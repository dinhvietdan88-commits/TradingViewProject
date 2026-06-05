import asyncio
import logging

from .registry import ExchangeRegistry

log = logging.getLogger(__name__)


class HealthMonitor:
    """Background task to monitor exchange connectivity and state."""

    def __init__(self, registry: ExchangeRegistry, check_interval_sec: int = 60):
        self._registry = registry
        self._check_interval = check_interval_sec
        self._task = None

    async def _monitor_loop(self):
        log.info(f"HealthMonitor started (interval: {self._check_interval}s)")
        while True:
            try:
                for exchange_id in self._registry.list_exchange_ids():
                    adapter = self._registry.get_adapter(exchange_id)
                    health = await adapter.health_check()

                    if health["healthy"]:
                        if not self._registry.is_available(exchange_id):
                            log.info(f"Exchange {exchange_id} recovered.")
                        self._registry.mark_available(exchange_id)
                    else:
                        if self._registry.is_available(exchange_id):
                            log.warning(
                                f"Exchange {exchange_id} unavailable: {health['error']}"
                            )
                        self._registry.mark_unavailable(exchange_id)
            except Exception as e:
                log.error(f"HealthMonitor loop error: {e}", exc_info=True)

            await asyncio.sleep(self._check_interval)

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._monitor_loop())

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None


# Singleton instance
_monitor = None


def start_health_monitor() -> None:
    from .registry import get_registry
    import config

    global _monitor
    if _monitor is None:
        interval = getattr(config, "EXCHANGE_HEALTH_INTERVAL", 60)
        _monitor = HealthMonitor(get_registry(), interval)
        _monitor.start()


def stop_health_monitor() -> None:
    global _monitor
    if _monitor:
        _monitor.stop()
        _monitor = None
