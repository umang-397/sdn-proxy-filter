# Benchmark summary

Modes: direct, proxy. Values are means across repeats.

| resource | clients | proxy mean ms | direct mean ms | latency overhead | proxy req/s | direct req/s | proxy Mbps | direct Mbps |
|---|---|---|---|---|---|---|---|---|
| index | 1 | 1.01 | 0.48 | +109.0% | 942.2 | 1887.1 | 0.18 | 0.36 |
| index | 5 | 1.84 | 0.72 | +154.5% | 2503.9 | 5705.1 | 0.48 | 1.10 |
| index | 10 | 2.96 | 0.85 | +249.4% | 2930.8 | 8933.6 | 0.56 | 1.72 |
| large | 1 | 2.88 | 2.37 | +21.4% | 332.3 | 403.0 | 2658.65 | 3224.14 |
| large | 5 | 5.84 | 3.70 | +57.8% | 785.7 | 1193.5 | 6285.64 | 9548.31 |
| large | 10 | 12.20 | 5.68 | +114.9% | 743.1 | 1486.1 | 5945.13 | 11888.69 |

`mean` is the mean per-request latency; request and byte rates are measured by the load generator itself (`app/client.py --bench`), not from process start-up time.
