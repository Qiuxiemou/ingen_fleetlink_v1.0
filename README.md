# ingen_fleetlink_v1.0

Fleet connectivity and mission backend for simulated robotics systems.

## Weekly submissions

| Week | Deliverables |
| --- | --- |
| [Week 1](weekly/week-01/README.md) | Service foundation, architecture decisions, failure modes, and readiness checks |
| [Week 2](weekly/week-02/README.md) | Protocol v1, robot REST API, simulator v0, and contract tests |
| [Week 3](weekly/week-03/README.md) | Network lab, liveness, session recovery, telemetry replay, and measured link budget |

The implementation continues under app/ and simulator/. Each weekly index links its documents, tests, and runnable tools.

## Local development

Install Python 3.11 and uv, then run `uv sync --locked`. Copy `.env.example` to `.env` and generate a development token with `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`. Set that value as `ROBOT_DEV_TOKEN` in your local `.env`.

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws-max-size 32768
```

Run the simulator in a second terminal.

```sh
uv run python -m simulator.run simulator/scenario.yaml --seconds 10
```

Inspect robots at `http://127.0.0.1:8000/v1/robots` and OpenAPI at `http://127.0.0.1:8000/docs`. The gateway and API share an in-memory robot registry, so run one server worker for the v1 simulator.

- [Architecture decisions and synthetic sizing](docs/W01_Architecture_Decisions.md)
- [Service design and failure modes](docs/W01_Service_Design.md)
- [Robot link v1 contract](docs/W02_Protocol_Spec.md)
- [Week 2 test report](docs/W02_Test_Report.md)
- [Simulator scenarios](simulator/README.md)

## Verification

Run `uv run ruff check .`, `uv run black --check .`, `uv run mypy app simulator`, and `uv run pytest -v --cov=app --cov=simulator --cov-report=term-missing`.

For the real PostgreSQL test, start an isolated instance with password authentication. Use the test-only examples below for a disposable local database.

```sh
docker run --rm --name fleetlink-test-db -p 127.0.0.1:55432:5432 -e POSTGRES_USER=fleetlink -e POSTGRES_PASSWORD=ci_test_only -e POSTGRES_DB=fleetlink_test postgres:16
```

Set `FLEETLINK_TEST_DATABASE_URL` to `postgresql+psycopg://fleetlink:ci_test_only@127.0.0.1:55432/fleetlink_test` and rerun pytest. Use the same URL for `DATABASE_URL` to check the running server. After stopping the database, `/readyz` should return 503 and `/healthz` should still return 200.

The GitHub Actions job provisions PostgreSQL automatically. To verify failure propagation, manually run **FleetLink CI** with **Inject a failing test to verify the pytest step** enabled. The test named `test_intentional_ci_failure` should fail and the job should be marked failed. A normal run skips the injection.

## Source material

This repository uses synthetic scenarios, waypoints, and telemetry. Keep internal reference documents and private deliverables in their approved storage. Published project notes describe the simulator and use independently defined sizing assumptions.
