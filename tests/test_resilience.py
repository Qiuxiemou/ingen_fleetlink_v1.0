import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.protocol import Command, Point, Pose, Telemetry
from app.services.link_quality import LinkQuality
from app.services.robots import RobotSession, registry
from simulator.resilience import ResilientRobot
from simulator.run import Scenario, run_fleet
from tests.test_link_contract import frame


def sample(seq: int, x: float = 0) -> Telemetry:
    return Telemetry(
        pose=Pose(x=x, y=0, theta=0),
        velocity=0,
        battery=100,
        mode="STOPPED",
        mission_step=0,
        sample_seq=seq,
    )


def test_replay_cannot_replace_newer_pose() -> None:
    session = RobotSession("r", [])
    now = datetime.now(UTC)
    session.accept_telemetry(sample(3, 3), now)
    session.accept_telemetry(sample(1, 1), now - timedelta(seconds=1))
    session.accept_telemetry(sample(3, 9), now)
    assert session.telemetry is not None
    assert session.telemetry.pose.x == 3
    assert session.duplicate_samples == 2
    assert session.missing_samples == 2


def test_hysteresis_and_deadline() -> None:
    quality = LinkQuality(last_heartbeat=0)
    assert quality.update(True, 1.6) == "DEGRADED"
    for index in range(2):
        quality.heartbeat(1.7 + index * 0.1)
        quality.observe_rtt(10)
        assert quality.update(True, 1.7 + index * 0.1) == "DEGRADED"
    quality.heartbeat(2)
    quality.observe_rtt(10)
    assert quality.update(True, 2) == "ONLINE"
    assert quality.update(True, 4.5) == "OFFLINE"
    assert quality.rtt_ms == 10


def test_resume_preserves_session_and_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "robot_dev_token", "test-only")
    monkeypatch.setattr(registry, "robots", {})
    with TestClient(app) as client:
        with client.websocket_connect("/v1/link") as socket:
            socket.send_json(frame())
            session_id = socket.receive_json()["session_id"]
            socket.send_json(
                frame(
                    "TELEMETRY",
                    session_id=session_id,
                    seq=2,
                    payload=sample(1, 1).model_dump(mode="json"),
                )
            )
            assert socket.receive_json()["payload"] == {"sample_seq": 1}
        with client.websocket_connect("/v1/link") as socket:
            socket.send_json(
                frame(
                    payload={
                        "token": "test-only",
                        "capabilities": ["resilience-v1"],
                        "resume_session_id": session_id,
                        "last_ack_seq": 1,
                    }
                )
            )
            welcome = socket.receive_json()
            assert welcome["session_id"] == session_id
            assert welcome["payload"]["resumed"] is True
            assert welcome["payload"]["last_ack_seq"] == 1
            assert client.get("/v1/robots/sim-0001").json()["link"]["resumptions"] == 1


def test_silent_socket_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "robot_dev_token", "test-only")
    monkeypatch.setattr(registry, "robots", {})
    with TestClient(app) as client:
        with client.websocket_connect("/v1/link") as socket:
            socket.send_json(frame())
            socket.receive_json()
            started = time.monotonic()
            assert socket.receive()["code"] == 1013
            assert time.monotonic() - started < 3
        assert client.get("/v1/robots/sim-0001").json()["link"]["state"] == "OFFLINE"


def test_buffer_bound_and_robot_deadman() -> None:
    async def exercise() -> None:
        scenario = Scenario(
            seed=1,
            robot_count=1,
            duration_seconds=0.3,
            telemetry_hz=20,
            speed_mps=1,
            buffer_samples=2,
            waypoints=[Point(x=0, y=0), Point(x=5, y=0)],
        )
        robot = ResilientRobot("ws://unused", "test", scenario, 0)
        robot.robot.apply(
            Command(command_id=uuid4(), command="MOVE_TO", target=Point(x=50, y=0))
        )
        robot.last_response = time.monotonic() - 3
        await robot.generate()
        assert robot.robot.mode == "STOPPED"
        assert robot.robot.command is None
        assert len(robot.buffer) == 2
        assert robot.dropped == 4
        assert [entry[0].sample_seq for entry in robot.buffer] == [5, 6]

    asyncio.run(exercise())


def test_one_robot_failure_does_not_cancel_fleet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = []

    async def run(robot: ResilientRobot) -> str:
        if robot.robot_id == "sim-0001":
            raise RuntimeError("Injected authentication failure")
        await asyncio.sleep(0.05)
        completed.append(robot.robot_id)
        return "completed"

    monkeypatch.setattr(ResilientRobot, "run", run)
    scenario = Scenario(
        seed=1,
        robot_count=2,
        duration_seconds=1,
        telemetry_hz=5,
        speed_mps=1,
        waypoints=[Point(x=0, y=0), Point(x=1, y=0)],
    )
    with pytest.raises(RuntimeError, match="independently"):
        asyncio.run(run_fleet("ws://unused", "test", scenario))
    assert completed == ["sim-0002"]


def test_interrupted_http_handshake_is_retried() -> None:
    async def exercise() -> None:
        attempts = 0

        async def interrupt(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            nonlocal attempts
            attempts += 1
            writer.close()
            await writer.wait_closed()

        scenario = Scenario(
            seed=17,
            robot_count=1,
            duration_seconds=1.2,
            telemetry_hz=10,
            speed_mps=1,
            buffer_samples=3,
            waypoints=[Point(x=0, y=0), Point(x=1, y=0)],
        )
        async with await asyncio.start_server(interrupt, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            robot = ResilientRobot(f"ws://127.0.0.1:{port}", "test", scenario, 0)
            await robot.run()
        assert attempts >= 2
        assert robot.generated == 12
        assert robot.dropped == 9

    asyncio.run(exercise())
