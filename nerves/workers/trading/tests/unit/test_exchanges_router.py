from exchanges.base import ExchangeAdapter
from exchanges.registry import ExchangeRegistry
from exchanges.router import ExchangeRouter


class MockAdapter(ExchangeAdapter):
    def __init__(self, name: str):
        self._name = name

    @property
    def exchange_name(self) -> str:
        return self._name

    @property
    def exchange_id(self) -> str:
        return self._name

    @property
    def is_testnet(self) -> bool:
        return True

    @property
    def is_dry_run(self) -> bool:
        return True

    @property
    def supported_order_types(self):
        return ["MARKET"]

    async def execute_smart_order(self, *args, **kwargs):
        pass

    async def health_check(self):
        return {"healthy": True}


def test_registry_case_insensitivity():
    registry = ExchangeRegistry()
    adapter = MockAdapter("Binance")
    registry.register(adapter)

    # Check registration lowercases key
    assert "binance" in registry.list_exchange_ids()
    assert "Binance" not in registry.list_exchange_ids()

    # Check is_available is case-insensitive
    assert registry.is_available("binance") is True
    assert registry.is_available("BINANCE") is True
    assert registry.is_available("Binance") is True

    # Check get_adapter is case-insensitive
    assert registry.get_adapter("BINANCE") is adapter
    assert registry.get_adapter("Binance") is adapter
    assert registry.get_adapter("binance") is adapter

    # Check mark_unavailable/mark_available
    registry.mark_unavailable("BINANCE")
    assert registry.is_available("binance") is False
    registry.mark_available("Binance")
    assert registry.is_available("binance") is True


def test_router_case_insensitivity():
    registry = ExchangeRegistry()
    binance = MockAdapter("Binance")
    bybit = MockAdapter("Bybit")
    registry.register(binance)
    registry.register(bybit)

    strategy_config = {"strategy_1": {"exchange": "Bybit", "fallback": "Binance"}}

    router = ExchangeRouter(registry, strategy_config)

    # Explicit uppercase exchange resolving
    resolved = router.resolve_exchange({"exchange": "BINANCE"})
    assert resolved is binance

    # Strategy exchange resolving
    resolved = router.resolve_exchange({"strategy": "strategy_1"})
    assert resolved is bybit

    # Fallback resolving
    registry.mark_unavailable("Bybit")
    resolved = router.resolve_exchange({"strategy": "strategy_1"})
    assert resolved is binance
