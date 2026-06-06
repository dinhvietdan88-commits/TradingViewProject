"""
P11 — DaemonLifecycleManager
Starts, stops, monitors, and auto-restarts the CaptureDaemon Node.js process.

Design ref: design.md § "DaemonLifecycleManager"
"""

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Path to daemon entry point
_DAEMON_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tradingview-mcp"
_DAEMON_ENTRY = _DAEMON_DIR / "src" / "daemon" / "index.js"


class DaemonLifecycleManager:
    """
    Manages the Node.js CaptureDaemon as a child process.

    Design invariant (5): Only DaemonLifecycleManager can start/stop the daemon.
    No other component holds a process reference.
    """

    def __init__(
        self,
        node_path: str | None = None,
        port: int | None = None,
        host: str | None = None,
        max_restarts: int = 3,
        restart_window_sec: int = 300,  # 5 minutes
        health_poll_interval: int = 10,  # seconds
    ):
        self._node_path = node_path or config.MCP_NODE_PATH or "node"
        self._port = port or config.CAPTURE_DAEMON_PORT
        self._host = host or config.CAPTURE_DAEMON_HOST
        self._max_restarts = max_restarts
        self._restart_window_sec = restart_window_sec
        self._health_poll_interval = health_poll_interval

        self._process: asyncio.subprocess.Process | None = None
        self._restart_times: list[float] = []
        self._monitor_task: asyncio.Task | None = None
        self._stopping = False

    @property
    def is_running(self) -> bool:
        """Check if the daemon process is alive."""
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        """
        Start the CaptureDaemon as a child process.
        Waits for the health endpoint to become available.
        """
        if self.is_running:
            logger.info("Capture daemon already running, skipping start.")
            return

        if not _DAEMON_ENTRY.exists():
            logger.warning(
                f"CaptureDaemon entry not found at {_DAEMON_ENTRY} — "
                "capture features disabled. Run: cd tradingview-mcp && npm install"
            )
            self._stopping = True  # prevent health monitor from looping
            return

        self._stopping = False

        env = {
            **os.environ,
            "CAPTURE_DAEMON_PORT": str(self._port),
            "CAPTURE_DAEMON_HOST": self._host,
            "TV_CDP_PORT": str(config.MCP_CDP_PORT),
        }

        logger.info(f"Starting CaptureDaemon: {self._node_path} {_DAEMON_ENTRY}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                self._node_path,
                str(_DAEMON_ENTRY),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_DAEMON_DIR),
                env=env,
            )
        except FileNotFoundError:
            logger.error(
                f"Node.js not found at '{self._node_path}'. Cannot start daemon."
            )
            return
        except Exception as e:
            logger.error(f"Failed to start daemon process: {e}")
            return

        # Start background log forwarder
        asyncio.create_task(self._forward_logs())

        # Wait for health endpoint (up to 10s)
        if await self._wait_for_ready(timeout=10):
            logger.info(f"CaptureDaemon ready on http://{self._host}:{self._port}")
        else:
            logger.warning("CaptureDaemon started but health check not yet responding.")

        # Start health monitor
        self._monitor_task = asyncio.create_task(self._health_monitor())

    async def stop(self) -> None:
        """Gracefully stop the daemon process."""
        self._stopping = True

        # Cancel health monitor
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        if not self.is_running:
            logger.info("Capture daemon not running, nothing to stop.")
            self._process = None
            return

        logger.info("Stopping CaptureDaemon...")

        try:
            # On Windows, terminate() sends TerminateProcess
            # On Unix, we send SIGTERM for graceful shutdown
            if sys.platform == "win32":
                self._process.terminate()
            else:
                self._process.send_signal(signal.SIGTERM)

            # Wait up to 5s for graceful exit
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except TimeoutError:
                logger.warning("Daemon did not exit gracefully, killing...")
                self._process.kill()
                await self._process.wait()

        except ProcessLookupError:
            pass  # Already dead
        except Exception as e:
            logger.error(f"Error stopping daemon: {e}")

        self._process = None
        logger.info("CaptureDaemon stopped.")

    async def restart(self) -> None:
        """
        Restart the daemon, respecting the restart budget.
        Max 3 restarts per 5 minutes to prevent restart loops.
        """
        now = time.monotonic()
        # Prune old restart times outside the window
        self._restart_times = [
            t for t in self._restart_times if (now - t) < self._restart_window_sec
        ]

        if len(self._restart_times) >= self._max_restarts:
            logger.error(
                f"Restart budget exhausted ({self._max_restarts} restarts in "
                f"{self._restart_window_sec}s). Capture daemon disabled for "
                f"{self._restart_window_sec}s. Check Node.js / tradingview-mcp setup."
            )
            # Pause the monitor for one full window so we don't spam logs every 10s
            self._stopping = True
            await asyncio.sleep(self._restart_window_sec)
            # Allow retrying after cooldown
            self._stopping = False
            self._restart_times.clear()
            return

        self._restart_times.append(now)
        logger.info(
            f"Restarting CaptureDaemon "
            f"({len(self._restart_times)}/{self._max_restarts} restarts used)"
        )

        await self.stop()
        self._stopping = False
        await self.start()

    async def health_check(self) -> bool:
        """Ping the daemon /health endpoint. Returns True if healthy."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self._host}:{self._port}/health",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _wait_for_ready(self, timeout: int = 10) -> bool:
        """Poll health endpoint until it responds or timeout."""
        start = time.monotonic()
        while (time.monotonic() - start) < timeout:
            if await self.health_check():
                return True
            await asyncio.sleep(0.5)
        return False

    async def _health_monitor(self) -> None:
        """
        Background task: poll health every N seconds, auto-restart on crash.
        """
        while not self._stopping:
            try:
                await asyncio.sleep(self._health_poll_interval)

                if self._stopping:
                    break

                if not self.is_running:
                    logger.warning("CaptureDaemon process died — auto-restarting...")
                    await self.restart()
                    continue

                healthy = await self.health_check()
                if not healthy and self.is_running:
                    logger.warning(
                        "CaptureDaemon health check failed (process alive but not responding). "
                        "Will retry next poll."
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(5)

    async def _forward_logs(self) -> None:
        """Forward daemon stdout/stderr to Python logger."""
        if not self._process:
            return

        async def _read_stream(stream, level):
            try:
                async for line in stream:
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if text:
                        logger.log(level, f"[daemon] {text}")
            except ConnectionError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)

        # Read both streams concurrently
        if self._process.stdout:
            asyncio.create_task(_read_stream(self._process.stdout, logging.INFO))
        if self._process.stderr:
            asyncio.create_task(_read_stream(self._process.stderr, logging.WARNING))
