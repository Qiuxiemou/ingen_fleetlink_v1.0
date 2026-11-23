import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

from app.models.protocol import Command, Point
from simulator.resilience import ResilientRobot
from simulator.run import Scenario


async def exercise(token: str) -> dict:
    scenario = Scenario(
        seed=17,
        robot_count=2,
        duration_seconds=4,
        telemetry_hz=20,
        replay_hz=40,
        speed_mps=1,
        waypoints=[Point(x=0, y=0), Point(x=8, y=0)],
    )
    bad = ResilientRobot("ws://127.0.0.1:18802/v1/link", "wrong-token", scenario, 0)
    healthy = ResilientRobot("ws://127.0.0.1:18802/v1/link", token, scenario, 1)
    results = await asyncio.gather(bad.run(), healthy.run(), return_exceptions=True)
    assert isinstance(results[0], RuntimeError) and "AUTH_FAILED" in str(results[0])
    assert isinstance(results[1], str)
    healthy_summary = json.loads(results[1])
    assert healthy_summary["generated"] == 80 and healthy_summary["sent"] >= 35

    deadman = ResilientRobot("ws://unused", token, scenario, 2)
    deadman.robot.apply(
        Command(command_id=uuid4(), command="MOVE_TO", target=Point(x=100, y=0))
    )
    deadman.last_response = time.monotonic()
    start = time.perf_counter()
    generation = asyncio.create_task(deadman.generate())
    while deadman.robot.mode != "STOPPED":
        await asyncio.sleep(0.005)
    delay = time.perf_counter() - start
    await generation
    assert 2.4 <= delay < 3.0
    result = {
        "authentication_failure_isolated": True,
        "unaffected_robot": healthy_summary,
        "deadman_seconds": round(delay, 4),
        "stop_after_deadman_expiry_seconds": round(max(0, delay - 2.5), 4),
    }
    return result


async def main_async() -> None:
    token = secrets.token_urlsafe(32)
    gateway = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "18802",
        "--log-level",
        "warning",
        "--no-access-log",
        env={**os.environ, "ROBOT_DEV_TOKEN": token, "LAB_PROBES": "false"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            for _ in range(50):
                try:
                    if (
                        await client.get("http://127.0.0.1:18802/healthz")
                    ).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Gateway did not start")
        result = await exercise(token)
        output = Path("weekly/week-03/results/recovery_checks.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    finally:
        gateway.terminate()
        await gateway.wait()


if __name__ == "__main__":
    asyncio.run(main_async())
