import argparse
import asyncio
import hashlib
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field
from websockets.asyncio.client import ClientConnection, connect

from app.core.config import settings
from app.models.protocol import (
    MAX_MESSAGE_BYTES,
    VERSION,
    Command,
    CommandAck,
    CommandResult,
    Envelope,
    Hello,
    MessageType,
    Point,
    Pose,
    ProtocolModel,
    Telemetry,
    Welcome,
)

Mode = Literal["PATROL", "MOVING", "STOPPED", "DOCKING", "DOCKED"]


class Scenario(ProtocolModel):
    seed: int
    robot_count: int = Field(ge=1, le=1000)
    duration_seconds: float = Field(gt=0)
    telemetry_hz: int = Field(ge=1, le=100)
    speed_mps: float = Field(gt=0)
    waypoints: list[Point] = Field(min_length=2)


@dataclass
class Robot:
    scenario: Scenario
    step: int
    x: float
    y: float
    battery: float
    theta: float = 0
    mode: Mode = "PATROL"
    command: Command | None = None

    @classmethod
    def seeded(cls, scenario: Scenario, index: int) -> "Robot":
        rng = random.Random(f"{scenario.seed}/{index}")
        start = rng.randrange(len(scenario.waypoints))
        point = scenario.waypoints[start]
        return cls(
            scenario,
            (start + 1) % len(scenario.waypoints),
            point.x,
            point.y,
            rng.uniform(90, 100),
        )

    def apply(self, command: Command) -> list[CommandResult]:
        results = []
        if self.command is not None:
            results.append(
                CommandResult(command_id=self.command.command_id, status="cancelled")
            )
        self.command = None
        if command.command == "STOP":
            self.mode = "STOPPED"
            results.append(
                CommandResult(command_id=command.command_id, status="completed")
            )
        else:
            self.command = command
            self.mode = "DOCKING" if command.command == "DOCK" else "MOVING"
        return results

    def advance(self, dt: float) -> tuple[Telemetry, CommandResult | None]:
        target = None
        result = None
        distance = 0.0
        if self.mode == "PATROL":
            target = self.scenario.waypoints[self.step]
        elif self.command:
            target = (
                self.scenario.waypoints[0]
                if self.command.command == "DOCK"
                else self.command.target
            )
        if target is not None and self.battery > 0 and dt > 0:
            dx, dy = target.x - self.x, target.y - self.y
            remaining = math.hypot(dx, dy)
            distance = min(remaining, self.scenario.speed_mps * dt)
            if distance:
                self.theta = math.atan2(dy, dx)
                self.x += dx * (distance / remaining)
                self.y += dy * (distance / remaining)
            if distance == remaining:
                self.x, self.y = target.x, target.y
                if self.command:
                    self.mode = "DOCKED" if self.mode == "DOCKING" else "STOPPED"
                    result = CommandResult(
                        command_id=self.command.command_id, status="completed"
                    )
                    self.command = None
                else:
                    self.step = (self.step + 1) % len(self.scenario.waypoints)
            self.battery = max(0, self.battery - 0.02 * distance)
        return (
            Telemetry(
                pose=Pose(x=self.x, y=self.y, theta=self.theta),
                velocity=distance / dt if dt else 0,
                battery=self.battery,
                mode=self.mode,
                mission_step=self.step,
            ),
            result,
        )


class RobotClient:
    def __init__(self, socket: ClientConnection, robot_id: str):
        self.socket = socket
        self.robot_id = robot_id
        self.session_id: UUID | None = None
        self.seq = 0
        self.peer_seq = 0

    async def send(self, kind: MessageType, payload: BaseModel) -> None:
        self.seq += 1
        message = Envelope(
            protocol_version=VERSION,
            msg_type=kind,
            robot_id=self.robot_id,
            session_id=self.session_id,
            seq=self.seq,
            sent_at=datetime.now(UTC),
            payload=payload.model_dump(mode="json", exclude_none=True),
        )
        await self.socket.send(message.model_dump_json())

    async def receive(self) -> Envelope:
        message = Envelope.model_validate_json(await self.socket.recv(decode=False))
        if message.msg_type == MessageType.ERROR:
            raise RuntimeError(f"{self.robot_id}: {message.payload.get('code')}")
        if (
            message.protocol_version != VERSION
            or message.robot_id != self.robot_id
            or message.seq != self.peer_seq + 1
            or (self.session_id is not None and message.session_id != self.session_id)
        ):
            raise RuntimeError(f"{self.robot_id}: invalid gateway envelope")
        self.peer_seq = message.seq
        return message


