"""Integration test: anomalous ingest -> incident -> query -> drill-down -> alert."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.alerting.notifier as notifier_mod

BASE = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)


def _loop_payload(i: int) -> dict:
    return {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "endpoint": "/agent/step",
        "caller": "runaway-agent",
        "tokens_in": 50,
        "tokens_out": 10,
        "prompt": "retry the same tool call",  # identical -> same hash
        "ts": (BASE + timedelta(seconds=i)).isoformat(),
    }


def test_loop_creates_incident_and_notifies(client, monkeypatch):
    sent: list = []

    class SpyNotifier(notifier_mod.BaseNotifier):
        def send(self, incident):
            sent.append(incident.type)
            return True

    monkeypatch.setattr(notifier_mod, "get_notifier", lambda: SpyNotifier())

    incident_seen = False
    for i in range(12):
        resp = client.post("/log", json=_loop_payload(i))
        assert resp.status_code == 200
        if resp.json()["incidents"]:
            incident_seen = True

    assert incident_seen, "a loop incident should have been raised during ingest"
    assert "loop" in sent, "the notifier should have been dispatched for the loop"

    # It is queryable via /incidents.
    incidents = client.get("/incidents", params={"type": "loop"}).json()
    assert len(incidents) >= 1
    incident = incidents[0]
    assert incident["scope_value"] == "runaway-agent"
    assert incident["notified"] is True

    # Drill-down returns the surrounding request pattern.
    detail = client.get(f"/incidents/{incident['id']}").json()
    assert detail["incident"]["id"] == incident["id"]
    assert len(detail["surrounding_records"]) >= 10
    assert all(r["caller"] == "runaway-agent" for r in detail["surrounding_records"])


def test_cooldown_dedups_repeated_anomalies(client):
    # A sustained loop should not create a new incident on every single call.
    for i in range(30):
        client.post("/log", json=_loop_payload(i))
    incidents = client.get("/incidents", params={"type": "loop"}).json()
    assert len(incidents) == 1, "cooldown should collapse the storm into one incident"
