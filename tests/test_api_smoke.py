"""FastAPI smoke tests; skipped when DATABASE_URL is unset."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skip DB-backed API tests",
)


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
