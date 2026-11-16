from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.robots import registry

TOKEN = "test-only"


def frame(kind: str = "HELLO", **override: object) -> dict:
    return {
        "protocol_version": 1,
        "msg_type": kind,
        "robot_id": "sim-0001",
        "session_id": None,
        "seq": 1,
        "sent_at": datetime.now(UTC).isoformat(),
        "payload": (
            {"token": TOKEN, "capabilities": ["test"]} if kind == "HELLO" else {}
        ),
        **override,
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "robot_dev_token", TOKEN)
    monkeypatch.setattr(registry, "robots", {})
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"protocol_version": 2}, "UNSUPPORTED_VERSION"),
        ({"msg_type": "made-up"}, "UNKNOWN_MESSAGE_TYPE"),
        ({"msg_type": "HEARTBEAT"}, "EXPECTED_HELLO"),
        ({"sent_at": "2026-11-09T12:00:00"}, "INVALID_ENVELOPE"),
        ({"sent_at": "2026-11-09T12:00:00-05:00"}, "INVALID_ENVELOPE"),
        ({"payload": {}}, "AUTH_FAILED"),
        ({"payload": {"token": "wrong"}}, "AUTH_FAILED"),
        ({"payload": {"token": TOKEN}}, "INVALID_PAYLOAD"),
    ],
)
def test_invalid_handshake(client: TestClient, overrides: dict, code: str) -> None:
    with client.websocket_connect("/v1/link") as ws:
        ws.send_json(frame(**overrides))
        error = ws.receive_json()
        assert error["msg_type"] == "ERROR"
        assert error["payload"]["code"] == code
        assert ws.receive()["code"] == 1008
    assert client.get("/v1/robots").json() == []


@pytest.mark.parametrize(
    ("raw", "code", "close"),
    [
        ("{", "MALFORMED_JSON", 1008),
        ("[]", "INVALID_ENVELOPE", 1008),
        ("é" * 8193, "MESSAGE_TOO_LARGE", 1009),
    ],
)
def test_invalid_wire_message(
    client: TestClient, raw: str, code: str, close: int
) -> None:
    with client.websocket_connect("/v1/link") as ws:
        ws.send_text(raw)
        assert ws.receive_json()["payload"]["code"] == code
        assert ws.receive()["code"] == close


def test_robot_session_and_api(client: TestClient) -> None:
    with client.websocket_connect("/v1/link") as ws:
        ws.send_json(frame())
        welcome = ws.receive_json()
        assert welcome["msg_type"] == "WELCOME"
        assert welcome["seq"] == 1
        assert welcome["payload"]["negotiated_version"] == 1
        assert welcome["session_id"] == welcome["payload"]["session_id"]
        identity = {"session_id": welcome["session_id"]}
        path = "/v1/robots/sim-0001"
        assert client.get(path).json()["link_state"] == "connected"
        assert client.get(f"{path}/telemetry/latest").status_code == 404

        with client.websocket_connect("/v1/link") as other:
            other.send_json(frame())
            assert other.receive_json()["payload"]["code"] == "ROBOT_ALREADY_CONNECTED"

        ws.send_json(frame("HEARTBEAT", seq=2, session_id=str(uuid4())))
        assert ws.receive_json()["payload"]["code"] == "SESSION_MISMATCH"
        ws.send_json(frame("HEARTBEAT", seq=1, **identity))
        duplicate = ws.receive_json()
        assert duplicate["payload"]["code"] == "DUPLICATE_SEQ"
        assert duplicate["payload"]["expected_seq"] == 2
        ws.send_json(frame("HEARTBEAT", seq=3, **identity))
        assert ws.receive_json()["payload"]["code"] == "SEQUENCE_GAP"
        ws.send_json(frame("TELEMETRY", seq=2, payload={}, **identity))
        assert ws.receive_json()["payload"]["code"] == "INVALID_PAYLOAD"
        payload = {
            "pose": {"x": 1, "y": 2, "theta": 0.5},
            "velocity": 1.5,
            "battery": 98,
            "mode": "PATROL",
            "mission_step": 1,
        }
        ws.send_json(frame("TELEMETRY", seq=2, payload=payload, **identity))
        ws.send_json(frame("HEARTBEAT", seq=3, **identity))
        ack = ws.receive_json()
        assert ack["msg_type"] == "HEARTBEAT_ACK"
        assert ack["seq"] == 6
        assert ack["payload"] == {"ack_seq": 3}
        assert client.get(f"{path}/telemetry/latest").json()["telemetry"] == payload
        assert client.get("/v1/robots").json()[0]["session_id"] == welcome["session_id"]

        stub = client.post(f"{path}/commands", json={"command": "STOP"})
        assert stub.status_code == 501
        assert stub.json()["error"]["code"] == "DELIVERY_NOT_IMPLEMENTED"
        invalid = client.post(f"{path}/commands", json={"command": "MOVE_TO"})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get(path).json()["link_state"] == "disconnected"
    with client.websocket_connect("/v1/link") as ws:
        ws.send_json(frame())
        assert ws.receive_json()["session_id"] != welcome["session_id"]
        assert client.get(f"{path}/telemetry/latest").status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("POST", "/v1/robots/no-such-robot/commands", 404, "ROBOT_NOT_FOUND"),
        ("GET", "/v1/robots/invalid.id", 422, "VALIDATION_ERROR"),
        ("GET", "/v1/unknown", 404, "HTTP_404"),
        ("PUT", "/v1/robots", 405, "HTTP_405"),
    ],
)
def test_error_envelope(
    client: TestClient, method: str, path: str, status: int, code: str
) -> None:
    kwargs = {"json": {"command": "STOP"}} if method == "POST" else {}
    response = client.request(method, path, **kwargs)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert set(response.json()) == {"error", "request_id"}
