# Week 01 — Engineering Log

Intern: Qiushi Chen  
Company: InGen Dynamics Inc.  
Project: Fleet Connectivity, Teleoperation Resilience & Mission Backend  
Week: November 2–7, 2026

## Work Completed

During the first week, I reviewed the engineering documentation for five InGen platforms: Aido Rover, Fari, Sentinel Prime AI, Aido Humanoid, and Senpai. I analyzed their connectivity environments, message patterns, command safety requirements, operator roles, and data retention considerations.

Based on these findings, I prepared three Architecture Decision Records (ADRs) covering robot communication transport, database selection, and command-delivery semantics. I also created a service design document describing component responsibilities, failure handling, initial APIs, and performance targets.

For the implementation, I established the FastAPI service skeleton with environment-based configuration using pydantic-settings, PostgreSQL connectivity through SQLAlchemy, and structured JSON logging with unique request IDs. I implemented `/healthz` and `/readyz`, including database availability checking.

The project passed eight automated pytest tests with 93% code coverage. Ruff, Black, and mypy checks passed locally, and the GitHub Actions CI workflow completed successfully.

## Key Architecture Decision: WebSocket Transport

The most challenging architectural decision was selecting the communication transport between robots and the backend. I considered WebSocket, MQTT, and gRPC bidirectional streaming.

MQTT provides publish-subscribe messaging and configurable delivery guarantees, making it attractive for IoT devices. However, it introduces broker infrastructure and additional operational complexity. gRPC offers strongly typed interfaces and efficient binary communication, but direct browser integration is less straightforward.

I selected WebSocket for the initial FleetLink implementation because Aido Rover requires frequent telemetry updates and bidirectional command communication. WebSocket integrates directly with FastAPI and can also support communication with the future React operator console.

An important limitation is that WebSocket runs over TCP. Packet loss can cause head-of-line blocking, delaying newer messages while missing data is retransmitted. WebSocket also does not automatically provide application-level command deduplication, expiration, or session recovery.

To address these risks, the design separates transport reliability from command safety. Future implementations will use heartbeat monitoring, sequence numbers, reconnection handling, and command expiration. At-least-once delivery with robot-side idempotent deduplication will prevent repeated execution of retried commands.

## Lessons Learned and Next Steps

This week reinforced the importance of making architecture decisions based on system requirements rather than familiarity with particular technologies. A communication protocol suitable for ordinary telemetry may not satisfy safety-critical motion-control requirements.

I also gained practical experience with FastAPI, uv, PostgreSQL, automated testing, code quality tools, and GitHub Actions.

In Week 2, I will implement the versioned WebSocket protocol, initial robot REST endpoints, and an asyncio-based robot simulator to validate these architectural decisions.