# Week 3 resilience design

The gateway and simulator use a one-second heartbeat interval and monotonic timers. A link becomes DEGRADED after 1.5 seconds without a heartbeat and OFFLINE after 2.5 seconds. The receive loop wakes every 250 ms, giving a nominal worst-case detection time of 2.75 seconds against the three-second target. A socket close immediately marks the transport disconnected. The API preserves the existing connected/disconnected field and adds ONLINE/DEGRADED/OFFLINE under `link.state`.

RTT is measured by gateway heartbeat probes and matching acknowledgements. The EWMA uses alpha 0.2. Jitter uses alpha 0.125 on the absolute difference between successive RTT samples. Three consecutive samples with EWMA RTT above 500 ms or jitter above 150 ms degrade the link. Three consecutive healthy samples recover ONLINE. These thresholds provide hysteresis under isolated retransmissions. The API also exposes heartbeat age, source sample age, frame gap ratio, session resumptions, and telemetry replay counters. Source sample age assumes synchronized UTC, while heartbeat deadlines always use monotonic time.

## Session recovery

Clients opt into the extension by advertising `resilience-v1`. HELLO may include `resume_session_id`, `last_ack_seq`, and `last_server_seq`. WELCOME returns `resumed` and the server's last acknowledged telemetry sample sequence. A missing server session produces SESSION_EXPIRED and the simulator establishes a new session. An active duplicate connection is rejected and retried with backoff. Invalid authentication terminates only that robot's task.

The resume session ID is a UUID. Both HELLO cursors are nonnegative integers and default to zero. An acknowledgement cursor beyond server state produces INVALID_RESUME. WELCOME's resumed field is boolean and last_ack_seq is the server's nonnegative sample cursor. TELEMETRY optionally adds sample_seq, an integer of at least one, and replayed, a boolean defaulting to false. Each accepted or duplicate sample receives TELEMETRY_ACK with a payload containing sample_seq, the highest sample cursor accepted by this session. New WELCOME fields are sent only to clients advertising resilience-v1.

The wire envelope sequence retains its Week 2 meaning and resets per connection. It detects malformed or duplicate transport frames within that connection. A telemetry `sample_seq` persists across reconnects and is acknowledged by TELEMETRY_ACK. The last acknowledged sample is the resume cursor. The last gateway frame sequence is diagnostic context because heartbeat and acknowledgement frames are regenerated on reconnect. This prevents stale transport acknowledgements from becoming part of replay state.

Old clients can still send HELLO with just token and capabilities. They do not receive unsolicited gateway heartbeat probes. Their periodic robot heartbeats still renew liveness. They establish a fresh session when reconnecting without resume fields.

## Buffer and replay

Sampling continues during outages in a separate coroutine. The default buffer retains at most 300 unacknowledged samples, corresponding to about 60 seconds at 5 Hz. On overflow the oldest sample is dropped and a counter records the loss. Newest samples remain available. The sender processes the buffer in sequence order at up to 10 samples per second, including live samples, so it can drain a 5 Hz backlog without flooding the gateway. Heartbeats and command acknowledgements get priority in the single sender.

The server only advances its latest pose for a sample sequence greater than the last accepted sequence. Older and duplicate samples receive the current acknowledgement without overwriting the pose. Missing sample numbers are counted as an observation of telemetry gaps. TCP retransmission hides IP packet loss from envelope sequence numbers, so the frame gap ratio is an application observation and cannot estimate physical network packet loss.

## Robot fault isolation

Fleet execution uses gather with return_exceptions. Each robot independently owns its sampling, connection, retry schedule, buffer, and session. A fatal error ends that robot's tasks while other robots finish their scenarios. The CLI reports a failing fleet exit after collecting all results. Retriable network failures use full jitter on exponential backoff from 200 ms to a maximum of two seconds.

## Command expiry and clock policy for the next phase

Use an immutable command UUID, UTC issued_at, and expires_at on each future retry. The robot will estimate clock offset from the midpoint of HELLO send and WELCOME receipt, with half the handshake RTT as the initial uncertainty. Refresh estimates during heartbeats before enabling motion commands. Require uncertainty at or below 100 ms and absolute offset at or below two seconds for motion. Reject motion conservatively when estimated server time plus uncertainty reaches expires_at. Log the estimate and rejection reason. STOP should preempt movement independently of clock confidence.

The simulator's local deadman stops motion after 2.5 seconds without a gateway response, on the next kinematics tick. At the default 5 Hz this gives at most 200 ms from timeout to stop, against the 500 ms target. Reconnection leaves the robot stopped until commanded. Full delivery, retry deduplication, control leases, and enforcement of the proposed UTC expiry rule remain Week 4 work.

The measured command RTT uses an isolated lab mode (`LAB_PROBES=true`) which sends STOP commands and times their acknowledgements. This mode is disabled by default and leaves the public REST submission endpoint at its documented Week 2 status.
