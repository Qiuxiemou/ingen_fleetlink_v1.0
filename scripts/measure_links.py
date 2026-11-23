import argparse
import asyncio
import json
import os
import platform
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import httpx
import yaml  # type: ignore[import-untyped]

from app.models.protocol import Point
from scripts import impairment
from simulator.resilience import ResilientRobot
from simulator.run import Scenario


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(
        ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3
    )


async def measure(profile: dict, token: str, seconds: float) -> dict:
    await asyncio.to_thread(impairment.apply, profile)
    blackout_seconds = profile.get("blackout_seconds", 0)
    duration = seconds + blackout_seconds
    if blackout_seconds >= 30:
        duration = max(duration, 2 * blackout_seconds + 20)
    scenario = Scenario(
        seed=17,
        robot_count=2,
        duration_seconds=duration,
        telemetry_hz=5,
        speed_mps=1.5,
        waypoints=[Point(x=0, y=0), Point(x=8, y=0)],
    )
    impaired = ResilientRobot("ws://127.0.0.1:18800/v1/link", token, scenario, 0)
    healthy = ResilientRobot("ws://127.0.0.1:18801/v1/link", token, scenario, 1)
    tasks = [asyncio.create_task(robot.run()) for robot in (impaired, healthy)]
    snapshots = []
    outage_start = None
    outage_end = None
    detected = None
    recovered = None
    session = None
    regressions = 0
    previous_seq = 0
    healthy_offline = 0
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            while time.monotonic() - start < duration:
                elapsed = time.monotonic() - start
                if blackout_seconds and elapsed >= 5 and outage_start is None:
                    await asyncio.to_thread(impairment.blackout, True)
                    outage_start = time.monotonic()
                if (
                    outage_start is not None
                    and outage_end is None
                    and time.monotonic() - outage_start >= blackout_seconds
                ):
                    await asyncio.to_thread(impairment.blackout, False)
                    outage_end = time.monotonic()
                response = await client.get("http://127.0.0.1:18801/v1/robots")
                response.raise_for_status()
                rows = response.json()
                now = time.monotonic()
                for robot in rows:
                    if robot["robot_id"] == "sim-0002" and elapsed > 3:
                        healthy_offline += int(robot["link"]["state"] == "OFFLINE")
                    if robot["robot_id"] != "sim-0001":
                        continue
                    if session is None:
                        session = robot["session_id"]
                    metrics = robot["link"]
                    seq = metrics["last_sample_seq"]
                    regressions += int(seq < previous_seq)
                    previous_seq = seq
                    if (
                        outage_start is not None
                        and detected is None
                        and metrics["state"] == "OFFLINE"
                    ):
                        detected = now - outage_start
                    if (
                        outage_end is not None
                        and recovered is None
                        and metrics["resumptions"] > 0
                        and metrics["state"] != "OFFLINE"
                    ):
                        recovered = now - outage_end
                    snapshots.append(
                        {
                            "elapsed": round(now - start, 3),
                            "session_id": robot["session_id"],
                            "link": metrics,
                        }
                    )
                for task in tasks:
                    if task.done() and task.exception():
                        raise task.exception()  # type: ignore[misc]
                await asyncio.sleep(0.1)
        summaries = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(impairment.clear)
    if not snapshots:
        raise RuntimeError("No robot snapshots collected")
    latest = snapshots[-1]["link"]
    command_rtt = latest["command_rtt_ms"]
    states = [row["link"]["state"] for row in snapshots]
    staleness = [
        row["link"]["telemetry_staleness_seconds"]
        for row in snapshots
        if row["link"]["telemetry_staleness_seconds"] is not None
    ]
    transitions = sum(left != right for left, right in pairwise(states))
    result = {
        "profile": profile,
        "duration_seconds": duration,
        "command_samples": len(command_rtt),
        "command_rtt_p50_ms": percentile(command_rtt, 0.5),
        "command_rtt_p95_ms": percentile(command_rtt, 0.95),
        "command_rtt_p99_ms": percentile(command_rtt, 0.99),
        "disconnect_detection_seconds": (
            round(detected, 3) if detected is not None else None
        ),
        "reconnect_seconds": round(recovered, 3) if recovered is not None else None,
        "max_staleness_seconds": max(staleness) if staleness else None,
        "state_transitions": transitions,
        "latest_regressions": regressions,
        "same_session": all(row["session_id"] == session for row in snapshots),
        "healthy_offline_observations": healthy_offline,
        "robots": [json.loads(summary) for summary in summaries],
        "final_metrics": latest,
        "trace": snapshots,
    }
    assert regressions == 0
    assert healthy_offline == 0
    if blackout_seconds:
        assert detected is not None and detected <= 3.0
        assert recovered is not None
        assert result["same_session"]
        assert latest["replayed_samples"] > 0
    return result


async def main_async(args: argparse.Namespace) -> None:
    profiles = yaml.safe_load(Path("lab/profiles.yaml").read_text())["profiles"]
    if args.profile:
        profiles = [item for item in profiles if item["name"] in args.profile]
    token = secrets.token_urlsafe(32)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results = (
        json.loads(output.read_text(encoding="utf-8"))["results"]
        if args.profile and output.exists()
        else []
    )
    for profile in profiles:
        with await asyncio.to_thread(
            subprocess.Popen,
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "18801",
                "--ws-max-size",
                "32768",
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            env={**os.environ, "ROBOT_DEV_TOKEN": token, "LAB_PROBES": "true"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as gateway:
            try:
                async with httpx.AsyncClient(timeout=1) as client:
                    for _ in range(50):
                        try:
                            if (
                                await client.get("http://127.0.0.1:18801/healthz")
                            ).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        raise RuntimeError("Gateway did not start")
                result = await measure(profile, token, args.seconds)
                results = [
                    previous
                    for previous in results
                    if previous["profile"]["name"] != profile["name"]
                ]
                results.append(result)
                output.write_text(
                    json.dumps(
                        {
                            "environment": {
                                "platform": platform.platform(),
                                "python": sys.version,
                                "cpu": platform.processor(),
                                "logical_cpus": os.cpu_count(),
                                "measured_at_utc": datetime.now(UTC).isoformat(),
                                "toxiproxy": impairment.api("GET", "/version"),
                            },
                            "results": results,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(
                    profile["name"],
                    "p95_ms",
                    result["command_rtt_p95_ms"],
                    "reconnect_s",
                    result["reconnect_seconds"],
                    flush=True,
                )
            finally:
                gateway.terminate()
                await asyncio.to_thread(gateway.wait, timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure the FleetLink network profile matrix"
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=25,
        help="Baseline seconds plus blackout duration",
    )
    parser.add_argument("--profile", action="append")
    parser.add_argument(
        "--output", default="weekly/week-03/results/link_measurements.json"
    )
    args = parser.parse_args()
    impairment.initialize()
    try:
        asyncio.run(main_async(args))
    finally:
        impairment.clear()


if __name__ == "__main__":
    main()
