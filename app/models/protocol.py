from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

VERSION: Literal[1] = 1
MAX_MESSAGE_BYTES = 16_384
RobotID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Timestamp = AwareDatetime


class MessageType(StrEnum):
    HELLO = "HELLO"
    WELCOME = "WELCOME"
    HEARTBEAT = "HEARTBEAT"
    HEARTBEAT_ACK = "HEARTBEAT_ACK"
    TELEMETRY = "TELEMETRY"
    TELEMETRY_ACK = "TELEMETRY_ACK"
    COMMAND = "COMMAND"
    COMMAND_ACK = "COMMAND_ACK"
    COMMAND_RESULT = "COMMAND_RESULT"
    ERROR = "ERROR"


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Envelope(ProtocolModel):
    protocol_version: int = Field(strict=True, ge=1)
    msg_type: MessageType
    robot_id: RobotID | None
    session_id: UUID | None
    seq: int = Field(strict=True, ge=1, le=2**53 - 1)
    sent_at: Timestamp
    payload: dict[str, object]

    @field_validator("sent_at", mode="before")
    @classmethod
    def timestamp_format(cls, value: object) -> object:
        if isinstance(value, datetime) or (isinstance(value, str) and "T" in value):
            return value
        raise ValueError("Use an ISO-8601 date and time")

    @field_validator("sent_at")
    @classmethod
    def timestamp_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("Use a UTC timestamp")
        return value


class Hello(ProtocolModel):
    token: str = Field(min_length=1, max_length=512)
    capabilities: list[str] = Field(max_length=32)
    resume_session_id: UUID | None = None
    last_ack_seq: int = Field(default=0, ge=0)
    last_server_seq: int = Field(default=0, ge=0)


class Welcome(ProtocolModel):
    session_id: UUID
    negotiated_version: Literal[1] = VERSION
    server_time: Timestamp
    resumed: bool = False
    last_ack_seq: int = 0


class HeartbeatAck(ProtocolModel):
    ack_seq: int


class TelemetryAck(ProtocolModel):
    sample_seq: int = Field(ge=1)


class Pose(ProtocolModel):
    x: float
    y: float
    theta: float = Field(ge=-3.141592653589793, le=3.141592653589793)


class Telemetry(ProtocolModel):
    pose: Pose
    velocity: float = Field(ge=0)
    battery: float = Field(ge=0, le=100)
    mode: Literal["PATROL", "MOVING", "STOPPED", "DOCKING", "DOCKED"]
    mission_step: int = Field(ge=0)
    sample_seq: int | None = Field(default=None, ge=1)
    replayed: bool = False


class Point(ProtocolModel):
    x: float
    y: float


class CommandRequest(ProtocolModel):
    command: Literal["MOVE_TO", "STOP", "DOCK"]
    target: Point | None = None

    @model_validator(mode="after")
    def check_target(self) -> Self:
        if (self.command == "MOVE_TO") != (self.target is not None):
            raise ValueError("A target is required for MOVE_TO and forbidden otherwise")
        return self


class Command(CommandRequest):
    command_id: UUID


class CommandAck(ProtocolModel):
    command_id: UUID


class CommandResult(CommandAck):
    status: Literal["completed", "cancelled", "rejected"]


class ProtocolError(ProtocolModel):
    code: str
    message: str
    expected_seq: int | None = None
