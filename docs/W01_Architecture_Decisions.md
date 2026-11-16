# Week 1 architecture decisions

## Synthetic sizing assumptions

These are planning estimates for the FleetLink simulator. Payload sizes are budgets for complete JSON messages. Rates exclude TLS, TCP, retransmissions, and handshakes. The 20-robot scenario sends a combined pose/status sample, so the separate 1 Hz status line below is a capacity allowance.

| Stream per robot | Steady rate | Budget per message | 20 robots |
| --- | ---: | ---: | ---: |
| Pose telemetry | 5/s | 360 B | 100 msg/s · 36 kB/s |
| Status telemetry | 1/s | 300 B | 20 msg/s · 6 kB/s |
| Heartbeat plus ACK | 2/s | 240 B | 40 msg/s · 9.6 kB/s |
| Command, ACK, and result | 0.3/s | 320 B | 6 msg/s · 1.92 kB/s |
| Total | 8.3/s | — | 166 msg/s · 53.52 kB/s |

A burst of 20 pose updates per second per robot produces 466 msg/s and 161.52 kB/s across 20 robots. A retry of a command adds traffic beyond this baseline.

## ADR 1 · Robot transport

Use WebSockets with JSON for the simulated fleet. At 20 connections and 166 steady msg/s, the gateway can serve the bidirectional link with one socket per robot and a small per-session state record. FastAPI supports the gateway directly and browser tooling can inspect JSON messages.

MQTT offers broker-side routing and delivery QoS, which is useful for fan-out at a larger fleet size. The baseline has one gateway consumer, so a broker adds an operational dependency for little benefit. gRPC bidirectional streaming adds schema tooling and binary encoding, with browser access typically going through an intermediary. All three options considered here use TCP, so loss can temporarily delay subsequent messages on a connection. Track application-level timing and validate the latency budget under impairment.

## ADR 2 · Storage

Use PostgreSQL for mission and assignment transactions and for bounded telemetry retention. At 6 telemetry rows/s per robot, 20 robots produce 120 rows/s, or 10.368 million rows per continuous day. Budgeting 320 B per row for a compact record plus one index yields 3.32 GB/day or 23.22 GB in seven days. At 8 active hours per day, that becomes 1.11 GB/day or 7.74 GB in seven days. These decimal GB estimates exclude WAL, replicas, backups, and bloat. One sustained hour at the 21 Hz burst rate would add 1.08 million rows over baseline, about 346 MB.

Model missions, robots, and assignments with foreign keys and an explicit constraint on the active assignment. Use row locking for claims and consider `SKIP LOCKED` when several workers compete for queued work. MySQL also supports relational constraints and row locking. PostgreSQL gives the design declarative time partitioning as an option for retention and straightforward measurement of query plans. MongoDB can model time-series data, but the assignment invariant spans several related records. Measure actual bytes per row and query latency before committing to a retention period or partition scheme.

## ADR 3 · Command delivery

Design for at-least-once delivery with robot-side deduplication by command ID and expiry checked before execution. In the baseline, 20 robots at 0.1 command/s each produce two commands per second before acknowledgements and retries. A lost acknowledgement can make a successful execution look like a failed delivery. At-most-once initiation leaves that ambiguity unresolved and prevents a safe retry.

Keep the ID and expiry unchanged on retry. A duplicate should report the known state without restarting motion. Stop retrying by expiry and surface an unknown outcome when a disconnect prevents confirmation. The simulator protocol establishes IDs and result shapes. Delivery, expiry, and deduplication are planned follow-up work.
