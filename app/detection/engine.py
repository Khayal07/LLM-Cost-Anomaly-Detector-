"""Detection orchestration.

Phase 1 placeholder: exposes ``run_detection`` so the ingestion layer is fully
wired, but returns no incidents yet. Phase 2 registers the statistical
detectors and cooldown/dedup logic here.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CallRecord, Incident


def run_detection(session: Session, record: CallRecord) -> list[Incident]:
    """Run all registered detectors against a freshly ingested record."""
    return []
