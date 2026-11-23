import asyncio
import json
import random
import time
from collections import deque
from datetime import UTC, datetime
from uuid import UUID

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidMessage

from app.models.protocol import (
    MAX_MESSAGE_BYTES,
    Command,
    CommandAck,
    CommandResult,
    HeartbeatAck,
    Hello,
    MessageType,
    ProtocolModel,
    Telemetry,
    TelemetryAck,
    Welcome,
)
from app.services.link_quality import OFFLINE_SECONDS
from simulator.run import Robot, RobotClient, Scenario


class ResilientRobot:
    def __init__(self, url: str, token: str, scenario: Scenario, index: int):
        self.url = url
        self.token = token
        self.scenario = scenario
        self.robot_id = f"sim-{index + 1:04d}"
        self.robot = Robot.seeded(scenario, index)
        self.rng = random.Random(f"retry/{scenario.seed}/{index}")
        self.buffer: deque[tuple[Telemetry, datetime]] = deque()
        self.session_id: UUID | None = None
        self.last_ack = 0
        self.last_server_seq = 0
        self.last_response = time.monotonic()
        self.connected = False
        self.generated = 0
        self.dropped = 0
        self.sent = 0
        self.replayed = 0
        self.reconnects = 0
        self.max_buffer = 0
        self.results: deque[CommandResult] = deque()
        self.ended = asyncio.Event()

    async def generate(self) -> None:
        start = time.monotonic()
        ticks = int(self.scenario.duration_seconds * self.scenario.telemetry_hz)
        for tick in range(ticks):
            await asyncio.sleep(
                max(0, start + tick / self.scenario.telemetry_hz - time.monotonic())
            )
            if time.monotonic() - self.last_response >= OFFLINE_SECONDS:
                self.robot.mode = "STOPPED"
                self.robot.command = None
            telemetry, result = self.robot.advance(1 / self.scenario.telemetry_hz)
            self.generated += 1
            telemetry.sample_seq = self.generated
            if len(self.buffer) >= self.scenario.buffer_samples:
                self.buffer.popleft()
                self.dropped += 1
            self.buffer.append((telemetry, datetime.now(UTC)))
            self.max_buffer = max(self.max_buffer, len(self.buffer))
            if result:
                self.results.append(result)
        await asyncio.sleep(
            max(0, start + self.scenario.duration_seconds - time.monotonic())
        )
        self.ended.set()

    async def receive(self, peer: RobotClient) -> None:
        while True:
            async with asyncio.timeout(OFFLINE_SECONDS):
                message = await peer.receive()
            self.last_response = time.monotonic()
            self.last_server_seq = message.seq
            if message.msg_type == MessageType.HEARTBEAT:
                self.heartbeat_acks.append(message.seq)
            elif message.msg_type == MessageType.TELEMETRY_ACK:
                ack = TelemetryAck.model_validate(message.payload)
                if ack.sample_seq > self.generated:
                    raise RuntimeError("Gateway acknowledged an unknown sample")
                self.last_ack = max(self.last_ack, ack.sample_seq)
                while (
                    self.buffer and (self.buffer[0][0].sample_seq or 0) <= self.last_ack
                ):
                    self.buffer.popleft()
            elif message.msg_type == MessageType.COMMAND:
                command = Command.model_validate(message.payload)
                self.command_acks.append(command.command_id)
                self.results.extend(self.robot.apply(command))
            elif message.msg_type != MessageType.HEARTBEAT_ACK:
                raise RuntimeError(f"Unexpected gateway message {message.msg_type}")

    async def transmit(self, peer: RobotClient) -> None:
        heartbeat_at = 0.0
        telemetry_at = 0.0
        cursor = self.last_ack
        replay_until = self.generated
        while not self.ended.is_set():
            now = time.monotonic()
            if now >= heartbeat_at:
                await peer.send(MessageType.HEARTBEAT, ProtocolModel())
                heartbeat_at = now + 1
            while self.heartbeat_acks:
                await peer.send(
                    MessageType.HEARTBEAT_ACK,
                    HeartbeatAck(ack_seq=self.heartbeat_acks.popleft()),
                )
            while self.command_acks:
                await peer.send(
                    MessageType.COMMAND_ACK,
                    CommandAck(command_id=self.command_acks.popleft()),
                )
            while self.results:
                await peer.send(MessageType.COMMAND_RESULT, self.results.popleft())
            if now >= telemetry_at:
                sample = next(
                    (
                        item
                        for item in self.buffer
                        if (item[0].sample_seq or 0) > cursor
                    ),
                    None,
                )
                if sample:
                    telemetry, captured = sample
                    replayed = (telemetry.sample_seq or 0) <= replay_until
                    await peer.send(
                        MessageType.TELEMETRY,
                        telemetry.model_copy(update={"replayed": replayed}),
                        sent_at=captured,
                    )
                    cursor = telemetry.sample_seq or cursor
                    self.sent += 1
                    self.replayed += int(replayed)
                    telemetry_at = now + 1 / self.scenario.replay_hz
            await asyncio.sleep(0.01)

    async def connection(self) -> None:
        async with connect(
            self.url, max_size=MAX_MESSAGE_BYTES, open_timeout=3, close_timeout=0.5
        ) as socket:
            peer = RobotClient(socket, self.robot_id)
            await peer.send(
                MessageType.HELLO,
                Hello(
                    token=self.token,
                    capabilities=["simulated-motion", "resilience-v1"],
                    resume_session_id=self.session_id,
                    last_ack_seq=self.last_ack,
                    last_server_seq=self.last_server_seq,
                ),
            )
            async with asyncio.timeout(3):
                message = await peer.receive()
            if message.msg_type != MessageType.WELCOME:
                raise RuntimeError("Expected WELCOME")
            welcome = Welcome.model_validate(message.payload)
            if (
                welcome.session_id != message.session_id
                or welcome.last_ack_seq > self.generated
            ):
                raise RuntimeError("Invalid WELCOME")
            if self.session_id is not None:
                self.reconnects += 1
            self.session_id = peer.session_id = welcome.session_id
            self.last_ack = welcome.last_ack_seq
            while self.buffer and (self.buffer[0][0].sample_seq or 0) <= self.last_ack:
                self.buffer.popleft()
            self.last_response = time.monotonic()
            self.connected = True
            self.heartbeat_acks: deque[int] = deque()
            self.command_acks: deque[UUID] = deque()
            tasks = [
                asyncio.create_task(self.receive(peer)),
                asyncio.create_task(self.transmit(peer)),
                asyncio.create_task(self.ended.wait()),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                self.connected = False
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def network(self) -> None:
        attempt = 0
        while not self.ended.is_set():
            started = time.monotonic()
            try:
                await self.connection()
            except RuntimeError as exc:
                if "ROBOT_ALREADY_CONNECTED" in str(exc):
                    pass
                elif "SESSION_EXPIRED" in str(exc):
                    self.session_id = None
                    self.last_ack = self.last_server_seq = 0
                else:
                    raise
            except (OSError, TimeoutError, ConnectionClosed, InvalidMessage):
                pass
            if time.monotonic() - started > 5:
                attempt = 0
            delay = self.rng.uniform(0, min(2, 0.2 * 2 ** min(attempt, 5)))
            attempt += 1
            try:
                await asyncio.wait_for(self.ended.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def run(self) -> str:
        generation = asyncio.create_task(self.generate())
        network = asyncio.create_task(self.network())
        try:
            done, _ = await asyncio.wait(
                [generation, network], return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
            if generation in done:
                await network
        finally:
            generation.cancel()
            network.cancel()
            await asyncio.gather(generation, network, return_exceptions=True)
        return json.dumps(
            {
                "robot_id": self.robot_id,
                "generated": self.generated,
                "sent": self.sent,
                "replayed": self.replayed,
                "dropped": self.dropped,
                "unacknowledged": len(self.buffer),
                "max_buffer": self.max_buffer,
                "reconnects": self.reconnects,
            }
        )
