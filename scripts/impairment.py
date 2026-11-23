import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx
import yaml  # type: ignore[import-untyped]

COMPOSE = ["docker", "compose", "-f", "lab/compose.yaml"]
API = "http://127.0.0.1:18474"
PROXY = "fleetlink"


def api(method: str, path: str, data: object = None) -> object:
    response = httpx.request(method, API + path, json=data, timeout=10)
    response.raise_for_status()
    return response.json() if response.content else None


def clear() -> None:
    subprocess.run(
        [*COMPOSE, "exec", "-T", "netem", "tc", "qdisc", "del", "dev", "eth0", "root"],
        capture_output=True,
        check=False,
    )
    api("POST", "/reset", {})


def initialize() -> None:
    for attempt in range(50):
        try:
            api("GET", "/version")
            break
        except httpx.TransportError:
            if attempt == 49:
                raise
            time.sleep(0.1)
    api(
        "POST",
        "/populate",
        [
            {
                "name": PROXY,
                "listen": "0.0.0.0:18800",
                "upstream": "host.docker.internal:18801",
                "enabled": True,
            }
        ],
    )


def apply(profile: dict) -> None:
    clear()
    latency = profile.get("latency_ms", 0)
    for direction in ("upstream", "downstream"):
        delay = profile.get(f"{direction}_ms", latency)
        if delay:
            api(
                "POST",
                f"/proxies/{PROXY}/toxics",
                {
                    "name": f"delay_{direction}",
                    "type": "latency",
                    "stream": direction,
                    "attributes": {
                        "latency": delay,
                        "jitter": profile.get("jitter_ms", 0),
                    },
                },
            )
        if profile.get("bandwidth_kbps"):
            api(
                "POST",
                f"/proxies/{PROXY}/toxics",
                {
                    "name": f"bandwidth_{direction}",
                    "type": "bandwidth",
                    "stream": direction,
                    "attributes": {"rate": profile["bandwidth_kbps"]},
                },
            )
    if profile.get("loss_percent"):
        subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "netem",
                "tc",
                "qdisc",
                "replace",
                "dev",
                "eth0",
                "root",
                "netem",
                "loss",
                f"{profile['loss_percent']}%",
                "seed",
                "17",
            ],
            check=True,
        )


def blackout(enabled: bool) -> None:
    if enabled:
        for direction in ("upstream", "downstream"):
            api(
                "POST",
                f"/proxies/{PROXY}/toxics",
                {
                    "name": f"blackout_{direction}",
                    "type": "timeout",
                    "stream": direction,
                    "attributes": {"timeout": 0},
                },
            )
    else:
        for direction in ("upstream", "downstream"):
            api("DELETE", f"/proxies/{PROXY}/toxics/blackout_{direction}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", help="Profile name, init, or clear")
    args = parser.parse_args()
    if args.profile == "init":
        initialize()
    elif args.profile == "clear":
        clear()
    else:
        profiles = yaml.safe_load(Path("lab/profiles.yaml").read_text())["profiles"]
        profile = next(item for item in profiles if item["name"] == args.profile)
        apply(profile)
        print(json.dumps(profile))


if __name__ == "__main__":
    main()
