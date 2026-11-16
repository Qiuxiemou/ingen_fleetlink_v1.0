# Robot link v1

Connect to `ws://127.0.0.1:8000/v1/link` for local development. Each WebSocket text message contains one JSON object, up to 16,384 UTF-8 bytes. Run Uvicorn with `--ws-max-size 32768` so the application can send `MESSAGE_TOO_LARGE` for messages above its limit and the transport can still cap larger inputs.

## Envelope

| Field | Type and rules |
| --- | --- |
| `protocol_version` | Integer 1. Unsupported integer versions receive an ERROR in v1. |
| `msg_type` | Case-sensitive string from the payload table. |
| `robot_id` | Case-sensitive ID with 1–64 ASCII letters, digits, underscores, or hyphens. May be null in a pre-handshake ERROR. |
| `session_id` | Null for HELLO and pre-handshake ERROR. UUID from WELCOME for subsequent traffic. |
| `seq` | Integer from 1 through 2⁵³−1. Each direction starts at 1 on a new connection. |
| `sent_at` | ISO-8601 UTC date and time with `Z` or explicit zero offset. |
| `payload` | JSON object with the fields below. Extra fields are rejected. |

The first robot frame must be HELLO within five seconds. Supply the local development token and a capabilities list. The gateway selects v1, returns WELCOME, and assigns a fresh session UUID. One simultaneous connection per robot ID is allowed. Reconnect with a fresh HELLO and sequence 1.

The gateway expects the next contiguous robot sequence. A lower value produces `DUPLICATE_SEQ`; a higher value produces `SEQUENCE_GAP`. Both include `expected_seq`. An invalid frame does not advance the robot sequence, so the peer can correct and resend it. A valid processed frame advances the sequence once. Gateway frames, including ERROR, share the gateway's separate sequence.

For a rough skew estimate, record robot UTC before sending HELLO and on receipt of WELCOME. Subtract the midpoint of those readings from `server_time` and treat half the round-trip duration as a rough uncertainty estimate. V1 accepts any correctly formatted UTC value and orders by sequence. Use `received_at` for gateway-observed sample age. V1 does not enforce clock skew or command expiry.

## Payloads

| Message | Direction | Payload |
| --- | --- | --- |
| HELLO | Robot → gateway | `token` (1–512 characters), `capabilities` (up to 32 strings) |
| WELCOME | Gateway → robot | `session_id` (UUID, matching the envelope), `negotiated_version` (1), `server_time` (UTC timestamp) |
| HEARTBEAT | Robot → gateway | Empty object |
| HEARTBEAT_ACK | Gateway → robot | `ack_seq` (integer sequence of HEARTBEAT) |
| TELEMETRY | Robot → gateway | `pose` (`x`, `y`, `theta`), `velocity`, `battery`, `mode`, `mission_step` |
| COMMAND | Gateway/test peer → robot | `command_id` (UUID), `command` (`MOVE_TO`, `STOP`, `DOCK`), `target` (`{x,y}`, required for `MOVE_TO`) |
| COMMAND_ACK | Robot → gateway/test peer | `command_id` (UUID) |
| COMMAND_RESULT | Robot → gateway/test peer | `command_id` (UUID), `status` (`completed`, `cancelled`, `rejected`) |
| ERROR | Gateway → robot | `code`, `message`, optional `expected_seq` |

The site frame is a synthetic Cartesian plane. Coordinates are meters from the scenario origin with +x to the right and +y up. Heading is counterclockwise from +x, in radians from −π to π. Velocity is a nonnegative scalar in m/s. Battery is 0–100 percent. Mode is `PATROL`, `MOVING`, `STOPPED`, `DOCKING`, or `DOCKED`. Mission step is a zero-based waypoint index.

