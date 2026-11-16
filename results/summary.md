# Benchmark summary

Modes: direct, proxy. Values are means across repeats.

| resource | clients | proxy mean ms | direct mean ms | latency overhead | proxy req/s | direct req/s | proxy Mbps | direct Mbps |
|---|---|---|---|---|---|---|---|---|
| index | 1 | 1.12 | 0.54 | +107.2% | 861.6 | 1717.5 | 0.17 | 0.33 |
| index | 5 | 1.78 | 0.73 | +144.2% | 2520.6 | 5431.9 | 0.48 | 1.04 |
| index | 10 | 2.60 | 0.88 | +195.8% | 3199.8 | 8908.1 | 0.61 | 1.71 |
| large | 1 | 2.70 | 2.46 | +10.1% | 356.3 | 386.8 | 2850.61 | 3094.03 |
| large | 5 | 5.32 | 3.87 | +37.7% | 870.3 | 1128.7 | 6962.08 | 9029.85 |
| large | 10 | 9.91 | 6.01 | +65.0% | 868.9 | 1414.1 | 6951.13 | 11312.94 |

`mean` is the mean per-request latency; request and byte rates are measured by the load generator itself (`app/client.py --bench`), not from process start-up time.
