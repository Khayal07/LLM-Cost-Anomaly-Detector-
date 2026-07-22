"""Unit tests for the pure statistical helpers."""
from __future__ import annotations

import math

from app.detection.stats import iqr_bounds, mean_std, median, rolling_stats, zscore


def test_mean_std_basic():
    mean, std, n = mean_std([2, 4, 4, 4, 5, 5, 7, 9])
    assert mean == 5.0
    assert n == 8
    assert math.isclose(std, 2.138, abs_tol=1e-3)  # sample stddev (ddof=1)


def test_mean_std_empty_and_singleton():
    assert mean_std([]) == (0.0, 0.0, 0)
    assert mean_std([42]) == (42.0, 0.0, 1)  # stddev undefined -> 0


def test_zscore_normal():
    assert zscore(10, 5, 2.5) == 2.0


def test_zscore_zero_std_is_zero():
    # No variance -> no signal, so we never divide by zero or false-positive.
    assert zscore(100, 5, 0) == 0.0


def test_iqr_bounds_flags_high_outlier():
    values = [10, 11, 12, 13, 14, 15]
    low, high = iqr_bounds(values, k=1.5)
    assert 100 > high  # a value of 100 would be well above the upper fence
    assert low < 10


def test_iqr_bounds_empty():
    assert iqr_bounds([]) == (0.0, 0.0)


def test_median():
    assert median([3, 1, 2]) == 2.0
    assert median([]) == 0.0


def test_rolling_stats_shape():
    snap = rolling_stats([1, 2, 3])
    assert set(snap) == {"mean", "stddev", "n"}
    assert snap["n"] == 3
    assert snap["mean"] == 2.0
