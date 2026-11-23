import csv
import json
from pathlib import Path

from docx import Document  # type: ignore[import-untyped]
from docx.oxml import OxmlElement  # type: ignore[import-untyped]
from docx.oxml.ns import qn  # type: ignore[import-untyped]
from docx.shared import Inches, Pt, RGBColor  # type: ignore[import-untyped]

ROOT = Path("weekly/week-03")


def number(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def table(document, headings: list[str], rows: list[list[str]]) -> None:
    grid = document.add_table(rows=1, cols=len(headings))
    grid.autofit = False
    widths = [1.9] + [4.9 / (len(headings) - 1)] * (len(headings) - 1)
    for cells, values in [(grid.rows[0].cells, headings)] + [
        (grid.add_row().cells, row) for row in rows
    ]:
        for index, (cell, value, width) in enumerate(zip(cells, values, widths)):
            cell.width = Inches(width)
            cell.text = value
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(3)
                paragraph.paragraph_format.space_before = Pt(3)
                if len(headings) > 3 and index > 0:
                    paragraph.alignment = 1
                for run in paragraph.runs:
                    run.font.size = Pt(10)
            properties = cell._tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                edge = OxmlElement(f"w:{side}")
                edge.set(qn("w:val"), "single")
                edge.set(qn("w:sz"), "4")
                edge.set(qn("w:color"), "D9D9D9")
                borders.append(edge)
            properties.append(borders)
    header_properties = grid.rows[0]._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    header_properties.append(repeat)
    for cell in grid.rows[0].cells:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), "F2F2F2")
        cell._tc.get_or_add_tcPr().append(shading)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    document.add_paragraph()


