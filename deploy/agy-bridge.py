#!/usr/bin/env python3
"""
agy-bridge: HTTP sidecar that wraps agy CLI for Docker containers.

Runs on Server C HOST (not inside Docker). Provides:
  POST /analyze  → Execute agy --print with PTY wrapper
  GET  /health   → Bridge status + circuit breaker state

SCAR-005: agy requires PTY — we use `script -qfc` wrapper.
SCAR-006: ANTIGRAVITY_API_KEY must be Tier 1 to avoid quota issues.

Usage:
  # Install deps on host
  pip3 install fastapi uvicorn google-antigravity

  # Run manually
  ANTIGRAVITY_API_KEY=xxx python3 agy-bridge.py

  # Or via systemd (see /etc/systemd/system/agy-bridge.service)
"""

import asyncio
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agy-bridge")


# ── Circuit Breaker ──────────────────────────────────────────────

@dataclass
class CircuitBreaker:
    """Simple circuit breaker for agy CLI calls."""
    failure_threshold: int = 3
    recovery_timeout_sec: int = 120
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _state: str = field(default="CLOSED", init=False)

    def is_available(self) -> bool:
        if self._state == "OPEN":
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout_sec:
                self._state = "HALF_OPEN"
                log.info("Circuit breaker → HALF_OPEN (recovery attempt)")
                return True
            return False
        return True

    def record_success(self):
        self._failure_count = 0
        if self._state != "CLOSED":
            log.info(f"Circuit breaker → CLOSED (was {self._state})")
        self._state = "CLOSED"

    def record_failure(self, reason: str = ""):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "OPEN"
            log.warning(
                f"Circuit breaker → OPEN after {self._failure_count} failures. "
                f"Recovery in {self.recovery_timeout_sec}s. Last: {reason[:100]}"
            )

    @property
    def state(self) -> str:
        return self._state

    @property
    def info(self) -> dict:
        return {
            "state": self._state,
            "failure_count": self._failure_count,
            "threshold": self.failure_threshold,
            "recovery_timeout_sec": self.recovery_timeout_sec,
        }


# ── Global State ─────────────────────────────────────────────────

cb = CircuitBreaker()
AGY_PATH: Optional[str] = None
PTY_MODE: str = "direct"  # "pty" or "direct"
BIND_HOST = os.environ.get("AGY_BRIDGE_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("AGY_BRIDGE_PORT", "9100"))
DEFAULT_MODEL = os.environ.get("AGY_MODEL", "gemini-2.5-flash")
DEFAULT_TIMEOUT = int(os.environ.get("AGY_TIMEOUT_SEC", "25"))

# Stats
_stats = {
    "total_requests": 0,
    "success": 0,
    "failure": 0,
    "total_latency_ms": 0.0,
    "started_at": time.time(),
}


def _detect_agy() -> Optional[str]:
    """Find agy binary on PATH."""
    for name in ("agy", "localharness"):
        path = shutil.which(name)
        if path:
            return path
    # Check pip-installed location
    for base in (
        os.path.expanduser("~/.local/bin"),
        "/usr/local/bin",
        os.path.join(sys.prefix, "bin"),
    ):
        for name in ("agy", "localharness"):
            full = os.path.join(base, name)
            if os.path.isfile(full) and os.access(full, os.X_OK):
                return full
    return None


def _detect_pty_mode() -> str:
    """Check if we can use PTY wrapper (SCAR-005)."""
    # On Linux, use `script -qfc` to provide PTY
    if shutil.which("script"):
        return "pty"
    # On macOS, `script -q` syntax differs
    if sys.platform == "darwin" and shutil.which("script"):
        return "pty_macos"
    return "direct"


async def _run_agy(prompt: str, model: str, timeout_sec: int) -> dict:
    """Execute AI generation via agy CLI binary (primary) or google-genai SDK (fallback).

    Strategy:
      1. agy CLI binary with stdin redirect + --print-timeout (no PTY needed)
         Key: prompt must include "Do NOT use any tools" instruction to prevent
         workspace exploration. stdin redirect disables interactive tool use.
      2. google-genai SDK fallback (uses GEMINI_API_KEY directly)
    """
    global AGY_PATH, PTY_MODE

    # ── Strategy 1: agy CLI binary (file redirect, no PTY) ────────
    if AGY_PATH:
        import tempfile

        # Prepend instruction to prevent tool/file exploration
        constrained_prompt = (
            "IMPORTANT: Do NOT use any tools. Do NOT read any files. "
            "Do NOT explore the workspace. Answer the analysis directly "
            "based on your knowledge.\n\n" + prompt
        )

        # Write prompt to temp file — agy detects stdin PIPE as interactive
        # but file redirect (< file.txt) triggers proper single-shot mode
        prompt_file = None
        start = time.time()
        try:
            # Use ~/.cache (in ReadWritePaths) — /tmp is read-only under ProtectSystem=strict
            cache_dir = os.path.expanduser("~/.cache")
            os.makedirs(cache_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", prefix="agy_prompt_",
                dir=cache_dir, delete=False, encoding="utf-8",
            ) as f:
                f.write(constrained_prompt)
                prompt_file = f.name

            shell_cmd = (
                f"{AGY_PATH} --print --print-timeout {timeout_sec}s"
                f" --dangerously-skip-permissions"
                f" < {prompt_file}"
            )
            proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_sec + 5,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except (ProcessLookupError, NameError):
                pass
            log.warning(f"agy CLI timeout ({timeout_sec}s). Trying SDK fallback...")
        except FileNotFoundError:
            log.warning(f"agy binary not found: {AGY_PATH}. Trying SDK fallback...")
        except Exception as e:
            log.warning(f"agy CLI error: {e}. Trying SDK fallback...")
        else:
            latency_ms = (time.time() - start) * 1000
            output = stdout.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")[:200]
                log.warning(f"agy CLI exit code {proc.returncode}: {err[:100]}. Trying SDK...")
            elif output and len(output.strip()) >= 10:
                # Clean ANSI escape codes if any
                import re
                output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)
                output = output.replace('\r', '')
                log.info(f"agy CLI OK ({latency_ms:.0f}ms, {len(output)} chars)")
                return {
                    "success": True,
                    "advice": output.strip(),
                    "model": model,
                    "latency_ms": latency_ms,
                    "exit_code": 0,
                    "stdout_len": len(output),
                    "provider": "agy-cli",
                }
            else:
                log.warning("agy CLI returned empty/short response. Trying SDK...")
        finally:
            # Cleanup temp file
            if prompt_file:
                try:
                    os.unlink(prompt_file)
                except OSError:
                    pass

    # ── Strategy 2: google-genai SDK (fallback) ──────────────────
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTIGRAVITY_API_KEY")
    if api_key:
        try:
            from google import genai

            start = time.time()
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            # response.text can raise ValueError if no text parts
            try:
                advice = response.text
            except (ValueError, AttributeError):
                # Try extracting from candidates
                advice = None
                if response.candidates:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, 'text') and part.text:
                            advice = (advice or "") + part.text
            latency_ms = (time.time() - start) * 1000

            log.info(f"SDK response: advice_len={len(advice) if advice else 0}, latency={latency_ms:.0f}ms")

            if not advice or len(advice.strip()) < 10:
                return {
                    "success": False,
                    "error": f"Empty response from Gemini SDK fallback (advice_len={len(advice) if advice else 0})",
                    "latency_ms": latency_ms,
                }

            return {
                "success": True,
                "advice": advice.strip(),
                "model": model,
                "latency_ms": latency_ms,
                "exit_code": 0,
                "stdout_len": len(advice),
                "provider": "google-genai",
            }
        except ImportError:
            log.warning("google-genai SDK not installed.")
        except Exception as e:
            log.warning(f"google-genai SDK failed: {e}")
            return {
                "success": False,
                "error": f"Both agy CLI and SDK failed: {str(e)[:200]}",
                "latency_ms": (time.time() - start) * 1000 if 'start' in dir() else 0,
            }

    return {"success": False, "error": "No agy binary and no API key available"}


