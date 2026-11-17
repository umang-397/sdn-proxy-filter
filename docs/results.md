# Results and status

## What is verified now

| Item | Result | Evidence |
|---|---|---|
| Policy unit tests | 6/6 pass | `tests/test_policy.py` |
| Localhost end-to-end smoke test | 24/24 pass (`FAILED: 0`) | `results/local_smoke.txt`, `tests/expected/local_smoke.txt` |
| Proxy + controller protocol (fake controller) | pass, including controller-restart re-sync | local smoke checks |
| Benchmark pipeline | real localhost data + plots produced | `results/localhost/` |
| Mininet / Ryu scenarios | scripted and expected outputs committed; must be executed on an Ubuntu VM | `tests/expected/`, `topology/topo.py` |

The development machine used for this pass was Windows, where Mininet and Ryu
cannot run. The Mininet numbers are therefore **not** claimed here. Run the
commands in `docs/testing.md` on the Ubuntu VM; they overwrite the CSVs in
`results/` and produce the final graphs.

## Localhost benchmark (sanity only)

This is real measured data from `tests/local_benchmark.py`, but there is no
switch and "direct" connects straight to the service. It checks the client JSON
protocol, aggregation and plotting; it is not a substitute for the Mininet
study. Values are means over 5 repetitions, 3 requests per client per batch.

| resource | clients | proxy mean ms | direct mean ms | latency overhead | proxy req/s | direct req/s | proxy Mbps | direct Mbps |
|---|---|---|---|---|---|---|---|---|
| index | 1 | 15.82 | 6.02 | +162.8% | 64.4 | 223.5 | 0.01 | 0.04 |
| index | 5 | 12.37 | 5.34 | +131.6% | 258.0 | 490.5 | 0.05 | 0.09 |
| index | 10 | 11.83 | 4.74 | +149.9% | 483.9 | 883.6 | 0.09 | 0.17 |
| large | 1 | 22.26 | 15.12 | +47.2% | 47.8 | 67.7 | 382.53 | 541.76 |
| large | 5 | 22.37 | 12.32 | +81.6% | 181.7 | 264.8 | 1453.27 | 2118.64 |
| large | 10 | 19.09 | 12.25 | +55.9% | 312.7 | 477.4 | 2501.46 | 3818.97 |

Generated files: `results/localhost/benchmark_{proxy,direct}.csv`,
`benchmark_{proxy,direct}_summary.csv`, `latency.png`, `throughput.png`,
`summary.md`.

Expected shape of the Mininet results: the proxy adds one extra TCP hop and
per-request parsing, so latency is higher and throughput lower than the direct
baseline; the gap should be roughly constant rather than growing with client
count, because the proxy is threaded per connection.

## Mininet results to fill on the VM

Run, in order:

```bash
git checkout -- config/policy.json
sudo mn -c
# terminal 1: ryu-manager --ofp-tcp-listen-port 6653 controller/filter_controller.py
sudo python3 topology/topo.py --test basic
sudo python3 topology/topo.py --test multi
sudo python3 topology/topo.py --hard
sudo python3 topology/topo.py --bench proxy
sudo python3 topology/topo.py --bench direct
sudo python3 topology/topo.py --policy-timing --cycles 20
python3 results/plot.py
```

Then check:

```bash
python3 tests/check_expected.py results/mininet_basic.txt tests/expected/mininet_basic.txt
python3 tests/check_expected.py results/mininet_multi.txt tests/expected/mininet_multi.txt
python3 tests/check_expected.py results/mininet_hard.txt tests/expected/mininet_hard.txt
python3 tests/check_expected.py results/mininet_policy_timing.txt tests/expected/mininet_policy_timing.txt
```

The policy-timing check assumes the default `--cycles 20`.

Expected report files and the evidence checklist are in `docs/testing.md`.

## Policy change activation time

`--policy-timing` writes `results/policy_change.csv` with one row per
`BLOCK`/`ALLOW` call (`call,action,ms`). The reported value starts when the
proxy receives the control command and ends after the controller acknowledges
the flow mod; it includes the atomic policy file write and the unix-socket round
trip. `results/plot.py` adds the time series, histogram and mean/p95/max.

## Rubric mapping

| Rubric item | Where |
|---|---|
| Sockets | `app/proxy.py` (thread per client, relay, malformed/slow/down handling), local smoke |
| Mininet + SDN | `topology/topo.py`, `controller/filter_controller.py`, `--test basic` |
| Socket-SDN integration | `sync()`, controller protocol, `--test basic` dynamic checks |
| Dynamic SDN (6 marks) | automatic malformed/rate block + dynamic drop rules + re-sync on controller restart |
| Challenging scenario | `--hard`: bypass, flood, mid-transfer policy change, proxy crash |
| Performance (5 marks) | `--bench`, `--policy-timing`, corrected measurement, `results/plot.py` |
| Docs and viva (6 marks) | `docs/` and `README.md` |

## Known limitations

* Mininet/Ryu execution and terminal screenshots must be produced in the Ubuntu
  VM; this repo only contains the scripts and expected outputs for that step.
* The controller is single-switch (s1); STP is mentioned in the team split but
  not required by the current topology.
* Automatic block thresholds are tuned for a lab (`5` malformed / 10 s,
  `200` requests / 1 s); production values should be higher.
