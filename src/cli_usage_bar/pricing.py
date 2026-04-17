"""Approximate token pricing for Anthropic models (USD per 1M tokens).

Values are coarse and should be considered indicative only. Users who need
precise cost accounting should treat these numbers as a starting point and
adjust them to match their latest invoice.
"""

from __future__ import annotations

# (input, cache_write, cache_read, output) USD per 1M tokens
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-4": (15.0, 18.75, 1.50, 75.0),
    "claude-opus-4-6": (15.0, 18.75, 1.50, 75.0),
    "claude-opus-4-7": (15.0, 18.75, 1.50, 75.0),
    "claude-sonnet-4": (3.0, 3.75, 0.30, 15.0),
    "claude-sonnet-4-6": (3.0, 3.75, 0.30, 15.0),
    "claude-haiku-4-5": (0.80, 1.0, 0.08, 4.0),
    "claude-haiku-4-5-20251001": (0.80, 1.0, 0.08, 4.0),
}

DEFAULT_PRICE = PRICING["claude-sonnet-4-6"]


def price_for(model: str) -> tuple[float, float, float, float]:
    if model in PRICING:
        return PRICING[model]
    lower = model.lower()
    for key, val in PRICING.items():
        if key in lower:
            return val
    return DEFAULT_PRICE


def compute_cost(
    model: str,
    input_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
    output_tokens: int,
) -> float:
    p_in, p_cwrite, p_cread, p_out = price_for(model)
    cost = (
        input_tokens * p_in
        + cache_creation_tokens * p_cwrite
        + cache_read_tokens * p_cread
        + output_tokens * p_out
    ) / 1_000_000.0
    return round(cost, 4)
