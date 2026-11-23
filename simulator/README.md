# Robot simulator v0

Week 3 enables recovery by default. Scenarios may set `resilience: false` for the Week 2 connection behavior. Recovery scenarios additionally accept `buffer_samples` (default 300) and `replay_hz` (default 10). Set replay_hz above telemetry_hz to drain buffered samples while new sampling continues. Summary output includes generated, sent, replayed, dropped, pending, and reconnect counts. The [resilience design](../docs/W03_Resilience_Design.md) describes the deadman, resume cursor, and failure isolation.

Set `ROBOT_DEV_TOKEN` to the same local development token used by the gateway. Starting the gateway and running the default scenario for ten minutes requires two terminals.

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws-max-size 32768
uv run python -m simulator.run simulator/scenario.yaml
```

For a smoke test, add `--seconds 10`. Use `--url` to select another gateway. The YAML keys are `seed`, `robot_count`, `duration_seconds`, `telemetry_hz`, `speed_mps`, and `waypoints` (ordered `{x, y}` points in meters). The first waypoint is the dock. Each robot starts at a seeded waypoint and follows the loop with a fixed simulation time step. Heartbeats run independently at 1 Hz. Moving consumes 0.02 battery percentage points per meter.

A test peer can send `MOVE_TO`, `STOP`, or `DOCK`. The simulator sends an acknowledgement, then a result on arrival or immediate stop. A replacement command cancels the previous simulated command. Full server-side delivery is a separate milestone.

The summary prints one line per robot with sample count, heartbeat count, and a SHA-256 digest of telemetry payloads. Repeat the same scenario without injected commands to compare digests. Session IDs, UTC wire timestamps, and interleaving across robots vary between runs.
