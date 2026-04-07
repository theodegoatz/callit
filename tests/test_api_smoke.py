"""FastAPI smoke tests; skipped when DATABASE_URL is unset or DB is unreachable."""
import os

import pytest
from sqlalchemy import create_engine, text

from pipeline.db import DATABASE_URL, _connect_args


def _database_reachable() -> bool:
    try:
        eng = create_engine(
            DATABASE_URL,
            connect_args=_connect_args(DATABASE_URL),
            pool_pre_ping=True,
        )
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


_skip = (not os.getenv("DATABASE_URL")) or (not _database_reachable())
_reason = (
    "DATABASE_URL not set — skip DB-backed API tests"
    if not os.getenv("DATABASE_URL")
    else "DATABASE_URL set but database unreachable — skip DB-backed API tests"
)

pytestmark = pytest.mark.skipif(_skip, reason=_reason)


def test_health_ok():
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"


def test_dashboard_returns_200():
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "CallIt" in r.text or "callit" in r.text.lower()
