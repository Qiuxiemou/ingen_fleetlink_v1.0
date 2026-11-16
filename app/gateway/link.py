import hmac
import json
import logging
from asyncio import timeout
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.models.protocol import (
    MAX_MESSAGE_BYTES,
    VERSION,
    CommandAck,
    CommandResult,
    Envelope,
    HeartbeatAck,
    Hello,
    MessageType,
    ProtocolError,
    ProtocolModel,
    Telemetry,
    Welcome,
)
from app.services.robots import RobotSession, registry

router = APIRouter()
logger = logging.getLogger("fleetlink.gateway")

ROBOT_PAYLOADS: dict[MessageType, type[BaseModel]] = {
    MessageType.HEARTBEAT: ProtocolModel,
    MessageType.TELEMETRY: Telemetry,
    MessageType.COMMAND_ACK: CommandAck,
    MessageType.COMMAND_RESULT: CommandResult,
}


class LinkError(Exception):
    def __init__(self, code: str, message: str, expected_seq: int | None = None):
        super().__init__(message)
        self.code = code
        self.expected_seq = expected_seq


class Link:
    def __init__(self, socket: WebSocket):
        self.socket = socket
        self.session: RobotSession | None = None
        self.robot_id: str | None = None
        self.send_seq = 0
        self.expected_seq = 1

    async def receive(self) -> Envelope:
        event = await self.socket.receive()
        if event["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(event["code"])
        raw = event.get("text")
        if raw is None:
            raise LinkError("TEXT_REQUIRED", "Send a JSON text message")
        if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise LinkError("MESSAGE_TOO_LARGE", "Maximum size is 16384 UTF-8 bytes")
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise LinkError("MALFORMED_JSON", "Invalid JSON") from exc
        if not isinstance(data, dict):
            raise LinkError("INVALID_ENVELOPE", "Expected a JSON object")
        version = data.get("protocol_version")
        if type(version) is int and version != VERSION:
            raise LinkError("UNSUPPORTED_VERSION", "Supported protocol version is 1")
        kind = data.get("msg_type")
        if isinstance(kind, str) and kind not in MessageType._value2member_map_:
            raise LinkError("UNKNOWN_MESSAGE_TYPE", "Unrecognized message type")
        try:
            message = Envelope.model_validate(data)
        except ValidationError as exc:
            raise LinkError("INVALID_ENVELOPE", "Invalid envelope fields") from exc
        return message

    async def send(self, kind: MessageType, payload: BaseModel) -> None:
        self.send_seq += 1
        await self.socket.send_text(
            Envelope(
                protocol_version=VERSION,
                msg_type=kind,
                robot_id=self.robot_id,
                session_id=self.session.session_id if self.session else None,
                seq=self.send_seq,
                sent_at=datetime.now(UTC),
                payload=payload.model_dump(mode="json", exclude_none=True),
            ).model_dump_json()
        )

    async def send_error(self, error: LinkError) -> None:
        await self.send(
            MessageType.ERROR,
            ProtocolError(
                code=error.code, message=str(error), expected_seq=error.expected_seq
            ),
        )

    def check_sequence(self, message: Envelope) -> None:
        if message.seq < self.expected_seq:
            raise LinkError("DUPLICATE_SEQ", "Sequence already used", self.expected_seq)
        if message.seq > self.expected_seq:
            raise LinkError("SEQUENCE_GAP", "Sequence skipped", self.expected_seq)

    async def handshake(self) -> RobotSession:
        message = await self.receive()
        self.robot_id = message.robot_id
        if (
            message.msg_type != MessageType.HELLO
            or message.robot_id is None
            or message.session_id is not None
        ):
            raise LinkError(
                "EXPECTED_HELLO", "Send HELLO with robot_id and null session_id"
            )
        self.check_sequence(message)
        token = message.payload.get("token")
        if not (
            settings.robot_dev_token
            and isinstance(token, str)
            and hmac.compare_digest(
                token.encode(errors="surrogatepass"), settings.robot_dev_token.encode()
            )
        ):
            raise LinkError("AUTH_FAILED", "Invalid or missing development token")
        hello = Hello.model_validate(message.payload)
        session = registry.connect(message.robot_id, hello.capabilities)
        if session is None:
            raise LinkError("ROBOT_ALREADY_CONNECTED", "Robot has an active session")
        self.session = session
        self.expected_seq += 1
        await self.send(
            MessageType.WELCOME,
            Welcome(session_id=session.session_id, server_time=datetime.now(UTC)),
        )
        return session

    async def process(self, session: RobotSession) -> None:
        message = await self.receive()
        if (
            message.robot_id != session.robot_id
            or message.session_id != session.session_id
        ):
            raise LinkError(
                "SESSION_MISMATCH", "Use the negotiated robot and session IDs"
            )
        self.check_sequence(message)
        model = ROBOT_PAYLOADS.get(message.msg_type)
        if model is None:
            raise LinkError(
                "UNEXPECTED_MESSAGE_TYPE", "Message is not accepted from robots"
            )
        payload = model.model_validate(message.payload)
        self.expected_seq += 1
        session.last_seen = datetime.now(UTC)
        if message.msg_type == MessageType.HEARTBEAT:
            await self.send(
                MessageType.HEARTBEAT_ACK, HeartbeatAck(ack_seq=message.seq)
            )
        if isinstance(payload, Telemetry):
            session.telemetry = payload
            session.telemetry_received_at = session.last_seen
            session.telemetry_sent_at = message.sent_at


@router.websocket("/v1/link", name="robot_link_v1")
async def robot_link(socket: WebSocket) -> None:
    await socket.accept()
    link = Link(socket)
    context = {"connection_id": str(uuid4()), "robot_id": None}
    try:
        try:
            async with timeout(5):
                session = await link.handshake()
        except (LinkError, TimeoutError, ValidationError) as exc:
            if isinstance(exc, TimeoutError):
                exc = LinkError("HANDSHAKE_TIMEOUT", "Send HELLO within five seconds")
            if isinstance(exc, ValidationError):
                exc = LinkError("INVALID_PAYLOAD", "Invalid HELLO payload")
            await link.send_error(exc)
            await socket.close(1009 if exc.code == "MESSAGE_TOO_LARGE" else 1008)
            return
        context["robot_id"] = session.robot_id
        logger.info("Robot connected", extra=context)
        while True:
            try:
                await link.process(session)
            except ValidationError:
                await link.send_error(
                    LinkError("INVALID_PAYLOAD", "Invalid message payload")
                )
            except LinkError as exc:
                await link.send_error(exc)
                if exc.code == "MESSAGE_TOO_LARGE":
                    await socket.close(1009)
                    return
    except WebSocketDisconnect:
        pass
    finally:
        if link.session is not None:
            link.session.connected = False
            logger.info("Robot disconnected", extra=context)
