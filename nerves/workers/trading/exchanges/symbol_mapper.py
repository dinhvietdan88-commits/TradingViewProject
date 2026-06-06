from .base import SymbolMappingError


class SymbolMapper:
    """Translates canonical symbols to exchange-specific formats."""

    DEFAULT_RULES = {
        "binance": lambda s: s.upper().replace("/", "").replace("-", ""),
        "bybit": lambda s: s.upper().replace("/", "").replace("-", ""),
        "weex": lambda s: s.upper().replace("/", "").replace("-", "") + "_UMCBL",
    }

    def __init__(self, custom_mappings: dict[str, dict[str, str]] | None = None):
        self._custom = custom_mappings or {}

    def map_symbol(self, canonical: str, exchange_id: str) -> str:
        exchange_map = self._custom.get(exchange_id, {})
        canonical_upper = canonical.upper()
        if canonical_upper in exchange_map:
            return exchange_map[canonical_upper]

        rule = self.DEFAULT_RULES.get(exchange_id)
        if rule:
            return rule(canonical_upper)

        raise SymbolMappingError(
            f"Cannot map '{canonical}' for exchange '{exchange_id}'"
        )

    def reverse_map(self, exchange_symbol: str, exchange_id: str) -> str:
        exchange_map = self._custom.get(exchange_id, {})
        for canonical, mapped in exchange_map.items():
            if mapped == exchange_symbol:
                return canonical
        return exchange_symbol


# Singleton instance
_mapper = SymbolMapper()


def map_symbol(canonical: str, exchange_id: str) -> str:
    return _mapper.map_symbol(canonical, exchange_id)