async def run_robot(url: str, token: str, scenario: Scenario, index: int) -> str:
    robot = Robot.seeded(scenario, index)
    robot_id = f"sim-{index + 1:04d}"
    digest = hashlib.sha256()
    async with connect(url, max_size=MAX_MESSAGE_BYTES) as socket:
        peer = RobotClient(socket, robot_id)
        await peer.send(
            MessageType.HELLO, Hello(token=token, capabilities=["simulated-motion"])
        )
        async with asyncio.timeout(5):
            message = await peer.receive()
        if message.msg_type != MessageType.WELCOME:
            raise RuntimeError(f"{robot_id}: expected WELCOME")
        welcome = Welcome.model_validate(message.payload)
        if message.session_id != welcome.session_id:
            raise RuntimeError(f"{robot_id}: invalid WELCOME session")
        peer.session_id = welcome.session_id

        loop = asyncio.get_running_loop()
        start = loop.time()
        tick = 0
        heartbeat = 0
        while True:
            telemetry_at = tick / scenario.telemetry_hz
            next_at = min(telemetry_at, heartbeat, scenario.duration_seconds)
            try:
                async with asyncio.timeout_at(start + next_at):
                    message = await peer.receive()
            except TimeoutError:
                if next_at >= scenario.duration_seconds:
                    break
                if heartbeat == next_at:
                    await peer.send(MessageType.HEARTBEAT, ProtocolModel())
                    heartbeat += 1
                if telemetry_at == next_at:
                    telemetry, result = robot.advance(
                        1 / scenario.telemetry_hz if tick else 0
                    )
                    digest.update(telemetry.model_dump_json().encode())
                    await peer.send(MessageType.TELEMETRY, telemetry)
                    if result:
                        await peer.send(MessageType.COMMAND_RESULT, result)
                    tick += 1
                continue
            if message.msg_type == MessageType.COMMAND:
                command = Command.model_validate(message.payload)
                await peer.send(
                    MessageType.COMMAND_ACK, CommandAck(command_id=command.command_id)
                )
                for result in robot.apply(command):
                    await peer.send(MessageType.COMMAND_RESULT, result)
            elif message.msg_type != MessageType.HEARTBEAT_ACK:
                raise RuntimeError(
                    f"{robot_id}: unexpected {message.msg_type} from gateway"
                )
    return f"{robot_id} samples={tick} heartbeats={heartbeat} telemetry_sha256={digest.hexdigest()}"


async def run_fleet(url: str, token: str, scenario: Scenario) -> None:
    async with asyncio.TaskGroup() as fleet:
        tasks = [
            fleet.create_task(run_robot(url, token, scenario, index))
            for index in range(scenario.robot_count)
        ]
    for task in tasks:
        print(task.result())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a seeded FleetLink simulation")
    parser.add_argument("scenario", type=Path, help="YAML scenario file")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/v1/link")
    parser.add_argument("--seconds", type=float, help="Override the scenario duration")
    args = parser.parse_args()
    if not settings.robot_dev_token:
        parser.error("Set ROBOT_DEV_TOKEN in the environment or .env")
    data = yaml.safe_load(args.scenario.read_text(encoding="utf-8"))
    if args.seconds is not None:
        data["duration_seconds"] = args.seconds
    scenario = Scenario.model_validate(data)
    asyncio.run(run_fleet(args.url, settings.robot_dev_token, scenario))


if __name__ == "__main__":
    main()
