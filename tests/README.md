# Tests

| Command | Runs where | Expected |
|---|---|---|
| `python3 tests/test_policy.py` | anywhere | 6 tests, `OK` |
| `python3 tests/local_smoke.py` | anywhere | 24 PASS, `FAILED: 0` |
| `python3 tests/local_benchmark.py` | anywhere | writes `results/localhost/` |
| `sudo python3 topology/topo.py --test basic` | Ubuntu + Mininet | matches `expected/mininet_basic.txt` |
| `sudo python3 topology/topo.py --test multi` | Ubuntu + Mininet | matches `expected/mininet_multi.txt` |
| `sudo python3 topology/topo.py --hard` | Ubuntu + Mininet | matches `expected/mininet_hard.txt` |
| `sudo python3 topology/topo.py --policy-timing` | Ubuntu + Mininet | matches `expected/mininet_policy_timing.txt` |

After a Mininet run:

```bash
python3 tests/check_expected.py results/mininet_basic.txt \
    tests/expected/mininet_basic.txt
```

`flood.py` is the request generator used by the basic/hard scenarios:
`--mode malformed` sends invalid request lines, `--mode valid` sends
`GET web/index`.

`local_benchmark.py` is a localhost-only pipeline check. It uses the same
`BENCHJSON` client output and CSV schema as the Mininet benchmark and is clearly
labelled as non-Mininet data in `results/localhost/`.
