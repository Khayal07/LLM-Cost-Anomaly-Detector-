"""Unit tests for each statistical detector.

Records are inserted with controlled timestamps into an in-memory-style SQLite
database (via the ``db_session`` fixture), then a "current" record is evaluated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.detection.base import DetectionContext
from app.detection.detectors import (
    CostOutlierDetector,
    CostSpikeDetector,
    LoopSignatureDetector,
    TokenGrowthDetector,
)
from app.models import CallRecord

BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _add(session, ts, *, cost=0.001, tokens_in=100, caller="u", endpoint="/e", req_hash=None, model="gpt-4o-mini"):
    rec = CallRecord(
        ts=ts,
        provider="openai",
        model=model,
        endpoint=endpoint,
        caller=caller,
        tokens_in=tokens_in,
        tokens_out=0,
        total_tokens=tokens_in,
        cost_usd=cost,
        latency_ms=100,
        request_hash=req_hash,
    )
    session.add(rec)
    session.flush()
    return rec


def _ctx(session, record):
    return DetectionContext(session=session, record=record, settings=get_settings())


# --- LoopSignatureDetector ------------------------------------------------

def test_loop_fires_on_repeated_hash(db_session):
    for i in range(9):
        _add(db_session, BASE - timedelta(seconds=9 - i), req_hash="H")
    current = _add(db_session, BASE, req_hash="H")  # 10th identical
    result = LoopSignatureDetector().evaluate(_ctx(db_session, current))
    assert result is not None
    assert result.type == "loop"
    assert result.scope_value == "u"
    assert result.observed["count"] == 10


def test_loop_quiet_below_threshold(db_session):
    for i in range(4):
        _add(db_session, BASE - timedelta(seconds=4 - i), req_hash="H")
    current = _add(db_session, BASE, req_hash="H")
    assert LoopSignatureDetector().evaluate(_ctx(db_session, current)) is None


def test_loop_ignores_records_without_hash(db_session):
    for i in range(20):
        _add(db_session, BASE - timedelta(seconds=20 - i), req_hash=None)
    current = _add(db_session, BASE, req_hash=None)
    assert LoopSignatureDetector().evaluate(_ctx(db_session, current)) is None


# --- TokenGrowthDetector (prompt bloat) -----------------------------------

def test_prompt_bloat_fires_on_token_explosion(db_session):
    for i in range(10):
        _add(db_session, BASE - timedelta(seconds=100 - i), tokens_in=100)
    current = _add(db_session, BASE, tokens_in=1000)  # 10x the median
    result = TokenGrowthDetector().evaluate(_ctx(db_session, current))
    assert result is not None
    assert result.type == "prompt_bloat"
    assert result.observed["ratio"] >= 3


def test_prompt_bloat_quiet_on_stable_tokens(db_session):
    for i in range(10):
        _add(db_session, BASE - timedelta(seconds=100 - i), tokens_in=100)
    current = _add(db_session, BASE, tokens_in=120)
    assert TokenGrowthDetector().evaluate(_ctx(db_session, current)) is None


def test_prompt_bloat_needs_min_samples(db_session):
    for i in range(3):
        _add(db_session, BASE - timedelta(seconds=10 - i), tokens_in=100)
    current = _add(db_session, BASE, tokens_in=5000)
    assert TokenGrowthDetector().evaluate(_ctx(db_session, current)) is None


# --- CostOutlierDetector --------------------------------------------------

def test_cost_outlier_fires_on_expensive_call(db_session):
    costs = [0.008, 0.010, 0.009, 0.011, 0.010, 0.012, 0.009, 0.011, 0.010, 0.010]
    for i, c in enumerate(costs):
        _add(db_session, BASE - timedelta(seconds=100 - i), cost=c)
    current = _add(db_session, BASE, cost=1.0)
    result = CostOutlierDetector().evaluate(_ctx(db_session, current))
    assert result is not None
    assert result.type == "cost_outlier"
    assert result.scope_value == "/e"


def test_cost_outlier_quiet_on_normal_call(db_session):
    costs = [0.008, 0.010, 0.009, 0.011, 0.010, 0.012, 0.009, 0.011, 0.010, 0.010]
    for i, c in enumerate(costs):
        _add(db_session, BASE - timedelta(seconds=100 - i), cost=c)
    current = _add(db_session, BASE, cost=0.010)
    assert CostOutlierDetector().evaluate(_ctx(db_session, current)) is None


# --- CostSpikeDetector ----------------------------------------------------

def test_cost_spike_fires_on_volume_surge(db_session):
    # 8 historical 1-minute buckets, each a single modest-cost call.
    hist_costs = [0.008, 0.010, 0.009, 0.011, 0.010, 0.012, 0.009, 0.011]
    for k, c in enumerate(hist_costs, start=1):
        _add(db_session, BASE - timedelta(seconds=60 * k), cost=c)
    # Current bucket: a burst of many calls at BASE.
    for _ in range(19):
        _add(db_session, BASE, cost=0.01)
    current = _add(db_session, BASE, cost=0.01)  # current-bucket total ~0.20
    result = CostSpikeDetector().evaluate(_ctx(db_session, current))
    assert result is not None
    assert result.type == "cost_spike"
    assert result.scope_value == "/e"


def test_cost_spike_quiet_on_steady_traffic(db_session):
    hist_costs = [0.008, 0.010, 0.009, 0.011, 0.010, 0.012, 0.009, 0.011]
    for k, c in enumerate(hist_costs, start=1):
        _add(db_session, BASE - timedelta(seconds=60 * k), cost=c)
    current = _add(db_session, BASE, cost=0.010)  # one normal call this bucket
    assert CostSpikeDetector().evaluate(_ctx(db_session, current)) is None
