import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from websockets.asyncio.server import ServerConnection, serve

from app.models.protocol import Command, Envelope, MessageType, Point, Welcome
from simulator.run import Scenario, run_robot


def test_simulator_acknowledges_and_executes_commands() -> None:
    async def exercise() -> None:
        session_id = uuid4()
        results: list[str] = []

        async def gateway(socket: ServerConnection) -> None:
            hello = Envelope.model_validate_json(await socket.recv())
            assert hello.msg_type == MessageType.HELLO
            assert hello.payload["token"] == "test-only"
            tx_seq = 0

            async def send(kind: MessageType, payload: dict[str, object]) -> None:
                nonlocal tx_seq
                tx_seq += 1
                await socket.send(
                    Envelope(
                        protocol_version=1,
                        msg_type=kind,
                        robot_id=hello.robot_id,
                        session_id=session_id,
                        seq=tx_seq,
                        sent_at=datetime.now(UTC),
                        payload=payload,
                    ).model_dump_json()
                )

            welcome = Welcome(session_id=session_id, server_time=datetime.now(UTC))
            await send(MessageType.WELCOME, welcome.model_dump(mode="json"))
            commands = (
                Command(command_id=uuid4(), command="MOVE_TO", target=Point(x=1, y=1)),
                Command(command_id=uuid4(), command="STOP"),
                Command(command_id=uuid4(), command="DOCK"),
            )
            for command in commands:
                await send(
                    MessageType.COMMAND,
                    command.model_dump(mode="json", exclude_none=True),
                )
                acknowledged = False
                while True:
                    frame = Envelope.model_validate_json(await socket.recv())
                    if frame.msg_type == MessageType.HEARTBEAT:
                        await send(MessageType.HEARTBEAT_ACK, {"ack_seq": frame.seq})
                    if frame.msg_type == MessageType.COMMAND_ACK:
                        assert frame.payload["command_id"] == str(command.command_id)
                        acknowledged = True
                    if frame.msg_type == MessageType.COMMAND_RESULT:
                        assert acknowledged
                        assert frame.payload == {
                            "command_id": str(command.command_id),
                            "status": "completed",
                        }
                        results.append(command.command)
                        break
            async for _ in socket:
                pass

        scenario = Scenario(
            seed=17,
            robot_count=1,
            duration_seconds=1,
            telemetry_hz=20,
            speed_mps=50,
            waypoints=[Point(x=0, y=0), Point(x=1, y=0)],
        )
        async with serve(gateway, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with asyncio.timeout(5):
                summary = await run_robot(
                    f"ws://127.0.0.1:{port}", "test-only", scenario, 0
                )
        assert results == ["MOVE_TO", "STOP", "DOCK"]
        assert "samples=20 heartbeats=1" in summary

    asyncio.run(exercise())
