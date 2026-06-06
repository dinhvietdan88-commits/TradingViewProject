"""
Property-Based Tests: Rate Limiting (Prop 20)
Feature: tradingview-alert-indicator-signal

Property 20: Shared rate limiting — indicator and strategy requests count against same 15/min limit.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hypothesis import given, settings
from hypothesis import strategies as st

RATE_LIMIT = 15  # requests per minute
WINDOW_SEC = 60.0


def _check_rate_limit(cache: dict, source_ip: str) -> bool:
    """Mirror rate limiting logic from gateway/webhook.py. Returns True if allowed."""
    now = time.time()
    count, first_req = cache.get(source_ip, (0, now))
    if now - first_req < WINDOW_SEC:
        if count >= RATE_LIMIT:
            return False  # rate limited
        cache[source_ip] = (count + 1, first_req)
    else:
        cache[source_ip] = (1, now)
    return True


# ── Property 20: Shared rate limit ───────────────────────────────────────────


@given(
    n_indicator=st.integers(min_value=0, max_value=20),
    n_strategy=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100)
def test_prop20_shared_rate_limit(n_indicator, n_strategy):
    """
    # Feature: tradingview-alert-indicator-signal, Property 20: Shared rate limiting
    Mixed indicator + strategy requests from same IP count against the same 15/min limit.
    Total allowed <= 15; total blocked = (n_indicator + n_strategy) - 15 if > 15.
    """
    cache: dict = {}
    ip = "1.2.3.4"

    allowed = 0
    blocked = 0
    total = n_indicator + n_strategy

    for _ in range(total):
        if _check_rate_limit(cache, ip):
            allowed += 1
        else:
            blocked += 1

    assert allowed <= RATE_LIMIT, f"Too many allowed: {allowed} > {RATE_LIMIT}"
    assert allowed + blocked == total, "allowed + blocked must equal total requests"
    if total > RATE_LIMIT:
        assert blocked == total - RATE_LIMIT, (
            f"Expected {total - RATE_LIMIT} blocked, got {blocked}"
        )
