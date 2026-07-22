"""Ingestion endpoints: record every LLM call and run detection on it."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.hashing import request_hash as hash_prompt
from app.models import CallRecord
from app.pricing import compute_cost
from app.schemas import IncidentSummary, LogRequest, LogResponse

router = APIRouter(tags=["ingestion"])


def build_record(payload: LogRequest) -> CallRecord:
    """Create a CallRecord from a log payload, filling cost/hash/totals."""
    cost = (
        payload.cost_usd
        if payload.cost_usd is not None
        else compute_cost(payload.model, payload.tokens_in, payload.tokens_out)
    )
    req_hash = payload.request_hash
    if req_hash is None and payload.prompt is not None:
        req_hash = hash_prompt(payload.prompt)

    ts = payload.ts or datetime.now(timezone.utc)
    return CallRecord(
        ts=ts,
        provider=payload.provider,
        model=payload.model,
        endpoint=payload.endpoint,
        caller=payload.caller,
        tokens_in=payload.tokens_in,
        tokens_out=payload.tokens_out,
        total_tokens=payload.tokens_in + payload.tokens_out,
        cost_usd=cost,
        latency_ms=payload.latency_ms,
        request_hash=req_hash,
        status=payload.status,
        meta=payload.meta,
    )


def ingest_one(session: Session, payload: LogRequest) -> tuple[CallRecord, list]:
    """Persist a record and run detection. Returns (record, incidents).

    Detection is wired in via ``app.detection.engine``; imported lazily so the
    ingestion layer has no hard dependency on the detector implementation.
    """
    record = build_record(payload)
    session.add(record)
    session.flush()  # assign record.id before detection queries

    from app.detection.engine import run_detection

    incidents = run_detection(session, record)
    session.commit()
    session.refresh(record)
    return record, incidents


@router.post("/log", response_model=LogResponse)
def log_call(payload: LogRequest, session: Session = Depends(get_session)) -> LogResponse:
    record, incidents = ingest_one(session, payload)
    return LogResponse(
        record_id=record.id,
        cost_usd=float(record.cost_usd),
        total_tokens=record.total_tokens,
        incidents=[
            IncidentSummary(
                id=i.id,
                type=i.type,
                severity=i.severity,
                scope_type=i.scope_type,
                scope_value=i.scope_value,
                message=i.message,
            )
            for i in incidents
        ],
    )


@router.post("/log/batch", response_model=list[LogResponse])
def log_batch(
    payloads: list[LogRequest], session: Session = Depends(get_session)
) -> list[LogResponse]:
    responses: list[LogResponse] = []
    for payload in payloads:
        record, incidents = ingest_one(session, payload)
        responses.append(
            LogResponse(
                record_id=record.id,
                cost_usd=float(record.cost_usd),
                total_tokens=record.total_tokens,
                incidents=[
                    IncidentSummary(
                        id=i.id,
                        type=i.type,
                        severity=i.severity,
                        scope_type=i.scope_type,
                        scope_value=i.scope_value,
                        message=i.message,
                    )
                    for i in incidents
                ],
            )
        )
    return responses
