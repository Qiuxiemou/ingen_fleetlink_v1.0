# Week 2 test report

Local verification used Python 3.11.18 and PostgreSQL 16 with the dependencies in `uv.lock`.

```text
26 passed
app/api/robots.py        100%
app/gateway/link.py       96%
simulator/run.py          84%
Total                     93%
```

The contract suite covers authentication, unsupported versions, malformed JSON, oversized UTF-8 messages, timestamps without UTC, duplicate or skipped sequences, unknown message types, session identity, and versioned REST errors. A standalone WebSocket client also exercised the worked example against Uvicorn. A test peer sent MOVE_TO, STOP, and DOCK to the simulator and verified acknowledgements and completion results.

With PostgreSQL reachable, `/readyz` returned 200. With rejected credentials and again after stopping the disposable database, it returned 503. `/healthz` kept returning 200. Injecting the failing test defined by the workflow produced pytest exit code 1 locally. The hosted GitHub Actions failure probe is pending publication of the workflow.

Two independent Uvicorn instances each ran the same 20-robot scenario for 600 seconds. In each run, every robot sent 3,000 telemetry samples and 600 heartbeats. All 20 per-robot telemetry digests matched across the two runs. Both registries showed all robots connected during the run and disconnected afterward.
