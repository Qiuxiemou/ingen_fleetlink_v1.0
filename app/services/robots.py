import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.models.protocol import Telemetry
from app.services.link_quality import LinkQuality


@dataclass
class RobotSession:
    robot_id: str
    capabilities: list[str]
    session_id: UUID = field(default_factory=uuid4)
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    connected: bool = True
    telemetry: Telemetry | None = None
    telemetry_received_at: datetime | None = None
    telemetry_sent_at: datetime | None = None
    quality: LinkQuality = field(default_factory=lambda: LinkQuality(time.monotonic()))
    telemetry_monotonic: float | None = None
    last_sample_seq: int = 0
    replayed_samples: int = 0
    duplicate_samples: int = 0
    missing_samples: int = 0
    resumptions: int = 0
    command_rtt_ms: list[float] = field(default_factory=list)
    connection_generation: int = 0

    def accept_telemetry(self, payload: Telemetry, sent_at: datetime) -> None:
        sample = payload.sample_seq
        if sample is not None:
            if sample <= self.last_sample_seq:
                self.duplicate_samples += 1
                return
            self.missing_samples += max(0, sample - self.last_sample_seq - 1)
            self.last_sample_seq = sample
        elif self.telemetry_sent_at is not None and sent_at < self.telemetry_sent_at:
            return
        self.telemetry = payload
        self.telemetry_received_at = datetime.now(UTC)
        self.telemetry_sent_at = sent_at
        self.telemetry_monotonic = time.monotonic()
        self.replayed_samples += int(payload.replayed)


class RobotRegistry:
    def __init__(self) -> None:
        self.robots: dict[str, RobotSession] = {}

    def connect(
        self,
        robot_id: str,
        capabilities: list[str],
        resume_session_id: UUID | None = None,
    ) -> RobotSession | None:
        previous = self.robots.get(robot_id)
        if previous and previous.connected:
            return None
        if previous and resume_session_id == previous.session_id:
            previous.connected = True
            previous.capabilities = capabilities
            previous.quality = LinkQuality(time.monotonic())
            previous.resumptions += 1
            previous.connection_generation += 1
            return previous
        session = RobotSession(robot_id, capabilities)
        self.robots[robot_id] = session
        return session


registry = RobotRegistry()
