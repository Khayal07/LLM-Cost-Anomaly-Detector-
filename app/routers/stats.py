"""Aggregation endpoints powering the dashboard.

Time-bucketing is done in Python so the queries stay portable across Postgres
and SQLite; grouping aggregations use portable SQL.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CallRecord, Incident
from app.schemas import CallRecordOut, GroupCost, StatsSummary, TimeBucketPoint

router = APIRouter(tags=["stats"])

_GRANULARITY = {"minute": 60, "hour": 3600, "day": 86400}


def _default_since(since: datetime | None, hours: int = 24) -> datetime:
    return since or (datetime.now(timezone.utc) - timedelta(hours=hours))


@router.get("/records", response_model=list[CallRecordOut])
def list_records(
    endpoint: str | None = None,
    caller: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    since: datetime | None = None,
    limit: int = Query(200, le=2000),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[CallRecord]:
    stmt = select(CallRecord).order_by(CallRecord.ts.desc()).limit(limit).offset(offset)
    if endpoint:
        stmt = stmt.where(CallRecord.endpoint == endpoint)
    if caller:
        stmt = stmt.where(CallRecord.caller == caller)
    if model:
        stmt = stmt.where(CallRecord.model == model)
    if provider:
        stmt = stmt.where(CallRecord.provider == provider)
    if since:
        stmt = stmt.where(CallRecord.ts >= since)
    return list(session.execute(stmt).scalars().all())


@router.get("/stats/summary", response_model=StatsSummary)
def summary(
    since: datetime | None = None, session: Session = Depends(get_session)
) -> StatsSummary:
    since = _default_since(since)
    row = session.execute(
        select(
            func.coalesce(func.sum(CallRecord.cost_usd), 0),
            func.count(CallRecord.id),
            func.coalesce(func.sum(CallRecord.total_tokens), 0),
        ).where(CallRecord.ts >= since)
    ).one()
    open_incidents = session.execute(
        select(func.count(Incident.id)).where(Incident.status == "open")
    ).scalar_one()
    return StatsSummary(
        total_cost_usd=float(row[0]),
        total_calls=int(row[1]),
        total_tokens=int(row[2]),
        open_incidents=int(open_incidents),
    )


@router.get("/stats/cost-over-time", response_model=list[TimeBucketPoint])
def cost_over_time(
    granularity: str = Query("hour", pattern="^(minute|hour|day)$"),
    since: datetime | None = None,
    session: Session = Depends(get_session),
) -> list[TimeBucketPoint]:
    since = _default_since(since, hours=24 if granularity != "day" else 24 * 30)
    step = _GRANULARITY[granularity]

    rows = session.execute(
        select(CallRecord.ts, CallRecord.cost_usd, CallRecord.total_tokens)
        .where(CallRecord.ts >= since)
        .order_by(CallRecord.ts)
    ).all()

    buckets: dict[int, dict[str, float]] = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tokens": 0})
    for ts, cost, tokens in rows:
        epoch = ts.replace(tzinfo=ts.tzinfo or timezone.utc).timestamp()
        key = int(epoch // step) * step
        b = buckets[key]
        b["cost"] += float(cost)
        b["calls"] += 1
        b["tokens"] += int(tokens)

    return [
        TimeBucketPoint(
            bucket=datetime.fromtimestamp(key, tz=timezone.utc),
            cost_usd=round(b["cost"], 6),
            calls=int(b["calls"]),
            tokens=int(b["tokens"]),
        )
        for key, b in sorted(buckets.items())
    ]


def _grouped(session: Session, column, since: datetime) -> list[GroupCost]:
    rows = session.execute(
        select(
            column,
            func.coalesce(func.sum(CallRecord.cost_usd), 0),
            func.count(CallRecord.id),
            func.coalesce(func.sum(CallRecord.total_tokens), 0),
        )
        .where(CallRecord.ts >= since)
        .group_by(column)
        .order_by(func.sum(CallRecord.cost_usd).desc())
    ).all()
    return [
        GroupCost(key=str(key), cost_usd=float(cost), calls=int(calls), tokens=int(tokens))
        for key, cost, calls, tokens in rows
    ]


@router.get("/stats/cost-by-model", response_model=list[GroupCost])
def cost_by_model(
    since: datetime | None = None, session: Session = Depends(get_session)
) -> list[GroupCost]:
    return _grouped(session, CallRecord.model, _default_since(since))


@router.get("/stats/cost-by-endpoint", response_model=list[GroupCost])
def cost_by_endpoint(
    since: datetime | None = None, session: Session = Depends(get_session)
) -> list[GroupCost]:
    return _grouped(session, CallRecord.endpoint, _default_since(since))
