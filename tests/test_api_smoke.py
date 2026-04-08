"""FastAPI smoke tests; skipped when the configured database is unreachable."""
import pytest
from sqlalchemy import create_engine, text

from pipeline.db import DATABASE_URL, _connect_args


def _database_reachable() -> bool:
    try:
        if str(DATABASE_URL).startswith("sqlite"):
            eng = create_engine(
                DATABASE_URL,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
        else:
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


_skip = not _database_reachable()
_reason = "Database unreachable (check DATABASE_URL or local SQLite at data/callit_local.db)"

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
