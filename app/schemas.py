"""Pydantic request/response schemas for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LogRequest(BaseModel):
    """A single LLM call to be ingested via ``POST /log``."""

    provider: str = Field(examples=["openai"])
    model: str = Field(examples=["gpt-4o-mini"])
    endpoint: str = "unknown"
    caller: str = "unknown"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None  # computed from pricing when omitted
    latency_ms: int = 0
    status: str = "success"
    ts: datetime | None = None  # defaults to now when omitted
    # Either supply a precomputed hash, or a prompt to hash server-side.
    request_hash: str | None = None
    prompt: Any | None = None
    meta: dict[str, Any] | None = None


class IncidentSummary(BaseModel):
    id: int
    type: str
    severity: str
    scope_type: str
    scope_value: str
    message: str


class LogResponse(BaseModel):
    record_id: int
    cost_usd: float
    total_tokens: int
    incidents: list[IncidentSummary] = []


class CallRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    provider: str
    model: str
    endpoint: str
    caller: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    cost_usd: float
    latency_ms: int
    request_hash: str | None
    status: str


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    detected_at: datetime
    type: str
    severity: str
    scope_type: str
    scope_value: str
    trigger_record_id: int | None
    score: float | None
    baseline: dict[str, Any] | None
    observed: dict[str, Any] | None
    window_start: datetime | None
    window_end: datetime | None
    message: str
    status: str
    notified: bool


class IncidentDetail(BaseModel):
    incident: IncidentOut
    surrounding_records: list[CallRecordOut]


class TimeBucketPoint(BaseModel):
    bucket: datetime
    cost_usd: float
    calls: int
    tokens: int


class GroupCost(BaseModel):
    key: str
    cost_usd: float
    calls: int
    tokens: int


class StatsSummary(BaseModel):
    total_cost_usd: float
    total_calls: int
    total_tokens: int
    open_incidents: int
