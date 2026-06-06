from typing import Dict, Any, Optional
import json

from .base import ExchangeAdapter, ExchangeUnavailableError
from .registry import ExchangeRegistry


class ExchangeRouter:
    """Routes trade signals to the appropriate exchange adapter."""

    def __init__(self, registry: ExchangeRegistry, strategy_config: Dict[str, Dict]):
        self._registry = registry
        self._strategy_config = strategy_config  # {strategy_id: {exchange, fallback}}

    def resolve_exchange(self, payload: Dict[str, Any]) -> ExchangeAdapter:
        """Determine target exchange from payload or strategy config."""
        # 1. Explicit exchange in payload
        exchange_id = payload.get("exchange")

        # 2. Strategy-based lookup
        if not exchange_id:
            strategy = payload.get("strategy", "")
            if strategy in self._strategy_config:
                exchange_id = self._strategy_config[strategy].get("exchange")

        # 3. Default exchange
        if not exchange_id:
            exchange_id = self._registry.default_exchange

        # Normalize to lower
        if exchange_id:
            exchange_id = exchange_id.lower()

        # Validate and check health
        if not self._registry.is_available(exchange_id):
            fallback_id = self._get_fallback(exchange_id, payload)
            if fallback_id:
                fallback_id = fallback_id.lower()
            if fallback_id and self._registry.is_available(fallback_id):
                return self._registry.get_adapter(fallback_id)
            elif not fallback_id or not self._registry.is_available(fallback_id):
                raise ExchangeUnavailableError(
                    f"Primary '{exchange_id}' and fallback are both unavailable"
                )

        return self._registry.get_adapter(exchange_id)

    def _get_fallback(self, primary_id: str, payload: Dict) -> Optional[str]:
        strategy = payload.get("strategy", "")
        if strategy in self._strategy_config:
            fallback = self._strategy_config[strategy].get("fallback")
            return fallback.lower() if fallback else None
        return None


# Singleton initialization
_router: Optional[ExchangeRouter] = None


def get_router() -> ExchangeRouter:
    from .registry import get_registry
    import config

    global _router
    if _router is None:
        try:
            strategy_config = json.loads(getattr(config, "STRATEGY_EXCHANGE_MAP", "{}"))
        except (json.JSONDecodeError, TypeError):
            strategy_config = {}
        _router = ExchangeRouter(get_registry(), strategy_config)
    return _router
