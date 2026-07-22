"""Detection orchestration: run detectors on ingest, dedup, and record incidents.

Detectors run synchronously on every ingested record (lowest time-to-detection).
A cooldown prevents re-opening the same scope+type incident while one is still
open or within ``COOLDOWN_SECONDS``, so a sustained anomaly yields one incident
rather than a flood.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.alerting.notifier import dispatch
from app.config import Settings, get_settings
from app.detection.base import DetectionContext, IncidentCandidate
from app.detection.detectors import ALL_DETECTORS, BaseDetector
from app.models import CallRecord, Incident


def _in_cooldown(session: Session, cand: IncidentCandidate, now, settings: Settings) -> bool:
    cutoff = now - timedelta(seconds=settings.cooldown_seconds)
    existing = session.execute(
        select(Incident.id)
        .where(
            Incident.type == cand.type,
            Incident.scope_type == cand.scope_type,
            Incident.scope_value == cand.scope_value,
            or_(Incident.status == "open", Incident.detected_at >= cutoff),
        )
        .limit(1)
    ).first()
    return existing is not None


def _candidate_to_incident(cand: IncidentCandidate, detected_at) -> Incident:
    return Incident(
        detected_at=detected_at,
        type=cand.type,
        severity=cand.severity,
        scope_type=cand.scope_type,
        scope_value=cand.scope_value,
        trigger_record_id=cand.trigger_record_id,
        score=cand.score,
        baseline=cand.baseline,
        observed=cand.observed,
        window_start=cand.window_start,
        window_end=cand.window_end,
        message=cand.message,
        status="open",
    )


def run_detection(
    session: Session,
    record: CallRecord,
    detectors: list[BaseDetector] | None = None,
) -> list[Incident]:
    """Evaluate all detectors against ``record`` and persist any new incidents."""
    settings = get_settings()
    detectors = detectors if detectors is not None else ALL_DETECTORS
    ctx = DetectionContext(session=session, record=record, settings=settings)

    created: list[Incident] = []
    for detector in detectors:
        try:
            candidate = detector.evaluate(ctx)
        except Exception:  # noqa: BLE001 - one bad detector must not block ingest
            continue
        if candidate is None or _in_cooldown(session, candidate, record.ts, settings):
            continue

        incident = _candidate_to_incident(candidate, record.ts)
        session.add(incident)
        session.flush()
        dispatch(incident)
        created.append(incident)

    return created
