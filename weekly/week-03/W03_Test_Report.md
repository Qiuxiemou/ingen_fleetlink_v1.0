# Week 3 measured link budget

| Profile | Samples | p50 ms | p95 ms | p99 ms |
| --- | ---: | ---: | ---: | ---: |
| clean | 25 | 1.74 | 2.42 | 2.48 |
| latency_50 | 25 | 103.87 | 104.27 | 104.36 |
| latency_100 | 25 | 203.79 | 205.58 | 205.83 |
| latency_200 | 24 | 403.72 | 404.32 | 404.46 |
| latency_300 | 24 | 603.57 | 604.36 | 604.48 |
| jitter_30 | 24 | 116.33 | 150.95 | 153.20 |
| loss_1 | 25 | 1.70 | 2.56 | 2.81 |
| loss_5 | 25 | 1.75 | 147.75 | 187.06 |
| loss_10 | 22 | 1.89 | 214.43 | 217.67 |
| asymmetric | 24 | 223.51 | 223.83 | 223.84 |
| bandwidth_8k | 25 | 28.65 | 30.32 | 64.98 |
| blackout_5 | 25 | 1.76 | 2.65 | 2.77 |
| blackout_15 | 25 | 1.81 | 2.11 | 2.14 |
| blackout_30 | 50 | 2.07 | 2.78 | 4.33 |

| Target | Result | Status |
| --- | --- | --- |
| Clean command p95 below 150 ms | 2.42 ms | Met |
| Detect link loss within 3 s | 2.44 s maximum | Met |
| Stop within 500 ms of deadman expiry | 5.90 ms | Met |
| No latest pose regression | 0 | Met |
| 15 s blackout resumes session | True | Met |
| Stable state under 10 percent loss | 0 state changes | Met |
| Unaffected robots keep running | 0 offline observations | Met |
| Zero expired command executions | Expiry enforcement is scheduled for Week 4 | Pending |

See W03_Link_Budget_Report.docx for methods, recovery measurements, and limits.
