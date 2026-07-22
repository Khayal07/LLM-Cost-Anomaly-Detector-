"""Shared test fixtures.

Tests run against a file-backed SQLite database (portable schema), configured
*before* the app is imported so the module-level engine binds to it.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway SQLite DB before any app import triggers engine
# creation. A file (not :memory:) is used so every connection shares state.
_TMP_DB = Path(tempfile.gettempdir()) / "costmonitor_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"


@pytest.fixture()
def db_session():
    """A clean database and session for a single test."""
    from app.db import Base, SessionLocal, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    """A TestClient with a freshly created schema."""
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
