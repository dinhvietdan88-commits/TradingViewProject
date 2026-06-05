import logging
from typing import Dict, Any, List

from .base import ExchangeAdapter, ExchangeNotFoundError

log = logging.getLogger(__name__)


class ExchangeRegistry:
    """Manages registered exchange adapters. Singleton."""

    def __init__(self):
        self._adapters: Dict[str, ExchangeAdapter] = {}
        self._health_status: Dict[str, bool] = {}

    def register(self, adapter: ExchangeAdapter) -> None:
        name = adapter.exchange_name.lower()
        self._adapters[name] = adapter
        self._health_status[name] = True
        log.info(f"Registered ExchangeAdapter: {name}")

    def get_adapter(self, exchange_id: str) -> ExchangeAdapter:
        eid = exchange_id.lower()
        if eid not in self._adapters:
            available = list(self._adapters.keys())
            raise ExchangeNotFoundError(
                f"Exchange '{exchange_id}' not registered. Available: {available}"
            )
        return self._adapters[eid]

    def list_exchanges(self) -> List[Dict[str, Any]]:
        return [
            {
                "exchange": name,
                "testnet": adapter.is_testnet,
                "dry_run": adapter.is_dry_run,
                "healthy": self._health_status.get(name, False),
            }
            for name, adapter in self._adapters.items()
        ]

    def list_exchange_ids(self) -> List[str]:
        return list(self._adapters.keys())

    def mark_unavailable(self, exchange_id: str) -> None:
        self._health_status[exchange_id.lower()] = False

    def mark_available(self, exchange_id: str) -> None:
        self._health_status[exchange_id.lower()] = True

    def is_available(self, exchange_id: str) -> bool:
        return self._health_status.get(exchange_id.lower(), False)

    @property
    def default_exchange(self) -> str:
        """First registered exchange is the default."""
        import config

        default = config.DEFAULT_EXCHANGE.lower()
        if default in self._adapters:
            return default
        if not self._adapters:
            raise ExchangeNotFoundError("No exchanges registered")
        return next(iter(self._adapters))


# Singleton Instance
_registry = ExchangeRegistry()


def get_registry() -> ExchangeRegistry:
    return _registry


def init_registry() -> None:
    """Auto-detects configured exchanges based on config."""
    import config
    from .binance_adapter import BinanceAdapter
    from .bybit_adapter import BybitAdapter

    if config.BINANCE_API_KEY or getattr(config, "BINANCE_DRY_RUN", True):
        binance = BinanceAdapter(
            api_key=config.BINANCE_API_KEY,
            api_secret=config.BINANCE_API_SECRET,
            testnet=config.BINANCE_TESTNET,
            dry_run=config.BINANCE_DRY_RUN,
        )
        _registry.register(binance)

    if getattr(config, "BYBIT_API_KEY", None) or getattr(config, "BYBIT_DRY_RUN", True):
        bybit = BybitAdapter(
            api_key=getattr(config, "BYBIT_API_KEY", ""),
            api_secret=getattr(config, "BYBIT_API_SECRET", ""),
            testnet=getattr(config, "BYBIT_TESTNET", True),
            dry_run=getattr(config, "BYBIT_DRY_RUN", True),
        )
        _registry.register(bybit)

    if getattr(config, "WEEX_API_KEY", None) or getattr(config, "WEEX_DRY_RUN", True):
        from .weex_adapter import WeexAdapter

        weex = WeexAdapter(
            api_key=getattr(config, "WEEX_API_KEY", ""),
            api_secret=getattr(config, "WEEX_API_SECRET", ""),
            passphrase=getattr(config, "WEEX_PASSPHRASE", ""),
            testnet=getattr(config, "WEEX_TESTNET", True),
            dry_run=getattr(config, "WEEX_DRY_RUN", True),
        )
        _registry.register(weex)
