"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.db import init_db
from app.routers import incidents, ingest, stats
from app.security import require_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="LLM Cost Anomaly Detector",
    description="Ingests LLM API calls and flags cost anomalies in near real time.",
    version="0.1.0",
    lifespan=lifespan,
)

# All data endpoints sit behind the optional API-key guard; /healthz stays open.
_auth = [Depends(require_api_key)]
app.include_router(ingest.router, dependencies=_auth)
app.include_router(incidents.router, dependencies=_auth)
app.include_router(stats.router, dependencies=_auth)


@app.get("/healthz", tags=["meta"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
