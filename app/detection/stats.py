"""Pure statistical helpers for the detection layer.

No database or app imports here — everything is a plain function over numbers so
these are trivially unit-testable and reusable by any detector (statistical or,
later, model-based).
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def mean_std(values: Iterable[float]) -> tuple[float, float, int]:
    """Return (mean, sample_stddev, n). stddev is 0 when n < 2."""
    arr = np.asarray(list(values), dtype=float)
    n = int(arr.size)
    if n == 0:
        return 0.0, 0.0, 0
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    return mean, std, n


def zscore(value: float, mean: float, std: float) -> float:
    """Standard score. Returns 0.0 when stddev is 0 (no variance -> no signal)."""
    if std <= 0:
        return 0.0
    return (value - mean) / std


def iqr_bounds(values: Iterable[float], k: float = 1.5) -> tuple[float, float]:
    """Return (lower, upper) Tukey fences: [Q1 - k*IQR, Q3 + k*IQR]."""
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def median(values: Iterable[float]) -> float:
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return 0.0
    return float(np.median(arr))


def rolling_stats(values: Iterable[float]) -> dict[str, float]:
    """Snapshot of a baseline window, suitable for storing on an incident."""
    mean, std, n = mean_std(values)
    return {"mean": mean, "stddev": std, "n": n}
