import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.db import database
from app.main import app


def test_readyz_with_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.getenv("FLEETLINK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FLEETLINK_TEST_DATABASE_URL to run PostgreSQL integration")

    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.password
    healthy = create_engine(parsed, connect_args={"connect_timeout": 3})
    rejected = create_engine(
        parsed.set(password=f"{parsed.password}_invalid"),
        connect_args={"connect_timeout": 3},
    )
    try:
        with TestClient(app) as client:
            monkeypatch.setattr(database, "engine", healthy)
            ready = client.get("/readyz")
            assert ready.status_code == 200
            assert ready.json() == {"status": "ready"}
            monkeypatch.setattr(database, "engine", rejected)
            response = client.get("/readyz")
            assert response.status_code == 503
            assert response.json() == {"detail": "Database unavailable"}
            assert client.get("/healthz").status_code == 200
    finally:
        healthy.dispose()
        rejected.dispose()
