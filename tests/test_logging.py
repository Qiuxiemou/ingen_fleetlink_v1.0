import json
import logging

from fastapi.testclient import TestClient

from app.core.logging import JSONFormatter
from app.main import app


def test_request_id_header() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers


def test_unique_request_ids() -> None:
    with TestClient(app) as client:
        first = client.get("/healthz")
        second = client.get("/healthz")

    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_json_formatter() -> None:
    record = logging.LogRecord(
        name="fleetlink",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Robot connected",
        args=(),
        exc_info=None,
    )
    record.connection_id = "conn-001"
    record.robot_id = "rover-001"

    result = json.loads(JSONFormatter().format(record))

    assert result["level"] == "INFO"
    assert result["message"] == "Robot connected"
    assert result["connection_id"] == "conn-001"
    assert result["robot_id"] == "rover-001"
