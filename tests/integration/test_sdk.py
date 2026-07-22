"""Tests for the client SDK and the auto-logging wrappers."""
from __future__ import annotations

import pytest

from sdk import CostMonitorClient, request_hash, wrap_anthropic, wrap_openai


@pytest.fixture()
def monitor(client):
    """A CostMonitorClient wired to the app in-process.

    The ``client`` fixture is a Starlette TestClient (an httpx.Client), so the
    SDK talks to the real app synchronously with no network.
    """
    return CostMonitorClient(client=client)


def test_request_hash_normalizes():
    assert request_hash("Hello   WORLD") == request_hash("hello world")
    assert request_hash("a") != request_hash("b")


def test_client_log_call_posts_record(monitor):
    result = monitor.log_call(
        provider="openai",
        model="gpt-4o-mini",
        tokens_in=1000,
        tokens_out=500,
        endpoint="/chat",
        caller="svc-a",
    )
    assert result["record_id"] > 0
    assert abs(result["cost_usd"] - 0.00045) < 1e-9
    assert result["total_tokens"] == 1500


# --- wrapper fakes --------------------------------------------------------

class _FakeMonitor:
    def __init__(self):
        self.calls: list[dict] = []

    def log_call(self, **kwargs):
        self.calls.append(kwargs)


class _OpenAIUsage:
    prompt_tokens = 123
    completion_tokens = 45


class _OpenAIResp:
    usage = _OpenAIUsage()
    model = "gpt-4o-mini"


class _FakeOpenAICompletions:
    def create(self, *args, **kwargs):
        return _OpenAIResp()


class _FakeOpenAI:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _FakeOpenAICompletions()})()


def test_wrap_openai_logs_usage():
    monitor = _FakeMonitor()
    client = wrap_openai(_FakeOpenAI(), monitor, endpoint="/summarize", caller="svc-a")
    resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])

    assert resp.model == "gpt-4o-mini"
    assert len(monitor.calls) == 1
    logged = monitor.calls[0]
    assert logged["provider"] == "openai"
    assert logged["tokens_in"] == 123
    assert logged["tokens_out"] == 45
    assert logged["endpoint"] == "/summarize"
    assert logged["caller"] == "svc-a"


class _AnthropicUsage:
    input_tokens = 300
    output_tokens = 80


class _AnthropicResp:
    usage = _AnthropicUsage()
    model = "claude-3-5-sonnet"


class _FakeAnthropicMessages:
    def create(self, *args, **kwargs):
        return _AnthropicResp()


class _FakeAnthropic:
    def __init__(self):
        self.messages = _FakeAnthropicMessages()


def test_wrap_anthropic_logs_usage():
    monitor = _FakeMonitor()
    client = wrap_anthropic(_FakeAnthropic(), monitor, caller="svc-b")
    client.messages.create(model="claude-3-5-sonnet", messages=[{"role": "user", "content": "hi"}])

    assert len(monitor.calls) == 1
    logged = monitor.calls[0]
    assert logged["provider"] == "anthropic"
    assert logged["tokens_in"] == 300
    assert logged["tokens_out"] == 80


def test_wrapper_logging_failure_does_not_break_call():
    class _BoomMonitor:
        def log_call(self, **kwargs):
            raise RuntimeError("network down")

    client = wrap_openai(_FakeOpenAI(), _BoomMonitor())
    # Should still return the underlying response despite logging blowing up.
    resp = client.chat.completions.create(model="gpt-4o-mini", messages=[])
    assert resp.model == "gpt-4o-mini"
