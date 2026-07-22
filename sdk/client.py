"""HTTP client for posting call records to the detector service.

Depends only on ``httpx`` (plus the shared ``app.hashing`` so request hashes
match the server exactly). Any application can call ``log_call`` after each LLM
request, or use the wrappers in ``sdk.wrappers`` to auto-log.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.hashing import request_hash

__all__ = ["CostMonitorClient", "log_call", "request_hash"]


class CostMonitorClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        timeout: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)
        self._owns_client = client is None

    def log_call(
        self,
        *,
        provider: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        endpoint: str = "unknown",
        caller: str = "unknown",
        cost_usd: float | None = None,
        latency_ms: int = 0,
        status: str = "success",
        prompt: Any | None = None,
        request_hash: str | None = None,  # noqa: A002 - matches API field
        meta: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        """Post one call record to ``/log`` and return the JSON response."""
        payload: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "endpoint": endpoint,
            "caller": caller,
            "latency_ms": latency_ms,
            "status": status,
        }
        if cost_usd is not None:
            payload["cost_usd"] = cost_usd
        if request_hash is not None:
            payload["request_hash"] = request_hash
        elif prompt is not None:
            payload["prompt"] = prompt
        if meta is not None:
            payload["meta"] = meta
        if ts is not None:
            payload["ts"] = ts.isoformat()

        url = "/log" if self._client.base_url else f"{self.base_url}/log"
        resp = self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CostMonitorClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def log_call(base_url: str = "http://localhost:8000", **kwargs: Any) -> dict[str, Any]:
    """One-shot convenience: open a client, log a single call, close it."""
    with CostMonitorClient(base_url) as client:
        return client.log_call(**kwargs)
