"""Tests for the optional API-key authentication guard."""
from __future__ import annotations

from app.config import get_settings

PAYLOAD = {"provider": "openai", "model": "gpt-4o-mini", "tokens_in": 10, "tokens_out": 5}


def test_auth_disabled_by_default(client):
    # No API_KEY configured -> endpoints are open.
    assert client.post("/log", json=PAYLOAD).status_code == 200


def test_auth_enforced_when_key_set(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "api_key", "s3cret")

    # healthz stays open
    assert client.get("/healthz").status_code == 200

    # missing / wrong key -> 401
    assert client.post("/log", json=PAYLOAD).status_code == 401
    assert client.get("/incidents").status_code == 401
    assert client.post("/log", json=PAYLOAD, headers={"X-API-Key": "wrong"}).status_code == 401

    # correct key -> allowed
    ok = client.post("/log", json=PAYLOAD, headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200
    assert client.get("/incidents", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_sdk_sends_api_key(client, monkeypatch):
    from sdk import CostMonitorClient

    monkeypatch.setattr(get_settings(), "api_key", "s3cret")
    # The SDK forwards the key so it authenticates cleanly.
    monitor = CostMonitorClient(api_key="s3cret", client=client)
    result = monitor.log_call(provider="openai", model="gpt-4o-mini", tokens_in=10, tokens_out=5)
    assert result["record_id"] > 0
