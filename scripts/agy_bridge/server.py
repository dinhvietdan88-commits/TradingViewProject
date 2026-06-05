"""
agy-bridge: FastAPI sidecar that wraps agy CLI for Docker containers.

Runs on Server C HOST (not in Docker) as a systemd service.
Listens on 127.0.0.1:9100 (localhost only — Docker reaches via host.docker.internal).

Architecture:
  Docker (analyzer) ──HTTP :9100──► Host (agy-bridge) ──subprocess──► agy --print

Harness Pattern: Adapted from AQH 7-gate pipeline (Go-native)
  Gate 0: Health check (circuit breaker state)
  Gate 1: Request validation (prompt length, model)
  Gate 2: Execution (agy --print subprocess)
  Gate 3: Response validation (non-empty, exit code)
  Gate 4: Metric recording (latency, success/fail)
"""

import asyncio
import logging
import os
import shutil
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════

AGY_BINARY = os.getenv(
    "AGY_BINARY_PATH",
    shutil.which("agy") or "/usr/local/bin/agy",
)
DEFAULT_TIMEOUT = int(os.getenv("AGY_DEFAULT_TIMEOUT", "25"))
DEFAULT_MODEL = os.getenv("AGY_DEFAULT_MODEL", "gemini-2.5-flash")
BRIDGE_PORT = int(os.getenv("AGY_BRIDGE_PORT", "9100"))

# ── PTY Wrapper (SCAR-005: Issue #76 — agy silences stdout in non-TTY) ──
# agy --print suppresses output when piped through subprocess.
# Workaround: wrap with `unbuffer` (preferred) or `script` to emulate TTY.
UNBUFFER_BINARY = shutil.which("unbuffer")
SCRIPT_BINARY = shutil.which("script")
PTY_MODE = "unbuffer" if UNBUFFER_BINARY else ("script" if SCRIPT_BINARY else "none")

# ── Warm Session: reuse agy conversation to avoid re-init each call ──
# When set, agy --continue --conversation <ID> keeps model context warm.
# Empty = each call is a fresh one-shot (cold start).
AGY_SESSION_ENABLED = os.getenv("AGY_SESSION_ENABLED", "true").lower() == "true"
_agy_last_conversation_id: str = ""

log = logging.getLogger("agy-bridge")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
)


# ════════════════════════════════════════════════════════════════
# Circuit Breaker — prevents thundering herd when agy is down
# ════════════════════════════════════════════════════════════════


