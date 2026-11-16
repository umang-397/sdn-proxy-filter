# Testing

## 1. Local tests (no Mininet, run anywhere)

### Policy unit tests

```bash
python3 tests/test_policy.py
```

6 tests: default, first-match precedence, keyword, runtime block/allow,
auto-block precedence + expiry, auto-block not persisted. Expected: `OK`.

### End-to-end localhost smoke test

```bash
python3 tests/local_smoke.py | tee results/local_smoke.txt
python3 tests/check_expected.py results/local_smoke.txt \
    tests/expected/local_smoke.txt
```

The test starts two services, the proxy, and a fake controller, then runs 24
checks. Expected output is committed as `tests/expected/local_smoke.txt`; the
last line is `FAILED: 0`.

Covered:

* allowed data, keyword deny, malformed request, unknown service,
* 1 MB response integrity,
* `BLOCK files` returns `BLOCKED`, controller receives `DROP`,
* new controller boot id -> proxy re-sends drop rules,
* block survives proxy restart, counters survive proxy restart,
* `ALLOW` restores service, counters non-zero,
* malformed flood -> automatic block + switch drop,
* legitimate request denied while auto-blocked, `UNBLOCK` restores it,
* request-rate flood -> automatic block,
* service down -> `ERROR service unavailable`,
* log contains permit and block lines.

On Linux the fake controller uses `AF_UNIX`; on Windows (no `AF_UNIX` in
Python) it uses `controller_tcp`. The proxy code path is the same.

## 2. Mininet acceptance tests

Prerequisites: controller running, `sudo mn -c`, policy reset
(`git checkout -- config/policy.json`). Each command is a separate run. The
scripted modes exit automatically; add `--cli` to keep the Mininet prompt open
for inspection.

```bash
sudo python3 topology/topo.py --test basic
python3 tests/check_expected.py results/mininet_basic.txt \
    tests/expected/mininet_basic.txt
```

15 checks, expected output in `tests/expected/mininet_basic.txt`:

| Check | What it proves |
|---|---|
| allowed request returns data | proxy path works |
| direct bypass fails at the switch | controller default drop works |
| blocked request gets BLOCKED | saved policy (c2 denied files) |
| keyword rule blocks | `secret` keyword |
| log shows both permit and block lines | evidence for the report |
| default drop flow is installed | priority 0 |
| allowed client-to-proxy flow is installed | priority 100 |
| dynamic BLOCK takes effect in the proxy | runtime rule |
| dynamic drop rule reaches the switch | priority 200 |
| dynamic ALLOW restores service | rule removal |
| malformed flood is detected | auto-block counter |
| flooding client is auto-blocked | STATS active block |
| switch drop is installed for the flooding client | network response |
| legitimate client keeps working during the flood | c3 is unaffected |
| client works again after UNBLOCK | recovery |

### Multi-client test

```bash
sudo python3 topology/topo.py --test multi
python3 tests/check_expected.py results/mininet_multi.txt \
    tests/expected/mininet_multi.txt
```

12 checks with c1, c2 and c3 running concurrently:

* baseline: c1 web allowed, c2 files denied, c3 files allowed,
* live `BLOCK files`: c3 also blocked while c1/c2 web traffic keeps working,
* live `BLOCKCLIENT 10.0.0.1`: c1 cut off while c2/c3 keep working,
* `dump-flows` contains both dynamic drop rules; saved to
  `results/evidence/dumpflows_multi_*.txt`.

## 3. Hard scenarios

```bash
sudo python3 topology/topo.py --hard
python3 tests/check_expected.py results/mininet_hard.txt \
    tests/expected/mininet_hard.txt
```

