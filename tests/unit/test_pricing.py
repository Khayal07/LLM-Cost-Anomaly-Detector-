"""Unit tests for the pricing table and cost computation."""
from __future__ import annotations

from app.pricing import DEFAULT_PRICE, compute_cost


def test_exact_model_cost():
    # gpt-4o-mini: (1000*0.15 + 500*0.60) / 1e6
    assert compute_cost("gpt-4o-mini", 1000, 500) == round((1000 * 0.15 + 500 * 0.60) / 1e6, 6)


def test_versioned_id_prefers_longest_prefix():
    # A versioned mini id must NOT be priced as full gpt-4o.
    versioned = compute_cost("gpt-4o-mini-2024-07-18", 1000, 500)
    mini = compute_cost("gpt-4o-mini", 1000, 500)
    full = compute_cost("gpt-4o", 1000, 500)
    assert versioned == mini
    assert versioned < full


def test_versioned_gpt4o_and_claude():
    assert compute_cost("gpt-4o-2024-11-20", 1000, 0) == compute_cost("gpt-4o", 1000, 0)
    assert compute_cost("claude-3-5-sonnet-20241022", 1000, 0) == compute_cost("claude-3-5-sonnet", 1000, 0)


def test_unknown_model_uses_default():
    d_in, d_out = DEFAULT_PRICE
    assert compute_cost("some-future-model", 1000, 1000) == round((1000 * d_in + 1000 * d_out) / 1e6, 6)
