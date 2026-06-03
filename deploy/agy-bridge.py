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


# ── CLI Health Tracker (Adaptive Strategy Gate) ──────────────────

@dataclass
class CliHealthTracker:
    """Tracks CLI latency and failure rate to decide strategy.

    Adaptive Strategy:
      - CLI healthy  → sequential (save tokens, ~0 extra latency)
      - CLI degraded → parallel race (burn 2x tokens, save ~8s latency)

    Degraded conditions (ANY triggers parallel):
      1. Rolling avg latency > latency_threshold_ms
      2. Recent failure rate > failure_rate_threshold
      3. Last N calls ALL failed (consecutive failures)

    SCAR-007b: Only burn 2x tokens when CLI is actually struggling.
    """
    window_size: int = 10            # rolling window of recent calls
    latency_threshold_ms: float = 18000.0   # 18s = CLI is sluggish
    failure_rate_threshold: float = 0.4     # 40% failure rate
    consecutive_fail_trigger: int = 2       # 2 consecutive fails → parallel

    _latencies: list = field(default_factory=list, init=False)
    _outcomes: list = field(default_factory=list, init=False)  # True=success, False=fail
    _consecutive_failures: int = field(default=0, init=False)

    def record(self, success: bool, latency_ms: float = 0.0):
        """Record a CLI call result."""
        self._outcomes.append(success)
        if success:
            self._latencies.append(latency_ms)
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

        # Trim to window
        if len(self._outcomes) > self.window_size:
            self._outcomes = self._outcomes[-self.window_size:]
        if len(self._latencies) > self.window_size:
            self._latencies = self._latencies[-self.window_size:]

    @property
    def is_degraded(self) -> bool:
        """True if CLI is struggling → should use parallel strategy."""
        # No data yet → first call, use sequential (give CLI a chance)
        if not self._outcomes:
            return False

        # Check consecutive failures
        if self._consecutive_failures >= self.consecutive_fail_trigger:
            return True

        # Check failure rate
        if len(self._outcomes) >= 3:
            fail_rate = self._outcomes.count(False) / len(self._outcomes)
            if fail_rate >= self.failure_rate_threshold:
                return True

        # Check avg latency
        if self._latencies:
            avg = sum(self._latencies) / len(self._latencies)
            if avg > self.latency_threshold_ms:
                return True

        return False

    @property
    def strategy(self) -> str:
        return "parallel" if self.is_degraded else "sequential"

    @property
    def info(self) -> dict:
        avg_lat = (sum(self._latencies) / len(self._latencies)) if self._latencies else 0
        fail_rate = (
            self._outcomes.count(False) / len(self._outcomes)
            if self._outcomes else 0
        )
        return {
            "strategy": self.strategy,
            "degraded": self.is_degraded,
            "avg_latency_ms": round(avg_lat, 1),
            "failure_rate": round(fail_rate, 3),
            "consecutive_failures": self._consecutive_failures,
            "samples": len(self._outcomes),
            "thresholds": {
                "latency_ms": self.latency_threshold_ms,
                "failure_rate": self.failure_rate_threshold,
                "consecutive_fails": self.consecutive_fail_trigger,
            },
        }


# ── Global State ─────────────────────────────────────────────────

cb = CircuitBreaker()
cli_health = CliHealthTracker()
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


import hashlib
import re
import tempfile

# ── Response Cache ───────────────────────────────────────────────

_response_cache: dict = {}  # {hash: (timestamp, result)}
CACHE_TTL = int(os.environ.get("AGY_CACHE_TTL", "300"))  # 5 min default


