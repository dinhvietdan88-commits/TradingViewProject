"""
infrastructure.py — CliInfrastructure: async subprocess wrapper for Claude CLI.

⚠️ DEPRECATED (2025-05): Superseded by sdk_client.SdkClient (In-Process SDK).
This module is retained ONLY for backward compatibility. New code should
import and use SdkClient from sdk_client.py instead. This module will be
removed in a future cleanup PR.

Original responsibilities (Infrastructure Layer invariants):
- Single point of subprocess creation (asyncio.create_subprocess_exec only).
- Owns rate limiting (sliding 60-second window).
- Owns availability state (set once at startup via check_availability).
- Never calls Service or Interface layers.
- All execution errors are captured in CliResult; no exceptions escape invoke().
"""

import asyncio
import logging
import time
from dataclasses import dataclass

import config

log = logging.getLogger(__name__)


# ─── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class CliResult:
    """Structured outcome of one Claude CLI subprocess invocation."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    rate_limited: bool = False
    timed_out: bool = False

    @classmethod
    def rate_limit_exceeded(cls) -> "CliResult":
        return cls(
            success=False,
            stdout="",
            stderr="Rate limit exceeded",
            exit_code=-1,
            duration_seconds=0.0,
            rate_limited=True,
        )

    @classmethod
    def timeout(cls, timeout: float, stderr: str = "") -> "CliResult":
        return cls(
            success=False,
            stdout="",
            stderr=stderr or f"Timeout after {timeout}s",
            exit_code=-1,
            duration_seconds=timeout,
            timed_out=True,
        )

    @classmethod
    def error(cls, msg: str, duration: float = 0.0, exit_code: int = -1) -> "CliResult":
        return cls(
            success=False,
            stdout="",
            stderr=msg,
            exit_code=exit_code,
            duration_seconds=duration,
        )


# ─── Infrastructure class ──────────────────────────────────────────────────────


class CliInfrastructure:
    """
    Async subprocess wrapper for Claude CLI binary.

    Design invariants:
    - Spawns processes ONLY via asyncio.create_subprocess_exec (never subprocess.run).
    - Concurrency limited by asyncio.Semaphore (CLAUDE_CLI_MAX_PARALLEL).
    - Rate limiting via sliding 60-second window (CLAUDE_CLI_RATE_LIMIT).
    - check_availability() MUST be awaited at startup before any invoke() calls.
    """

    def __init__(
        self,
        cli_path: str = "",
        timeout: int = 0,
        rate_limit: int = 0,
        max_parallel: int = 0,
    ):
        self._cli_path: str = cli_path or getattr(config, "CLAUDE_CLI_PATH", "claude")
        self._timeout: int = timeout or getattr(config, "CLAUDE_CLI_TIMEOUT", 120)
        self._rate_limit: int = rate_limit or getattr(
            config, "CLAUDE_CLI_RATE_LIMIT", 10
        )
        max_par: int = max_parallel or getattr(config, "CLAUDE_CLI_MAX_PARALLEL", 2)
        self._semaphore = asyncio.Semaphore(max(1, max_par))
        self._request_timestamps: list[float] = []
        self._available: bool = False
        self._model: str = getattr(config, "CLAUDE_CLI_MODEL", "")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def check_availability(self) -> bool:
        """
        Probe whether the Claude CLI binary exists and responds.
        Sets self._available. Must be called at startup before invoke().

        Returns True if CLI is usable, False otherwise.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                version_info = stdout.decode("utf-8", errors="replace").strip()
                log.info(
                    f"Claude CLI available: {version_info!r} at '{self._cli_path}'"
                )
                self._available = True
            else:
                err = stderr.decode("utf-8", errors="replace").strip()[:200]
                log.warning(
                    f"Claude CLI returned non-zero at '{self._cli_path}': {err}"
                )
                self._available = False
        except FileNotFoundError:
            log.warning(f"Claude CLI binary not found at '{self._cli_path}'")
            self._available = False
        except TimeoutError:
            log.warning(f"Claude CLI version check timed out for '{self._cli_path}'")
            self._available = False
        except Exception as exc:
            log.warning(f"Claude CLI availability check failed: {exc}")
            self._available = False
        return self._available

    @property
    def available(self) -> bool:
        """Whether CLI binary was confirmed available at startup."""
        return self._available

    async def invoke(
        self,
        prompt: str,
        system_prompt: str = "",
        image_path: str | None = None,
    ) -> CliResult:
        """
        Execute Claude CLI with the given prompt.

        Args:
            prompt: Main user prompt text (passed via stdin to avoid argv limits).
            system_prompt: Optional system/context prepended to prompt.
            image_path: If set, grants Read access to the image directory via
                        --add-dir and --allowedTools Read flags.

        Returns:
            CliResult — never raises; all errors are captured in the result.

        Property 1 guarantee: uses asyncio.create_subprocess_exec exclusively.
        Property 2 guarantee: rejects via rate_limited=True if window exceeded.
        Property 9 guarantee: kills subprocess on timeout, sets timed_out=True.
        """
        if not self._check_rate_limit():
            log.warning("Claude CLI: rate limit exceeded — request rejected")
            return CliResult.rate_limit_exceeded()

        full_prompt = (
            f"{system_prompt}\n\n{prompt}".strip() if system_prompt else prompt
        )
        args = self._build_args(image_path)

        t_start = time.monotonic()
        async with self._semaphore:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                duration = time.monotonic() - t_start
                msg = f"Claude CLI binary not found at '{self._cli_path}'"
                log.error(msg)
                return CliResult.error(msg, duration)
            except Exception as exc:
                duration = time.monotonic() - t_start
                log.error(f"Claude CLI subprocess spawn failed: {exc}")
                return CliResult.error(str(exc), duration)

            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(input=full_prompt.encode("utf-8")),
                    timeout=self._timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                duration = time.monotonic() - t_start
                log.warning(f"Claude CLI timed out after {self._timeout}s")
                return CliResult.timeout(self._timeout)

        duration = time.monotonic() - t_start
        rc = proc.returncode
        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = stderr_b.decode("utf-8", errors="replace").strip()

        if rc != 0:
            log.warning(f"Claude CLI rc={rc} stderr={stderr[:200]!r}")
            return CliResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                exit_code=rc,
                duration_seconds=duration,
            )

        log.debug(f"Claude CLI success in {duration:.2f}s ({len(stdout)} chars)")
        self._record_timestamp()
        return CliResult(
            success=True,
            stdout=stdout,
            stderr=stderr,
            exit_code=0,
            duration_seconds=duration,
        )

    # ── Rate limiting ──────────────────────────────────────────────────────────

    def _check_rate_limit(self) -> bool:
        """
        Return True if request is within the sliding 60-second window limit.
        Records the timestamp only on success (invoke() calls _record_timestamp after exec).
        """
        self._prune_timestamps()
        if len(self._request_timestamps) >= self._rate_limit:
            return False
        return True

    def _record_timestamp(self) -> None:
        """Record a successful invocation timestamp for rate limiting."""
        self._request_timestamps.append(time.monotonic())

    def _prune_timestamps(self) -> None:
        """Remove timestamps older than 60 seconds from the sliding window."""
        cutoff = time.monotonic() - 60.0
        self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _build_args(self, image_path: str | None = None) -> list[str]:
        """Build the subprocess argument list."""
        args = [self._cli_path, "-p", "--output-format", "text"]
        if self._model:
            args += ["--model", self._model]
        if image_path:
            from pathlib import Path as _Path

            img = _Path(image_path).resolve()
            args += [
                "--add-dir",
                str(img.parent),
                "--allowedTools",
                "Read",
                "--dangerously-skip-permissions",
            ]
        return args

    def get_stats(self) -> dict:
        """Return current rate-limit and availability stats."""
        self._prune_timestamps()
        return {
            "available": self._available,
            "cli_path": self._cli_path,
            "rate_limit": self._rate_limit,
            "requests_in_window": len(self._request_timestamps),
            "timeout_seconds": self._timeout,
            "model": self._model or "(default)",
        }
