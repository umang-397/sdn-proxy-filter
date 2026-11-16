# Results directory

## Committed in the repository

| Path | What it is |
|---|---|
| `test_policy.txt` | real output of `tests/test_policy.py` (6/6) |
| `local_smoke.txt` | real output of `tests/local_smoke.py` (24/24, `FAILED: 0`) |
| `localhost/` | real localhost-only benchmark data and plots; useful for checking the pipeline, **not** Mininet results |
| `screenshots/` | existing policy unit test and proxy smoke test screenshots |
| `plot.py` | graphs + summary table from benchmark CSVs |

## Generated on the Ubuntu VM (not committed yet)

Running `topology/topo.py` modes writes:

```
mininet_basic.txt
mininet_multi.txt
mininet_hard.txt
mininet_policy_timing.txt

benchmark_proxy.csv
benchmark_proxy_summary.csv
benchmark_direct.csv
benchmark_direct_summary.csv
policy_change.csv
latency.png
throughput.png
policy_change.png
summary.md
evidence/dumpflows_*.txt
evidence/proxy_*.log
evidence/hard_*.txt
```

## Evidence checklist (plan step 7)

* [ ] `proxy.log` before/after a policy change (`evidence/proxy_*.log`)
* [ ] `dump-flows` before/after (`evidence/dumpflows_*.txt`)
* [ ] terminal screenshots of the scenario runs (`screenshots/`)
* [ ] CSVs from 5 repetitions, proxy and direct
* [ ] policy-change CSV over 20 BLOCK/ALLOW pairs
* [ ] graphs produced by `results/plot.py`

## Reproduce local results

```bash
python3 tests/test_policy.py | tee results/test_policy.txt
python3 tests/local_smoke.py | tee results/local_smoke.txt
python3 tests/check_expected.py results/local_smoke.txt tests/expected/local_smoke.txt
python3 tests/local_benchmark.py
python3 results/plot.py --dir results/localhost --out results/localhost
```
