"""Model pricing table and cost computation.

Prices are approximate USD per 1,000,000 tokens (input, output) for common
OpenAI and Anthropic models, used only when a caller does not supply
``cost_usd`` explicitly. Update freely — nothing else depends on exact values.
"""
from __future__ import annotations

# (input_per_1m, output_per_1m) in USD.
PRICES: dict[str, tuple[float, float]] = {
    # --- OpenAI ---
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    # --- Anthropic ---
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-3-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
}

# Fallback for unknown models so cost is never silently zero.
DEFAULT_PRICE: tuple[float, float] = (1.00, 3.00)

_MILLION = 1_000_000


def _lookup(model: str) -> tuple[float, float]:
    """Resolve a price, tolerating version suffixes like ``-20241022``."""
    if model in PRICES:
        return PRICES[model]
    for name, price in PRICES.items():
        if model.startswith(name):
            return price
    return DEFAULT_PRICE


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return the estimated USD cost for a call."""
    in_price, out_price = _lookup(model)
    cost = (tokens_in * in_price + tokens_out * out_price) / _MILLION
    return round(cost, 6)
