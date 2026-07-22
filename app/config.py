"""Application configuration, loaded from environment / `.env`.

All detection thresholds live here so they can be tuned via env vars without
touching code (see `.env.example`).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- database ---
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/costmonitor"

    # --- dashboard -> api ---
    api_url: str = "http://localhost:8000"

    # --- secrets ---
    openai_api_key: str | None = None
    slack_webhook_url: str | None = None

    # --- detection thresholds ---
    z_score_threshold: float = 3.5
    iqr_multiplier: float = 1.5
    min_samples: int = 8
    loop_count_threshold: int = 10
    loop_window_seconds: int = 60
    cost_spike_bucket_seconds: int = 60
    baseline_window_seconds: int = 3600
    token_growth_ratio: float = 4.0
    # Materiality floor: don't raise cost incidents for trivial dollar amounts,
    # even if they're statistical outliers (a $0.009 call isn't worth paging on).
    min_incident_cost_usd: float = 0.05
    cooldown_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