| Error code | Meaning |
| --- | --- |
| `HANDSHAKE_TIMEOUT` | Missing HELLO after five seconds |
| `EXPECTED_HELLO` | Wrong first message or handshake identity |
| `AUTH_FAILED` | Missing, invalid, or disabled development token |
| `ROBOT_ALREADY_CONNECTED` | Robot ID has an active connection |
| `UNSUPPORTED_VERSION` | Unsupported version |
| `MALFORMED_JSON` | JSON could not be parsed |
| `TEXT_REQUIRED` | Received a binary message |
| `MESSAGE_TOO_LARGE` | UTF-8 limit exceeded |
| `UNKNOWN_MESSAGE_TYPE` | Unrecognized message type |
| `UNEXPECTED_MESSAGE_TYPE` | Known type disallowed from an active robot |
| `INVALID_ENVELOPE` | Missing or invalid envelope field |
| `INVALID_PAYLOAD` | Payload failed validation |
| `SESSION_MISMATCH` | Robot or session ID differs from the handshake |
| `DUPLICATE_SEQ` | Sequence lower than expected |
| `SEQUENCE_GAP` | Sequence higher than expected |

Initial errors close the socket with code 1008. Oversize errors close it with 1009. Other post-handshake errors allow a corrected frame.

## REST

| Endpoint | Success or defined error |
| --- | --- |
| GET `/v1/robots` | 200, array of robot views sorted by ID |
| GET `/v1/robots/{robot_id}` | 200, robot view; 404 for unknown ID |
| GET `/v1/robots/{robot_id}/telemetry/latest` | 200, sample and timestamps; 404 for unknown ID or missing sample |
| POST `/v1/robots/{robot_id}/commands` | 501 `DELIVERY_NOT_IMPLEMENTED` for a valid command to a known robot; 404 for unknown ID |

A robot view includes `robot_id`, `session_id`, `link_state`, `last_seen` and `capabilities`. Link state reflects transport closure. Latest telemetry includes `robot_id`, `session_id`, `sent_at`, `received_at`, and the telemetry payload under `telemetry`. A new session replaces the previous cached sample. The API returns 422 for invalid command bodies or path parameters. Versioned HTTP errors include `{"error":{"code":"...","message":"..."},"request_id":"..."}` and an identical `X-Request-ID` header.

## Worked exchange

With a plain WebSocket client, send this HELLO after substituting your local token.

```json
{"protocol_version":1,"msg_type":"HELLO","robot_id":"demo-01","session_id":null,"seq":1,"sent_at":"2026-11-09T15:00:00Z","payload":{"token":"<local token>","capabilities":["simulated-motion"]}}
```

The response has this shape. Copy its actual session ID.

```json
{"protocol_version":1,"msg_type":"WELCOME","robot_id":"demo-01","session_id":"c725994b-b112-4fd6-8c72-09617e5cf0ed","seq":1,"sent_at":"2026-11-09T15:00:00Z","payload":{"session_id":"c725994b-b112-4fd6-8c72-09617e5cf0ed","negotiated_version":1,"server_time":"2026-11-09T15:00:00Z"}}
```

Send telemetry with sequence 2 and the negotiated session ID. Check `GET /v1/robots/demo-01/telemetry/latest`.

```json
{"protocol_version":1,"msg_type":"TELEMETRY","robot_id":"demo-01","session_id":"c725994b-b112-4fd6-8c72-09617e5cf0ed","seq":2,"sent_at":"2026-11-09T15:00:01Z","payload":{"pose":{"x":1,"y":2,"theta":0},"velocity":1.5,"battery":98,"mode":"PATROL","mission_step":1}}
```

Send `{"command":"STOP"}` to `POST /v1/robots/demo-01/commands` while the socket is connected. Expect the documented 501 error. A protocol test peer may demonstrate simulator-side command execution by sending the following after WELCOME, using the simulator's robot ID, negotiated session ID, and the next gateway sequence.

```json
{"protocol_version":1,"msg_type":"COMMAND","robot_id":"demo-01","session_id":"c725994b-b112-4fd6-8c72-09617e5cf0ed","seq":2,"sent_at":"2026-11-09T15:00:02Z","payload":{"command_id":"d442c086-bf73-400d-91dc-2d31563e1b0f","command":"STOP"}}
```

The simulator sends COMMAND_ACK with that command ID, followed by COMMAND_RESULT with the same ID and `"status":"completed"`. Its outgoing sequence counts interleaved heartbeats and telemetry as well.
