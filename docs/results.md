# Results and status

## What was verified

| Item | Result | Evidence |
|---|---|---|
| Policy unit tests | 6/6 pass | `results/test_policy.txt`, `tests/test_policy.py` |
| Localhost end-to-end smoke test | 25/25 pass (`FAILED: 0`) | `results/local_smoke.txt`, `tests/expected/local_smoke.txt` |
| Mininet basic acceptance | 15/15 pass | `results/mininet_basic.txt`, `tests/expected/mininet_basic.txt` |
| Mininet multi-client | 12/12 pass | `results/mininet_multi.txt`, `tests/expected/mininet_multi.txt` |
| Mininet hard scenarios | 16/16 pass | `results/mininet_hard.txt`, `tests/expected/mininet_hard.txt` |
| Policy-change timing | 40 measurements, 2/2 report checks pass | `results/policy_change.csv`, `results/mininet_policy_timing.txt` |
| Mininet benchmark | 5 repetitions x 3 client counts x 2 resources, proxy and direct | `results/benchmark_{proxy,direct}{,_summary}.csv` |
| Proxy + controller protocol | pass, including controller-restart re-sync | local smoke + MR01 restart dumps |
| MR01 controller restart | drop rule re-pushed automatically | `results/evidence/restart_after_ryu.txt` |
| MR01 switch reconnect | drop rule re-installed after reconnect | `results/evidence/restart_after_switch.txt` |

All scripts and expected outputs are committed. The Mininet reports in
`results/` are the actual runs used for the report.

## Mininet benchmark results

Values are means across 5 repetitions, from `results/summary.md`. Each
repetition sends 5 requests per client through the proxy or directly.

| resource | clients | proxy mean ms | direct mean ms | latency overhead | proxy req/s | direct req/s | proxy Mbps | direct Mbps |
|---|---|---|---|---|---|---|---|---|
| index | 1 | 1.01 | 0.48 | +109.0% | 942.2 | 1887.1 | 0.18 | 0.36 |
| index | 5 | 1.84 | 0.72 | +154.5% | 2503.9 | 5705.1 | 0.48 | 1.10 |
| index | 10 | 2.96 | 0.85 | +249.4% | 2930.8 | 8933.6 | 0.56 | 1.72 |
| large | 1 | 2.88 | 2.37 | +21.4% | 332.3 | 403.0 | 2658.65 | 3224.14 |
| large | 5 | 5.84 | 3.70 | +57.8% | 785.7 | 1193.5 | 6285.64 | 9548.31 |
| large | 10 | 12.20 | 5.68 | +114.9% | 743.1 | 1486.1 | 5945.13 | 11888.69 |

`mean` is the mean per-request latency; request and byte rates are measured by the load generator itself (`app/client.py --bench`), not from process start-up time.

### Why the numbers look like this

The proxy adds one extra TCP hop and per-request parsing, policy evaluation and
logging. For small responses (`index`, about 24 bytes) that fixed work is a large
share of the total, so latency rises by about +107% to +196%. For large
responses (1 MB), the transfer itself dominates, so the relative latency cost is
only about +10% to +65%.

Throughput is lower through the proxy for the same reason: every byte and every
request passes through an extra process and connection. The gap does not grow
steadily with client count because the proxy handles each connection in its own
thread; it reflects the extra hop, not a single-connection bottleneck.

## Policy change activation time

`--policy-timing` writes `results/policy_change.csv` with one row per
`BLOCK`/`ALLOW` call (`call,action,ms`). Over 20 pairs (40 measurements):

| Metric | Value |
|---|---|
| mean | 0.96 ms |
| p95 | 1.10 ms |
| max | 1.20 ms |

The reported value starts when the proxy receives the control command and ends
after the controller acknowledges the flow mod; it includes the atomic policy
file write and the unix-socket round trip. `results/plot.py` also produces the
time series and histogram in `results/policy_change.png`.

## Localhost benchmark (pipeline check only)

`tests/local_benchmark.py` produces real numbers, but there is no switch and
"direct" connects straight to the service. It only checks the client JSON
protocol, aggregation and plotting; **it is not a substitute for the Mininet
study and must not be presented as the project's performance result.** The data
is kept in `results/localhost/` for reproducibility.

## Reproduce the results

On the Ubuntu machine, from the project root, with Ryu running in `~/ryu-env`:

```bash
git checkout -- config/policy.json
sudo mn -c
sudo python3 topology/topo.py --test basic
sudo python3 topology/topo.py --test multi
sudo python3 topology/topo.py --hard
sudo python3 topology/topo.py --bench proxy
sudo python3 topology/topo.py --bench direct
sudo python3 topology/topo.py --policy-timing --cycles 20
sudo chown -R $USER:$USER results
python3 results/plot.py
```

Then compare the reports:

```bash
python3 tests/check_expected.py results/mininet_basic.txt tests/expected/mininet_basic.txt
python3 tests/check_expected.py results/mininet_multi.txt tests/expected/mininet_multi.txt
python3 tests/check_expected.py results/mininet_hard.txt tests/expected/mininet_hard.txt
python3 tests/check_expected.py results/mininet_policy_timing.txt tests/expected/mininet_policy_timing.txt
```

The policy-timing check assumes the default `--cycles 20`. The evidence
checklist is in `docs/testing.md`.

## Rubric mapping

| Rubric item | Where |
|---|---|
| Sockets | `app/proxy.py` (thread per client, relay, malformed/slow/down handling), local smoke |
| Mininet + SDN | `topology/topo.py`, `controller/filter_controller.py`, `--test basic` |
| Socket-SDN integration | `sync()`, controller protocol, `--test basic` dynamic checks |
| Dynamic SDN (6 marks) | automatic malformed/rate block + dynamic drop rules + re-sync on controller restart |
| Challenging scenario | `--hard`: bypass, flood, mid-transfer policy change, proxy crash |
| Performance (5 marks) | `--bench`, `--policy-timing`, `results/plot.py` |
| Docs and viva (6 marks) | `docs/` and `README.md` |

## Known limitations

* One switch and one controller: no controller redundancy or multi-switch fabric.
* Automatic blocks are temporary and in memory; they are not saved across a
  proxy restart.
* A policy change cuts an in-flight transfer to a blocked service; new requests
  are denied immediately.
* Automatic block thresholds are tuned for a lab (`5` malformed / 10 s,
  `200` requests / 1 s); production values should be higher.