# ── FastAPI App ──────────────────────────────────────────────────

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
except ImportError:
    log.error("FastAPI not installed. Run: pip3 install fastapi uvicorn")
    sys.exit(1)

app = FastAPI(title="agy-bridge", version="1.0.0")


class AnalyzeRequest(BaseModel):
    prompt: str
    model: str = DEFAULT_MODEL
    timeout_sec: int = DEFAULT_TIMEOUT
    system_instruction: str = ""


@app.get("/health")
async def health():
    """Health check with circuit breaker state."""
    return {
        "status": "ok" if cb.is_available() else "degraded",
        "agy_binary": AGY_PATH or "NOT_FOUND",
        "pty_mode": PTY_MODE,
        "circuit_breaker": cb.info,
        "stats": {
            "total_requests": _stats["total_requests"],
            "success": _stats["success"],
            "failure": _stats["failure"],
            "avg_latency_ms": round(
                _stats["total_latency_ms"] / max(1, _stats["success"]), 1
            ),
            "uptime_sec": round(time.time() - _stats["started_at"]),
        },
    }


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Execute agy CLI analysis."""
    _stats["total_requests"] += 1

    if not cb.is_available():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Circuit breaker OPEN",
                "retry_after_sec": cb.recovery_timeout_sec,
                "circuit_breaker": cb.info,
            },
        )

    # Prepend system instruction to prompt if provided
    full_prompt = req.prompt
    if req.system_instruction:
        full_prompt = f"[System: {req.system_instruction}]\n\n{req.prompt}"

    try:
        result = await _run_agy(full_prompt, req.model, req.timeout_sec)
    except Exception as exc:
        log.error(f"_run_agy raised exception: {exc}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail={"error": str(exc)})

    log.info(f"_run_agy result: success={result.get('success')}, provider={result.get('provider', 'N/A')}")

    if result.get("success"):
        cb.record_success()
        _stats["success"] += 1
        _stats["total_latency_ms"] += result.get("latency_ms", 0)
        return result
    else:
        cb.record_failure(result.get("error", "unknown"))
        _stats["failure"] += 1
        if result.get("error", "").startswith("Timeout"):
            raise HTTPException(status_code=504, detail=result)
        raise HTTPException(status_code=500, detail=result)


# ── Startup ──────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global AGY_PATH, PTY_MODE
    AGY_PATH = _detect_agy()
    PTY_MODE = _detect_pty_mode()

    if AGY_PATH:
        log.info(f"✅ agy binary found: {AGY_PATH}")
    else:
        log.error("❌ agy binary NOT FOUND — bridge will return errors")

    log.info(f"PTY mode: {PTY_MODE}")
    log.info(f"Default model: {DEFAULT_MODEL}")
    log.info(f"Listening on {BIND_HOST}:{BIND_PORT}")

    # Verify ANTIGRAVITY_API_KEY
    key = os.environ.get("ANTIGRAVITY_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key:
        log.info(f"Auth key detected ({key[:6]}...)")
    else:
        log.warning("⚠️ No ANTIGRAVITY_API_KEY or GEMINI_API_KEY set!")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=BIND_HOST,
        port=BIND_PORT,
        log_level="info",
        access_log=True,
    )
