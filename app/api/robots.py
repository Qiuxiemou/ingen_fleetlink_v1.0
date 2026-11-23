import time
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.protocol import CommandRequest, RobotID, Telemetry
from app.services.link_quality import LinkState
from app.services.robots import RobotSession, registry


class LinkMetrics(BaseModel):
    state: LinkState
    rtt_ewma_ms: float | None
    jitter_ms: float
    observed_gap_ratio: float
    heartbeat_age_seconds: float
    telemetry_staleness_seconds: float | None
    last_sample_seq: int
    replayed_samples: int
    duplicate_samples: int
    missing_samples: int
    resumptions: int
    command_rtt_ms: list[float]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class RobotView(BaseModel):
    robot_id: RobotID
    session_id: UUID
    link_state: Literal["connected", "disconnected"]
    last_seen: datetime
    capabilities: list[str]
    link: LinkMetrics


class LatestTelemetry(BaseModel):
    robot_id: RobotID
    session_id: UUID
    sent_at: datetime
    received_at: datetime
    telemetry: Telemetry


router = APIRouter(
    prefix="/v1/robots",
    tags=["robots"],
    responses={422: {"model": ErrorResponse, "description": "Invalid request"}},
)
NOT_FOUND = {"model": ErrorResponse, "description": "Unknown robot or missing sample"}


def robot_view(session: RobotSession) -> RobotView:
    return RobotView(
        robot_id=session.robot_id,
        session_id=session.session_id,
        link_state="connected" if session.connected else "disconnected",
        last_seen=session.last_seen,
        capabilities=session.capabilities,
        link=LinkMetrics(
            state=session.quality.update(session.connected),
            rtt_ewma_ms=session.quality.rtt_ms,
            jitter_ms=session.quality.jitter_ms,
            observed_gap_ratio=session.quality.observed_gap_ratio,
            heartbeat_age_seconds=max(
                0, time.monotonic() - session.quality.last_heartbeat
            ),
            telemetry_staleness_seconds=(
                max(
                    0,
                    (
                        datetime.now(session.telemetry_sent_at.tzinfo)
                        - session.telemetry_sent_at
                    ).total_seconds(),
                )
                if session.telemetry_sent_at
                else None
            ),
            last_sample_seq=session.last_sample_seq,
            replayed_samples=session.replayed_samples,
            duplicate_samples=session.duplicate_samples,
            missing_samples=session.missing_samples,
            resumptions=session.resumptions,
            command_rtt_ms=session.command_rtt_ms,
        ),
    )


def require_robot(robot_id: str) -> RobotSession:
    robot = registry.robots.get(robot_id)
    if robot is None:
        raise HTTPException(
            404, detail={"code": "ROBOT_NOT_FOUND", "message": "Unknown robot"}
        )
    return robot


@router.get("")
async def list_robots() -> list[RobotView]:
    """List robots seen since this process started, sorted by ID."""
    return [robot_view(registry.robots[key]) for key in sorted(registry.robots)]


@router.get("/{robot_id}", responses={404: NOT_FOUND})
async def get_robot(robot_id: RobotID) -> RobotView:
    """Return the current or most recent session and transport link state."""
    return robot_view(require_robot(robot_id))


@router.get(
    "/{robot_id}/telemetry/latest",
    responses={404: NOT_FOUND},
    response_model_exclude_unset=True,
)
async def get_latest_telemetry(robot_id: RobotID) -> LatestTelemetry:
    """Return the last accepted sample in the most recent session."""
    robot = require_robot(robot_id)
    if (
        robot.telemetry is None
        or robot.telemetry_received_at is None
        or robot.telemetry_sent_at is None
    ):
        raise HTTPException(
            404,
            detail={
                "code": "TELEMETRY_NOT_FOUND",
                "message": "No sample in this session",
            },
        )
    return LatestTelemetry(
        robot_id=robot_id,
        session_id=robot.session_id,
        sent_at=robot.telemetry_sent_at,
        received_at=robot.telemetry_received_at,
        telemetry=robot.telemetry,
    )


@router.post(
    "/{robot_id}/commands",
    status_code=501,
    response_model=ErrorResponse,
    responses={404: NOT_FOUND},
)
async def submit_command(robot_id: RobotID, command: CommandRequest) -> ErrorResponse:
    """Validate the command contract. Delivery and command IDs are reserved for a later release."""
    require_robot(robot_id)
    raise HTTPException(
        501,
        detail={
            "code": "DELIVERY_NOT_IMPLEMENTED",
            "message": "Command delivery is disabled",
        },
    )
