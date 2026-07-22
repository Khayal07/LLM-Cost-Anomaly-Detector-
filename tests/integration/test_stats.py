"""Integration tests for the dashboard aggregation endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 4, 1, 8, 0, 0, tzinfo=timezone.utc)


def _seed(client, n=5):
    for i in range(n):
        client.post(
            "/log",
            json={
                "provider": "openai",
                "model": "gpt-4o-mini" if i % 2 == 0 else "gpt-4o",
                "endpoint": "/chat" if i % 2 == 0 else "/summarize",
                "caller": "svc-a",
                "tokens_in": 100,
                "tokens_out": 50,
                "cost_usd": 0.01,
                "ts": (BASE + timedelta(minutes=i)).isoformat(),
            },
        )


def test_summary(client):
    _seed(client, 5)
    body = client.get("/stats/summary", params={"since": (BASE - timedelta(hours=1)).isoformat()}).json()
    assert body["total_calls"] == 5
    assert abs(body["total_cost_usd"] - 0.05) < 1e-9
    assert body["total_tokens"] == 5 * 150
    assert body["open_incidents"] == 0


def test_cost_over_time_buckets(client):
    _seed(client, 5)
    points = client.get(
        "/stats/cost-over-time",
        params={"granularity": "hour", "since": (BASE - timedelta(hours=1)).isoformat()},
    ).json()
    assert len(points) == 1  # all 5 calls fall in one hour bucket
    assert abs(points[0]["cost_usd"] - 0.05) < 1e-9
    assert points[0]["calls"] == 5


def test_cost_by_model_and_endpoint(client):
    _seed(client, 5)
    since = (BASE - timedelta(hours=1)).isoformat()
    by_model = client.get("/stats/cost-by-model", params={"since": since}).json()
    keys = {row["key"] for row in by_model}
    assert keys == {"gpt-4o-mini", "gpt-4o"}

    by_endpoint = client.get("/stats/cost-by-endpoint", params={"since": since}).json()
    ep_keys = {row["key"] for row in by_endpoint}
    assert ep_keys == {"/chat", "/summarize"}


def test_records_query(client):
    _seed(client, 3)
    records = client.get("/records", params={"caller": "svc-a"}).json()
    assert len(records) == 3
    assert all(r["caller"] == "svc-a" for r in records)
