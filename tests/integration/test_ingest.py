"""Integration tests for the ingestion endpoint."""
from __future__ import annotations


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_log_stores_record_and_computes_cost(client):
    payload = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "endpoint": "/chat",
        "caller": "user-1",
        "tokens_in": 1000,
        "tokens_out": 500,
        "latency_ms": 320,
    }
    resp = client.post("/log", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    assert body["record_id"] > 0
    assert body["total_tokens"] == 1500
    # gpt-4o-mini: (1000*0.15 + 500*0.60) / 1e6 = 0.00045
    assert abs(body["cost_usd"] - 0.00045) < 1e-9
    assert body["incidents"] == []


def test_log_respects_explicit_cost(client):
    payload = {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet",
        "tokens_in": 100,
        "tokens_out": 100,
        "cost_usd": 1.23,
    }
    resp = client.post("/log", json=payload)
    assert resp.status_code == 200
    assert resp.json()["cost_usd"] == 1.23


def test_log_hashes_prompt_for_loop_signature(client):
    p1 = {"provider": "openai", "model": "gpt-4o", "prompt": "Hello  WORLD"}
    p2 = {"provider": "openai", "model": "gpt-4o", "prompt": "hello world"}
    r1 = client.post("/log", json=p1).json()
    r2 = client.post("/log", json=p2).json()
    # Both stored successfully; identical normalised prompts share a hash
    # (verified at the unit level in the detector tests).
    assert r1["record_id"] != r2["record_id"]


def test_log_batch(client):
    payloads = [
        {"provider": "openai", "model": "gpt-4o-mini", "tokens_in": 10, "tokens_out": 5}
        for _ in range(3)
    ]
    resp = client.post("/log/batch", json=payloads)
    assert resp.status_code == 200
    assert len(resp.json()) == 3
