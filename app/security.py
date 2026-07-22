"""Optional API-key authentication.

When ``API_KEY`` is configured, every data endpoint requires a matching
``X-API-Key`` header. When it's empty (the default), auth is disabled so local
development and tests work with no ceremony. ``/healthz`` is always open.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = get_settings().api_key
    if not expected:
        return  # auth disabled
    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )
