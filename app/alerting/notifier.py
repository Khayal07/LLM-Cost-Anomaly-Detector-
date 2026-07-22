"""Incident notification hooks.

If ``SLACK_WEBHOOK_URL`` is set, incidents are POSTed there; otherwise the
NullNotifier is used and incidents remain pollable via ``GET /incidents``.
Delivery is best-effort and never blocks or fails ingestion.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.models import Incident

logger = logging.getLogger(__name__)


class BaseNotifier:
    def send(self, incident: Incident) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class NullNotifier(BaseNotifier):
    def send(self, incident: Incident) -> bool:
        return False


class SlackNotifier(BaseNotifier):
    def __init__(self, webhook_url: str, timeout: float = 3.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, incident: Incident) -> bool:
        emoji = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(incident.severity, "⚪")
        text = (
            f"{emoji} *LLM cost anomaly: {incident.type}* "
            f"({incident.scope_type}=`{incident.scope_value}`)\n{incident.message}"
        )
        try:
            resp = httpx.post(self.webhook_url, json={"text": text}, timeout=self.timeout)
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001 - never let alerting break ingestion
            logger.warning("Slack notification failed: %s", exc)
            return False


def get_notifier() -> BaseNotifier:
    url = get_settings().slack_webhook_url
    return SlackNotifier(url) if url else NullNotifier()


def dispatch(incident: Incident) -> bool:
    """Send an incident and record whether delivery succeeded."""
    notified = get_notifier().send(incident)
    incident.notified = notified
    return notified