def _cache_key(prompt: str) -> str:
    """Generate cache key from prompt hash."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _get_cached(prompt: str) -> Optional[dict]:
    """Return cached response if within TTL."""
    key = _cache_key(prompt)
    if key in _response_cache:
        ts, result = _response_cache[key]
        if time.time() - ts < CACHE_TTL:
            cached_result = dict(result)
            cached_result["provider"] = f"{result['provider']}+cache"
            cached_result["cache_hit"] = True
            log.info(f"Cache HIT ({key[:8]}…): {result['provider']}, age={time.time()-ts:.0f}s")
            return cached_result
        else:
            del _response_cache[key]
    return None


def _put_cache(prompt: str, result: dict):
    """Store successful response in cache."""
    if result.get("success") and result.get("advice"):
        key = _cache_key(prompt)
        _response_cache[key] = (time.time(), result)
        # Evict old entries (max 50)
        if len(_response_cache) > 50:
            oldest = min(_response_cache, key=lambda k: _response_cache[k][0])
            del _response_cache[oldest]


def _clean_output(text: str) -> str:
    """Remove ANSI escape codes and carriage returns."""
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    return text.replace('\r', '').strip()


# ── Provider: agy CLI ────────────────────────────────────────────

async def _run_cli(prompt: str, timeout_sec: int) -> dict:
    """Execute via agy CLI binary with file redirect."""
    if not AGY_PATH:
        return {"success": False, "error": "No agy binary"}

    constrained_prompt = (
        "IMPORTANT: Do NOT use any tools. Do NOT read any files. "
        "Do NOT explore the workspace. Answer the analysis directly "
        "based on your knowledge.\n\n" + prompt
    )

    prompt_file = None
    start = time.time()
    try:
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
            proc.communicate(), timeout=timeout_sec + 5,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except (ProcessLookupError, NameError):
            pass
        return {"success": False, "error": f"CLI timeout ({timeout_sec}s)"}
    except Exception as e:
        return {"success": False, "error": f"CLI error: {e}"}
    finally:
        if prompt_file:
            try:
                os.unlink(prompt_file)
            except OSError:
                pass

    latency_ms = (time.time() - start) * 1000
    output = _clean_output(stdout.decode("utf-8", errors="replace"))

    if proc.returncode != 0:
        return {"success": False, "error": f"CLI exit {proc.returncode}"}
    if not output or len(output) < 10:
        return {"success": False, "error": "CLI empty response"}

    return {
        "success": True,
        "advice": output,
        "model": "gemini-2.5-flash",
        "latency_ms": latency_ms,
        "exit_code": 0,
        "stdout_len": len(output),
        "provider": "agy-cli",
    }


# ── Provider: google-genai SDK ───────────────────────────────────

async def _run_sdk(prompt: str, model: str) -> dict:
    """Execute via google-genai SDK directly."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTIGRAVITY_API_KEY")
    if not api_key:
        return {"success": False, "error": "No API key"}

    try:
        from google import genai

        start = time.time()
        client = genai.Client(api_key=api_key)
        # Run in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(model=model, contents=prompt),
        )
        try:
            advice = response.text
        except (ValueError, AttributeError):
            advice = None
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        advice = (advice or "") + part.text
        latency_ms = (time.time() - start) * 1000

        if not advice or len(advice.strip()) < 10:
            return {"success": False, "error": f"SDK empty response (len={len(advice) if advice else 0})"}

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
        return {"success": False, "error": "google-genai not installed"}
    except Exception as e:
        return {"success": False, "error": f"SDK error: {str(e)[:200]}"}


# ── Adaptive Strategy: Sequential ↔ Parallel ─────────────────────
# SCAR-007b: Pure sequential saves tokens but adds +8s latency on CLI fail.
# Pure parallel saves latency but burns 2x tokens every request.
# Adaptive: use CLI health metrics to auto-switch between the two.
#   CLI healthy  → sequential (1x tokens, ~0 extra latency)
#   CLI degraded → parallel race (2x tokens, saves ~8s on failover)

async def _run_sequential(prompt: str, model: str, timeout_sec: int,
                           has_cli: bool, has_sdk: bool) -> dict:
    """Sequential: CLI first → SDK only if CLI fails."""
    cli_result = None

    if has_cli:
        try:
            cli_result = await _run_cli(prompt, timeout_sec)
        except Exception as e:
            cli_result = {"success": False, "error": f"CLI exception: {e}"}

        # Record health
        cli_health.record(
            success=cli_result.get("success", False),
            latency_ms=cli_result.get("latency_ms", 0),
        )

        if cli_result.get("success"):
            log.info(f"[sequential] CLI OK ({cli_result['latency_ms']:.0f}ms)")
            return cli_result

        log.warning(f"[sequential] CLI failed: {cli_result.get('error', '?')}")
        if not has_sdk:
            return cli_result

    # SDK fallback
    log.info("[sequential] Falling back to SDK...")
    try:
        sdk_result = await _run_sdk(prompt, model)
    except Exception as e:
        sdk_result = {"success": False, "error": f"SDK exception: {e}"}

    if sdk_result.get("success"):
        cli_err = cli_result.get('error', 'N/A')[:60] if cli_result else "no CLI"
        log.info(f"[sequential] SDK fallback OK ({sdk_result['latency_ms']:.0f}ms) — CLI: {cli_err}")
        return sdk_result

    cli_err = cli_result.get('error', '?')[:80] if cli_result else "no binary"
    return {
        "success": False,
        "error": f"All failed: CLI={cli_err}; SDK={sdk_result.get('error','?')[:80]}",
    }


