from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.models.protocol import Telemetry


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


class RobotRegistry:
    def __init__(self) -> None:
        self.robots: dict[str, RobotSession] = {}

    def connect(self, robot_id: str, capabilities: list[str]) -> RobotSession | None:
        previous = self.robots.get(robot_id)
        if previous and previous.connected:
            return None
        session = RobotSession(robot_id, capabilities)
        self.robots[robot_id] = session
        return session


registry = RobotRegistry()
