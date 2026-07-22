"""Incident query endpoints: listing (for polling/alerting) and drill-down."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CallRecord, Incident
from app.schemas import IncidentDetail, IncidentOut

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=list[IncidentOut])
def list_incidents(
    status: str | None = None,
    type: str | None = None,
    scope_value: str | None = None,
    since: datetime | None = None,
    limit: int = Query(100, le=1000),
    session: Session = Depends(get_session),
) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.detected_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Incident.status == status)
    if type:
        stmt = stmt.where(Incident.type == type)
    if scope_value:
        stmt = stmt.where(Incident.scope_value == scope_value)
    if since:
        stmt = stmt.where(Incident.detected_at >= since)
    return list(session.execute(stmt).scalars().all())


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(
    incident_id: int,
    window: int = Query(50, le=500),
    session: Session = Depends(get_session),
) -> IncidentDetail:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")

    # Pull the call records around the incident, scoped to whatever the detector
    # flagged (endpoint or caller), so the UI can show the pattern that fired it.
    end = incident.window_end or incident.detected_at
    start = incident.window_start or (end - timedelta(minutes=10))

    stmt = (
        select(CallRecord)
        .where(CallRecord.ts >= start, CallRecord.ts <= end)
        .order_by(CallRecord.ts.desc())
        .limit(window)
    )
    if incident.scope_type == "endpoint":
        stmt = stmt.where(CallRecord.endpoint == incident.scope_value)
    elif incident.scope_type == "caller":
        stmt = stmt.where(CallRecord.caller == incident.scope_value)

    records = list(session.execute(stmt).scalars().all())
    records.reverse()  # chronological for the timeline view
    return IncidentDetail(incident=incident, surrounding_records=records)