async def _run_parallel(prompt: str, model: str, timeout_sec: int,
                         has_cli: bool, has_sdk: bool) -> dict:
    """Parallel race: both fire simultaneously, first success wins.
    Used only when CLI is degraded (high latency / failures)."""

    tasks = {}
    if has_cli:
        tasks["cli"] = asyncio.create_task(_run_cli(prompt, timeout_sec))
    if has_sdk:
        tasks["sdk"] = asyncio.create_task(_run_sdk(prompt, model))

    if not tasks:
        return {"success": False, "error": "No providers available"}

    # Wait for first completion
    done, pending = await asyncio.wait(
        tasks.values(), return_when=asyncio.FIRST_COMPLETED,
    )

    # Check if any completed task succeeded
    winner = None
    winner_name = None
    for name, task in tasks.items():
        if task in done:
            result = task.result()
            if result.get("success"):
                winner = result
                winner_name = name
                break

    if winner:
        # Cancel remaining tasks
        for name, task in tasks.items():
            if task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        # Record CLI health if CLI participated
        if "cli" in tasks:
            cli_task = tasks["cli"]
            if cli_task in done:
                cli_result = cli_task.result()
                cli_health.record(
                    success=cli_result.get("success", False),
                    latency_ms=cli_result.get("latency_ms", 0),
                )
            else:
                # CLI was still pending when SDK won → CLI is slow
                cli_health.record(success=False)

        log.info(
            f"[parallel] {winner_name} won ({winner['latency_ms']:.0f}ms) "
            f"— health: {cli_health.strategy}"
        )
        return winner

    # First completed task failed — wait for remaining
    for task in pending:
        try:
            result = await asyncio.wait_for(task, timeout=5)
            if result.get("success"):
                # Record CLI health
                if "cli" in tasks:
                    cli_task = tasks["cli"]
                    cli_r = cli_task.result() if cli_task.done() else {"success": False}
                    cli_health.record(
                        success=cli_r.get("success", False),
                        latency_ms=cli_r.get("latency_ms", 0),
                    )
                log.info(f"[parallel] late winner ({result['latency_ms']:.0f}ms)")
                return result
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass

    # All failed
    cli_health.record(success=False)
    errors = []
    for name, task in tasks.items():
        if task.done():
            r = task.result()
            errors.append(f"{name}={r.get('error','?')[:60]}")
    return {"success": False, "error": f"All failed: {'; '.join(errors)}"}


async def _run_agy(prompt: str, model: str, timeout_sec: int) -> dict:
    """Adaptive strategy dispatcher.

    Checks CLI health metrics (rolling window) to decide:
      - Sequential (healthy CLI) → save tokens
      - Parallel (degraded CLI) → save latency

    Always checks cache first (0 tokens, <100ms).
    """
    # ── Cache check ──────────────────────────────────────────────
    cached = _get_cached(prompt)
    if cached:
        return cached

    has_cli = bool(AGY_PATH)
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTIGRAVITY_API_KEY")
    has_sdk = bool(api_key)

    if not has_cli and not has_sdk:
        return {"success": False, "error": "No agy binary and no API key available"}

    # ── Adaptive strategy gate ───────────────────────────────────
    strategy = cli_health.strategy if (has_cli and has_sdk) else "sequential"

    if strategy == "parallel":
        log.info(
            f"[adaptive] → PARALLEL (CLI degraded: "
            f"avg={cli_health.info['avg_latency_ms']:.0f}ms, "
            f"fail_rate={cli_health.info['failure_rate']:.0%})"
        )
        result = await _run_parallel(prompt, model, timeout_sec, has_cli, has_sdk)
    else:
        result = await _run_sequential(prompt, model, timeout_sec, has_cli, has_sdk)

    # Annotate result with strategy used
    if result.get("success"):
        result["strategy"] = strategy
        _put_cache(prompt, result)

    return result


# ── FastAPI App ──────────────────────────────────────────────────

try:
    from fastapi import FastAPI, HTTPException
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
    """Health check with circuit breaker and adaptive strategy state."""
    return {
        "status": "ok" if cb.is_available() else "degraded",
        "agy_binary": AGY_PATH or "NOT_FOUND",
        "pty_mode": PTY_MODE,
        "strategy": cli_health.info,  # adaptive: sequential ↔ parallel
        "circuit_breaker": cb.info,
        "cache": {
            "entries": len(_response_cache),
            "ttl_sec": CACHE_TTL,
        },
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