class BridgeCircuitBreaker:
    """
    3-state circuit breaker for the agy subprocess.
    Mirrors ai_circuit_breaker.py pattern used in the analyzer.

    States:
      CLOSED    — normal operation, all calls pass through
      OPEN      — agy is down, reject immediately (recovery after N seconds)
      HALF_OPEN — allow one probe call to test recovery
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_sec: int = 60,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.consecutive_failures = 0
        self.last_failure_time: float = 0
        self.state = "CLOSED"
        self.total_successes = 0
        self.total_failures = 0

    def is_available(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.recovery_timeout_sec:
                self.state = "HALF_OPEN"
                log.info("Circuit breaker → HALF_OPEN (probing)")
                return True
            return False
        # HALF_OPEN — allow one probe
        return True

    def record_success(self):
        self.consecutive_failures = 0
        self.total_successes += 1
        if self.state != "CLOSED":
            log.info(f"Circuit breaker → CLOSED (was {self.state})")
            self.state = "CLOSED"

    def record_failure(self, reason: str = ""):
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= self.failure_threshold:
            if self.state != "OPEN":
                log.warning(
                    f"Circuit breaker → OPEN after {self.consecutive_failures} "
                    f"consecutive failures. Reason: {reason}"
                )
            self.state = "OPEN"

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_sec": self.recovery_timeout_sec,
        }


breaker = BridgeCircuitBreaker()


# ════════════════════════════════════════════════════════════════
# FastAPI Application
# ════════════════════════════════════════════════════════════════

app = FastAPI(
    title="agy-bridge",
    description="HTTP bridge wrapping agy CLI for Docker containers on Server C",
    version="1.0.0",
)


# ── Request / Response Models ──────────────────────────────────


class AnalyzeRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)
    model: str = Field(default=DEFAULT_MODEL)
    timeout_sec: int = Field(default=DEFAULT_TIMEOUT, ge=5, le=120)
    system_instruction: str = Field(default="")


class AnalyzeResponse(BaseModel):
    advice: str
    model: str
    latency_ms: float
    exit_code: int
    stdout_len: int
    stderr_preview: str = ""


class HealthResponse(BaseModel):
    status: str
    agy_binary: str
    agy_found: bool
    pty_mode: str
    has_api_key: bool
    circuit_breaker: dict
    uptime_sec: float


_start_time = time.time()


# ── Endpoints ──────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    """Gate 0: Pre-flight health check."""
    agy_found = os.path.isfile(AGY_BINARY) or shutil.which("agy") is not None
    has_api_key = bool(os.environ.get("ANTIGRAVITY_API_KEY"))
    return HealthResponse(
        status="healthy" if agy_found and breaker.state != "OPEN" else "degraded",
        agy_binary=AGY_BINARY,
        agy_found=agy_found,
        pty_mode=PTY_MODE,
        has_api_key=has_api_key,
        circuit_breaker=breaker.to_dict(),
        uptime_sec=round(time.time() - _start_time, 1),
    )


@app.get("/models")
async def list_models():
    """
    Discover which model agy is currently using.
    agy CLI does not have a /models subcommand — model routing is internal.
    We probe via a short --print call to check the active model.
    """
    configured_model = DEFAULT_MODEL
    agy_found = os.path.isfile(AGY_BINARY) or shutil.which("agy") is not None
    return {
        "configured_model": configured_model,
        "agy_binary": AGY_BINARY,
        "agy_found": agy_found,
        "session_enabled": AGY_SESSION_ENABLED,
        "note": (
            "agy CLI handles model routing internally. "
            "Set AGY_DEFAULT_MODEL env var to override. "
            "Available models depend on your AI Studio tier and ANTIGRAVITY_API_KEY quota."
        ),
        "hint": (
            'To verify: agy --print "What model are you using?" --print-timeout 10s'
        ),
    }


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """
    Gate 2: Execute agy --print with the given prompt.

    Spawns agy as a subprocess, captures stdout, and returns
    the AI-generated analysis text.
    """
    # ── Gate 0: Circuit Breaker check ──
    if not breaker.is_available():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "agy circuit breaker OPEN",
                "state": breaker.state,
                "retry_after_sec": max(
                    0,
                    breaker.recovery_timeout_sec
                    - (time.time() - breaker.last_failure_time),
                ),
            },
        )

    # ── Gate 1: Build command with PTY wrapper (SCAR-005) ──
    agy_cmd = [AGY_BINARY, "--print", req.prompt]
    if req.timeout_sec:
        agy_cmd.extend(["--print-timeout", f"{req.timeout_sec}s"])

    # Warm session: reuse conversation to avoid re-init overhead
    global _agy_last_conversation_id
    if AGY_SESSION_ENABLED and _agy_last_conversation_id:
        agy_cmd.extend(["--continue", "--conversation", _agy_last_conversation_id])
        log.debug(f"Reusing warm session: {_agy_last_conversation_id}")

    # Wrap with PTY to fix stdout suppression in non-TTY context
    if PTY_MODE == "unbuffer":
        cmd = [UNBUFFER_BINARY] + agy_cmd
    elif PTY_MODE == "script":
        # script -q -c 'agy ...' /dev/null
        cmd = [SCRIPT_BINARY, "-q", "-c", " ".join(agy_cmd), "/dev/null"]
    else:
        cmd = agy_cmd
        log.warning(
            "No PTY wrapper found (install 'expect' package for unbuffer). "
            "agy --print may produce empty stdout."
        )

    log.info(
        f"Executing agy --print (timeout={req.timeout_sec}s, "
        f"prompt_len={len(req.prompt)}, pty={PTY_MODE})"
    )

    start = time.monotonic()
    proc: Optional[asyncio.subprocess.Process] = None

    # Build env: inherit host env + ensure ANTIGRAVITY_API_KEY is passed
    subprocess_env = dict(os.environ)

    try:
        # ── Gate 2: Execution ──
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_env,
        )

        # Wait with timeout (add 5s grace period over agy's own timeout)
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=req.timeout_sec + 10,
        )

        latency_ms = (time.monotonic() - start) * 1000
        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

        # ── Gate 3: Response validation ──
        if proc.returncode == 0 and len(stdout_text) > 0:
            breaker.record_success()
            log.info(f"agy OK: {latency_ms:.0f}ms, stdout={len(stdout_text)} chars")
            return AnalyzeResponse(
                advice=stdout_text,
                model=req.model,
                latency_ms=round(latency_ms, 1),
                exit_code=0,
                stdout_len=len(stdout_text),
                stderr_preview=stderr_text[:200] if stderr_text else "",
            )
        else:
            error_detail = f"exit_code={proc.returncode}, stderr={stderr_text[:300]}"
            breaker.record_failure(error_detail)
            log.warning(f"agy FAIL: {error_detail}")
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "agy returned non-zero or empty stdout",
                    "exit_code": proc.returncode,
                    "stderr": stderr_text[:500],
                },
            )

    except asyncio.TimeoutError:
        breaker.record_failure(f"timeout after {req.timeout_sec}s")
        log.warning(f"agy TIMEOUT after {req.timeout_sec}s")
        # Kill the process if still running
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        raise HTTPException(
            status_code=504,
            detail={
                "error": f"agy timeout after {req.timeout_sec}s",
                "timeout_sec": req.timeout_sec,
            },
        )

    except FileNotFoundError:
        breaker.record_failure("agy binary not found")
        log.error(f"agy binary not found at: {AGY_BINARY}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": f"agy binary not found at {AGY_BINARY}",
                "hint": "Run: curl -fsSL https://antigravity.google/cli/install.sh | bash",
            },
        )

    except HTTPException:
        raise  # Re-raise our own exceptions

    except Exception as exc:
        breaker.record_failure(str(exc))
        log.exception(f"agy unexpected error: {exc}")
        raise HTTPException(
            status_code=500,
            detail={"error": f"Unexpected error: {str(exc)[:300]}"},
        )


# ════════════════════════════════════════════════════════════════
# Entry point (for direct execution)
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    log.info(f"Starting agy-bridge on 127.0.0.1:{BRIDGE_PORT}")
    log.info(f"agy binary: {AGY_BINARY}")
    log.info(f"Default timeout: {DEFAULT_TIMEOUT}s")
    log.info(f"Default model: {DEFAULT_MODEL}")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=BRIDGE_PORT,
        log_level="info",
    )