| Scenario | What the test does | Recorded evidence |
|---|---|---|
| Bypass | c1 connects to `10.0.0.21:8001` three times; c3 uses the proxy | `hard_bypass.txt`, FAILED output |
| Malformed flood | c1 sends 20 malformed lines; thresholds are 5 / 10 s | `hard_flood.txt`, auto-block in STATS, `dumpflows_hard_flood.txt` |
| Legit client during attack | c3 requests `web/index` while c1 is blocked | PASS/FAIL + log |
| Policy change mid-transfer | c1 downloads 1 MB `web/slow` over ~1 s; `BLOCK web` is issued after 0.3 s; then a new request is checked | `hard_policy_change.txt`, `dumpflows_*.txt` |
| Proxy crash | `pkill` proxy, request must fail, restart, request must work | `proxy_hard.log`, STATS before/after |
| Persistence | files are blocked before the crash; the drop must be re-synced after restart | `dumpflows_hard_after.txt` |

The mid-transfer case shows the interaction between layers:

* the in-flight connection may end with a partial body or a timeout because the
  priority-200 `proxy -> web` rule cuts the established flow,
* every new request is denied by the proxy immediately (`BLOCKED rule 1`),
* c3 is also affected while the service is globally blocked (expected),
* `ALLOW web` restores both the proxy decision and the switch path.

### Controller / switch restart check (manual, plan point 4)

In an interactive run (`sudo python3 topology/topo.py`), with the Ryu controller
running in another terminal:

```bash
proxy python3 app/ctl.py BLOCK files
sh ovs-ofctl -O OpenFlow13 dump-flows s1       # priority=200 proxy -> files
# stop Ryu (Ctrl-C), start it again, wait ~2 s (proxy PING interval)
sh ovs-ofctl -O OpenFlow13 dump-flows s1       # rule is re-pushed
proxy python3 app/ctl.py ALLOW files
```

To test the switch-reconnect path, delete the controller from the switch and
set it again:

```bash
sh ovs-vsctl del-controller s1
sh ovs-vsctl set-controller s1 tcp:127.0.0.1:6653
sh ovs-ofctl -O OpenFlow13 dump-flows s1       # default + dynamic rules return
```

Record the terminal transcript/screenshot in `results/screenshots/` and the
before/after dumps in `results/evidence/`.

## 4. Performance run

```bash
sudo python3 topology/topo.py --bench proxy
sudo python3 topology/topo.py --bench direct
sudo python3 topology/topo.py --policy-timing --cycles 20
python3 results/plot.py
```

The benchmark runs 5 repetitions of 1/5/10 client processes for `index` and
`large` responses. `client.py --bench` measures per-request latency and
throughput in-process; `topo.py` aggregates the JSON lines. Expected files:
`results/benchmark_proxy.csv`, `benchmark_proxy_summary.csv`,
`benchmark_direct.csv`, `benchmark_direct_summary.csv`, `policy_change.csv`,
plus `latency.png`, `throughput.png`, `policy_change.png`, `summary.md`.

`--policy-timing` alternates 20 `BLOCK web` / `ALLOW web` commands and records
the proxy-reported activation time (policy write + controller round trip).

## 5. Fresh-clone reproducibility check

```bash
git clone <repository> /tmp/sdn-proxy-fresh
cd /tmp/sdn-proxy-fresh
python3 tests/test_policy.py
python3 tests/local_smoke.py
sudo mn -c
# controller in another terminal, then:
sudo python3 topology/topo.py --test basic
```

The only environment-specific step is the eventlet pin for Ryu on newer
Python versions (`pip3 install eventlet==0.30.2`).

## 6. Evidence checklist

`results/` should contain:

* `local_smoke.txt`, `test_policy.txt` (or terminal screenshots),
* `mininet_basic.txt`, `mininet_multi.txt`, `mininet_hard.txt`,
  `mininet_policy_timing.txt`,
* benchmark CSVs + summary,
* `latency.png`, `throughput.png`, `policy_change.png`, `summary.md`,
* `evidence/dumpflows_*.txt`, `evidence/proxy_*.log`, `evidence/hard_*.txt`,
* `screenshots/` for terminal screenshots.
