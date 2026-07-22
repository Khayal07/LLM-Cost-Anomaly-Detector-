"""Auto-logging wrappers for OpenAI / Anthropic clients.

These patch the completion method on a client instance so every call is logged
to the detector service after it returns. Logging is best-effort: a logging
failure never affects the underlying LLM call.

    from openai import OpenAI
    from sdk import CostMonitorClient, wrap_openai

    monitor = CostMonitorClient("http://localhost:8000")
    client = wrap_openai(OpenAI(), monitor, endpoint="/summarize", caller="svc-a")
    client.chat.completions.create(model="gpt-4o-mini", messages=[...])  # auto-logged
"""
from __future__ import annotations

import time
from typing import Any

from sdk.client import CostMonitorClient


def _safe_log(monitor: CostMonitorClient, **kwargs: Any) -> None:
    try:
        monitor.log_call(**kwargs)
    except Exception:  # noqa: BLE001 - never break the caller's LLM request
        pass


def wrap_openai(
    client: Any,
    monitor: CostMonitorClient,
    *,
    endpoint: str = "openai",
    caller: str = "unknown",
) -> Any:
    """Patch ``client.chat.completions.create`` to auto-log usage."""
    original = client.chat.completions.create

    def logged_create(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        response = original(*args, **kwargs)
        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = getattr(response, "usage", None)
        _safe_log(
            monitor,
            provider="openai",
            model=getattr(response, "model", kwargs.get("model", "unknown")),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            endpoint=endpoint,
            caller=caller,
            latency_ms=latency_ms,
            prompt=kwargs.get("messages"),
        )
        return response

    client.chat.completions.create = logged_create
    return client


def wrap_anthropic(
    client: Any,
    monitor: CostMonitorClient,
    *,
    endpoint: str = "anthropic",
    caller: str = "unknown",
) -> Any:
    """Patch ``client.messages.create`` to auto-log usage."""
    original = client.messages.create

    def logged_create(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        response = original(*args, **kwargs)
        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = getattr(response, "usage", None)
        _safe_log(
            monitor,
            provider="anthropic",
            model=getattr(response, "model", kwargs.get("model", "unknown")),
            tokens_in=getattr(usage, "input_tokens", 0) or 0,
            tokens_out=getattr(usage, "output_tokens", 0) or 0,
            endpoint=endpoint,
            caller=caller,
            latency_ms=latency_ms,
            prompt=kwargs.get("messages"),
        )
        return response

    client.messages.create = logged_create
    return client
