# Benchmark summary

Modes: direct, proxy. Values are means across repeats.

| resource | clients | proxy mean ms | direct mean ms | latency overhead | proxy req/s | direct req/s | proxy Mbps | direct Mbps |
|---|---|---|---|---|---|---|---|---|
| index | 1 | 15.82 | 6.02 | +162.8% | 64.4 | 223.5 | 0.01 | 0.04 |
| index | 5 | 12.37 | 5.34 | +131.6% | 258.0 | 490.5 | 0.05 | 0.09 |
| index | 10 | 11.83 | 4.74 | +149.9% | 483.9 | 883.6 | 0.09 | 0.17 |
| large | 1 | 22.26 | 15.12 | +47.2% | 47.8 | 67.7 | 382.53 | 541.76 |
| large | 5 | 22.37 | 12.32 | +81.6% | 181.7 | 264.8 | 1453.27 | 2118.64 |
| large | 10 | 19.09 | 12.25 | +55.9% | 312.7 | 477.4 | 2501.46 | 3818.97 |

`mean` is the mean per-request latency; request and byte rates are measured by the load generator itself (`app/client.py --bench`), not from process start-up time.
