"""Detector interface and shared value objects.

A future model-based detector only has to subclass ``BaseDetector`` and
implement ``evaluate`` — the engine and API are agnostic to how the decision is
made.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CallRecord


def epoch(dt: datetime) -> float:
    """Seconds since the epoch, treating naive datetimes as UTC.

    SQLite returns naive datetimes while Postgres returns aware ones; this keeps
    time-bucketing consistent across both backends.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@dataclass
class DetectionContext:
    """Everything a detector needs: the new record plus a session to look back."""

    session: Session
    record: CallRecord
    settings: Settings


@dataclass
class IncidentCandidate:
    type: str
    scope_type: str
    scope_value: str
    severity: str = "medium"
    score: float | None = None
    baseline: dict[str, Any] | None = None
    observed: dict[str, Any] | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    message: str = ""
    trigger_record_id: int | None = None


class BaseDetector:
    """Base class for all detectors."""

    type: str = "base"

    def evaluate(self, ctx: DetectionContext) -> IncidentCandidate | None:
        raise NotImplementedError


def severity_from_zscore(z: float, threshold: float) -> str:
    if z >= 2 * threshold:
        return "high"
    if z >= 1.5 * threshold:
        return "medium"
    return "low"
