# Week 3 submission

- [Network lab and reproduction commands](../../lab/README.md)
- [Versioned network profiles](../../lab/profiles.yaml)
- [Resilience design and command expiry policy](../../docs/W03_Resilience_Design.md)
- [Measured link budget report](W03_Link_Budget_Report.docx)
- [Test report and target comparison](W03_Test_Report.md)
- [Raw per-profile measurements](results/link_measurements.json)
- [Measurement summary CSV](results/summary.csv)
- [Fault isolation and deadman measurements](results/recovery_checks.json)
- [Engineering log](../Wk-03-Log.md)
- [Resilience regression tests](../../tests/test_resilience.py)

Run `uv run python -m scripts.measure_links` after starting the lab. Run `uv run python -m scripts.verify_recovery` for independent authentication-failure isolation and local deadman timing. Rebuild the Word report and summary tables with `uv run --group report python -m scripts.build_report`.