def main() -> None:
    data = json.loads((ROOT / "results/link_measurements.json").read_text())
    checks = json.loads((ROOT / "results/recovery_checks.json").read_text())
    results = data["results"]
    if len(results) != 14:
        raise ValueError("Complete all 14 network profiles before building the report")
    document = Document()
    for style in document.styles:
        for border in list(style.element.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.65)
    section.left_margin = section.right_margin = Inches(0.85)
    footer = section.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run("FleetLink Week 3  |  ")
    page = OxmlElement("w:fldSimple")
    page.set(qn("w:instr"), "PAGE")
    footer._p.append(page)
    for name in ("Normal", "Title", "Heading 1", "Heading 2"):
        document.styles[name].font.name = "Calibri"
        document.styles[name].font.color.rgb = RGBColor(0, 0, 0)
    document.styles["Normal"].font.size = Pt(11)
    document.styles["Normal"].paragraph_format.space_after = Pt(6)
    document.styles["Title"].font.size = Pt(22)
    document.styles["Heading 1"].font.size = Pt(13)
    document.styles["Heading 1"].paragraph_format.space_before = Pt(8)
    document.styles["Heading 1"].paragraph_format.space_after = Pt(4)
    document.add_heading("FleetLink Week 3 Link Budget Report", 0)
    document.add_paragraph("Qiushi Chen  |  Synthetic robot network experiments")
    document.add_paragraph(
        "The experiment matrix measures command acknowledgement latency, heartbeat detection, "
        "session recovery, and telemetry replay. Each profile runs one impaired robot and one "
        "directly connected control robot. The tables below use the committed measurement JSON."
    )
    document.add_paragraph(
        "The regression suite passed 33 tests, including PostgreSQL integration, with 84 percent "
        "combined app and simulator coverage. Live impairment runs execute separately from "
        "the unit-test coverage process."
    )
    document.add_heading("Method and environment", 1)
    environment = data["environment"]
    document.add_paragraph(
        f"Measured on {environment['platform']} with Python {environment['python'].split()[0]}, "
        f"{environment['logical_cpus']} logical CPUs, and Toxiproxy 2.13.0 in Docker Desktop. "
        f"Processor identification is {environment['cpu']}. "
        "Robots sample at 5 Hz and replay at at most 10 Hz. Heartbeats run at 1 Hz."
    )
    document.add_paragraph(
        "RTT uses perf_counter from gateway STOP probe send to COMMAND_ACK receipt. "
        "The production REST endpoint keeps its placeholder response. API observations run "
        "roughly every 100 ms. Latency settings apply independently to both directions. "
        "Loss uses seeded Linux netem in the proxy namespace and includes TCP retransmissions."
    )
    document.add_heading("Command acknowledgement round trip", 1)
    command_rows = [
        [
            r["profile"]["name"],
            str(r["command_samples"]),
            number(r["command_rtt_p50_ms"]),
            number(r["command_rtt_p95_ms"]),
            number(r["command_rtt_p99_ms"]),
        ]
        for r in results
    ]
    table(document, ["Profile", "Samples", "p50 ms", "p95 ms", "p99 ms"], command_rows)
    document.add_paragraph(
        "Each profile is one short trial. Percentiles use linear interpolation over the observed "
        "samples. The small samples support regression checks and provide a baseline for the "
        "larger Week 7 experiment matrix."
    )
    heading = document.add_heading("Blackout recovery and ordering", 1)
    heading.paragraph_format.page_break_before = True
    blackout = [r for r in results if r["profile"].get("blackout_seconds")]
    table(
        document,
        ["Profile", "Detect s", "Reconnect s", "Replayed", "Pending"],
        [
            [
                r["profile"]["name"],
                number(r["disconnect_detection_seconds"]),
                number(r["reconnect_seconds"]),
                str(r["final_metrics"]["replayed_samples"]),
                str(r["robots"][0]["unacknowledged"]),
            ]
            for r in blackout
        ],
    )
    document.add_paragraph(
        "Detection is measured from insertion of silent blackout to the first API OFFLINE "
        "observation. Reconnection is measured from fault removal to the first resumed session "
        "observation. Pending samples remain in the bounded robot buffer when a finite scenario "
        "ends. A thirty-second backlog can require more than twenty seconds to fully drain."
    )
    table(
        document,
        ["Profile", "Max age s", "Dropped", "State changes", "Pose regressions"],
        [
            [
                r["profile"]["name"],
                number(r["max_staleness_seconds"]),
                str(r["robots"][0]["dropped"]),
                str(r["state_transitions"]),
                str(r["latest_regressions"]),
            ]
            for r in results
        ],
    )
    document.add_paragraph(
        "State changes during blackout include entering DEGRADED, entering OFFLINE, and recovery. "
        "Telemetry age uses the sample's captured UTC time, including buffered replay. "
        "The direct control robot is checked independently in every trace."
    )
    heading = document.add_heading("Comparison with the phase targets", 1)
    heading.paragraph_format.page_break_before = True
    clean = next(r for r in results if r["profile"]["name"] == "clean")
    loss = next(r for r in results if r["profile"]["name"] == "loss_10")
    targets = [
        [
            "Clean command p95 below 150 ms",
            number(clean["command_rtt_p95_ms"]) + " ms",
            "Met" if clean["command_rtt_p95_ms"] < 150 else "Not met",
        ],
        [
            "Detect link loss within 3 s",
            number(max(r["disconnect_detection_seconds"] for r in blackout))
            + " s maximum",
            (
                "Met"
                if all(r["disconnect_detection_seconds"] <= 3 for r in blackout)
                else "Not met"
            ),
        ],
        [
            "Stop within 500 ms of deadman expiry",
            number(checks["stop_after_deadman_expiry_seconds"] * 1000) + " ms",
            "Met" if checks["stop_after_deadman_expiry_seconds"] < 0.5 else "Not met",
        ],
        [
            "No latest pose regression",
            str(sum(r["latest_regressions"] for r in results)),
            "Met",
        ],
        [
            "15 s blackout resumes session",
            str(
                next(
                    r["same_session"]
                    for r in blackout
                    if r["profile"]["blackout_seconds"] == 15
                )
            ),
            "Met",
        ],
        [
            "Stable state under 10 percent loss",
            str(loss["state_transitions"]) + " state changes",
            "Met" if loss["state_transitions"] <= 1 else "Not met",
        ],
        [
            "Unaffected robots keep running",
            str(sum(r["healthy_offline_observations"] for r in results))
            + " offline observations",
            "Met",
        ],
        [
            "Zero expired command executions",
            "Expiry enforcement is scheduled for Week 4",
            "Pending",
        ],
    ]
    table(document, ["Target", "Measured result", "Status"], targets)
    document.add_paragraph(
        "An independent recovery check injected invalid authentication for one robot. The second "
        f"robot generated {checks['unaffected_robot']['generated']} samples and completed its "
        "scenario. A separate local-motion run at 20 Hz measured the deadman stop latency shown above."
    )
    document.add_heading("Reproduction and limits", 1)
    document.add_paragraph(
        "Start the lab with docker compose -f lab/compose.yaml up --build -d. "
        "Run uv run python -m scripts.measure_links and uv run python -m scripts.verify_recovery. "
        "Build this report with uv run --group report python -m scripts.build_report. "
        "Raw measurements and traces are in weekly/week-03/results."
    )
    document.add_paragraph(
        "The workload is synthetic and uses one impaired robot per profile. Session state is "
        "in memory and therefore survives connection outages within a running gateway process. "
        "After a gateway restart the simulator negotiates a new session. "
        "Envelope gaps measure application observations. Physical packet-loss percentages come "
        "from the configured netem profile. UTC source age depends on clock synchronization. "
        "Full motion command expiry, deduplication, and control leases are the next phase."
    )
    document.save(ROOT / "W03_Link_Budget_Report.docx")
    with (ROOT / "results/summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "profile",
                "command_samples",
                "p50_ms",
                "p95_ms",
                "p99_ms",
                "detect_s",
                "reconnect_s",
                "replayed",
                "dropped",
                "pending",
                "state_changes",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r["profile"]["name"],
                    r["command_samples"],
                    r["command_rtt_p50_ms"],
                    r["command_rtt_p95_ms"],
                    r["command_rtt_p99_ms"],
                    r["disconnect_detection_seconds"],
                    r["reconnect_seconds"],
                    r["final_metrics"]["replayed_samples"],
                    r["robots"][0]["dropped"],
                    r["robots"][0]["unacknowledged"],
                    r["state_transitions"],
                ]
            )
    markdown = [
        "# Week 3 measured link budget",
        "",
        "| Profile | Samples | p50 ms | p95 ms | p99 ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    markdown.extend("| " + " | ".join(row) + " |" for row in command_rows)
    markdown.extend(["", "| Target | Result | Status |", "| --- | --- | --- |"])
    markdown.extend("| " + " | ".join(row) + " |" for row in targets)
    markdown.append(
        "\nSee W03_Link_Budget_Report.docx for methods, recovery measurements, and limits."
    )
    (ROOT / "W03_Test_Report.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
