# Week 3 network experiments

Start the lab from the repository root with `docker compose -f lab/compose.yaml up --build -d`. Run `uv run python -m scripts.impairment init`, then `uv run python -m scripts.measure_links`. The measurement command starts and stops its own gateway on port 18801, runs one impaired robot through port 18800 and an independent control robot directly through port 18801, and saves JSON under weekly/week-03/results. Docker Desktop must allow host.docker.internal to reach the local gateway.

Use `--profile blackout_15` or another profile name to narrow a run. Multiple --profile options are supported. `--seconds 25` sets the baseline duration before adding blackout seconds. Keep at least 20 baseline seconds so the recovery window is meaningful. Sampling UTC times, OS scheduling, and TCP retransmissions vary between runs. YAML profiles and seeds reproduce the experiment configuration.

For blackouts of at least 30 seconds, the runner allows at least twice the blackout duration plus twenty seconds in total. This gives the backlog time to drain at the default rates with scheduler overhead. When --profile is supplied and the output already exists, matching profile rows are replaced and other profile measurements are retained.

To manually apply a profile, run `uv run python -m scripts.impairment latency_100`. To remove it, run `uv run python -m scripts.impairment clear`. The measurement script clears impairments in a finally block. Stop the lab with `docker compose -f lab/compose.yaml down`.

Toxiproxy 2.13.0 provides directional stream latency, jitter, bandwidth caps, and silent blackouts. The loss profiles use Linux tc netem in a NET_ADMIN helper sharing only the proxy's network namespace. They drop real egress IP packets at 1, 5, or 10 percent, allowing TCP retransmission to remain part of the experiment. Toxiproxy chunk dropping would alter TCP stream content and has different semantics, so the supplied loss scenarios use netem. The qdisc is limited to the disposable lab namespace.

Latency profiles specify one-way delay on both streams. Thus latency_100 adds approximately 200 ms to round trips. The asymmetric profile adds 200 ms upstream and 20 ms downstream. The bandwidth profile uses 8 KB/s in each direction. Silent blackout uses timeout toxics in both directions for the requested interval.

The raw traces include command RTT samples, per-robot link metrics, telemetry counters, reconnect delays, and the unaffected control robot's state. Assertions require no latest-sample regression, no control robot OFFLINE observations, and session resumption after blackout. Detection times are sampled through the API at roughly 100 ms intervals and include that observation granularity.

Protocol and impairment behavior references are [the project protocol spec](../docs/W02_Protocol_Spec.md), [the recovery design](../docs/W03_Resilience_Design.md), and [Toxiproxy 2.13.0 documentation](https://github.com/Shopify/toxiproxy/blob/v2.13.0/README.md).
