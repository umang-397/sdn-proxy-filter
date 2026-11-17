# Proxy and Content Filtering System (TCP + SDN)

Clients reach simulated services only through a concurrent TCP proxy. The proxy
allows/blocks requests by policy; the Ryu controller (OpenFlow 1.3) drops direct
client-to-service traffic in the switch and installs extra drop rules when the
policy changes at runtime or when a client starts flooding the proxy.

```
          +----------------------------- application layer -----------------------------+
          |                                                                             |
 c1 c2 c3 |---- TCP :8080 ----> [ proxy 10.0.0.10 ] ---- TCP ----> web :8001           |
          |                         |        |                    files :8002           |
          +-------------------------|--------|-----------------------------------------+
                                    |        |  unix socket /tmp/sdn_ctrl.sock
                                    |        +-----> [ Ryu controller :6653 ]
                                    |                         |
                                    +---- OpenFlow 1.3 ------+----> [ OVS s1 ]
                                                                  (default: only
                                                                   client<->proxy
                                                                   and proxy<->service)
```

Two enforcement points, on purpose:

* **Proxy (application layer)** understands `GET service/resource`, keywords and
  per-client rules, and logs every decision.
* **Switch/controller (network layer)** makes the proxy the only path to the
  services, so a client cannot bypass policy by connecting to `10.0.0.21:8001`
  directly. It also enforces automatic blocks during a flood before traffic
  reaches the proxy.

## Layout

```
app/        proxy.py service.py client.py ctl.py policy.py
controller/ filter_controller.py (Ryu, OpenFlow 1.3)
topology/   topo.py (Mininet, scenarios, benchmark)
config/     network.json (addresses, auto-block, transport) + policy.json
tests/      local tests, Mininet test driver, expected outputs, flood helper
results/    plot.py, evidence, benchmark output, screenshots
docs/       architecture, implementation, testing, results, viva notes
logs/       runtime logs (git-ignored)
```

## Setup (Ubuntu 20.04/22.04)

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip netcat-openbsd
pip3 install -r requirements.txt
# If Ryu fails on import with newer Python/eventlet:
pip3 install eventlet==0.30.2
```

Mininet does not run on macOS or native Windows. Use an Ubuntu VM for every
`topology/topo.py` command.

## Quick checks without Mininet

```bash
python3 tests/test_policy.py       # 6 unit tests, expect OK
python3 tests/local_smoke.py       # 24 checks, expect FAILED: 0
python3 tests/local_smoke.py | tee results/local_smoke.txt
python3 tests/check_expected.py results/local_smoke.txt tests/expected/local_smoke.txt
```

The local smoke test uses a fake controller over the same control protocol. On
Linux it uses the unix socket; on systems without `AF_UNIX` it automatically
uses the `controller_tcp` transport from `config/network.json`.

## Run with Mininet

Terminal 1 (controller, from the project root):

```bash
ryu-manager --ofp-tcp-listen-port 6653 controller/filter_controller.py
```

Terminal 2 (network, services and proxy):

```bash
sudo mn -c
sudo python3 topology/topo.py            # interactive mininet>
```

Examples inside `mininet>`:

```bash
c1 python3 app/client.py --req "GET web/index"                       # allowed
c1 python3 app/client.py --host 10.0.0.21 --port 8001 --req "GET /x" --timeout 3
                                                                     # bypass fails
c2 python3 app/client.py --req "GET files/index"                    # denied (policy)
proxy python3 app/ctl.py BLOCK web                                  # live change
proxy python3 app/ctl.py ALLOW web
proxy python3 app/ctl.py BLOCKCLIENT 10.0.0.1
proxy python3 app/ctl.py UNBLOCK 10.0.0.1
proxy python3 app/ctl.py STATS
sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

Runtime changes are written to `config/policy.json` (first match wins) and
pushed to the controller over `/tmp/sdn_ctrl.sock`. If the controller restarts,
the proxy notices the new boot id and re-pushes every drop rule. If the switch
reconnects, the controller re-installs its known drop rules.

Before a fresh demo/test run, reset the saved policy so the expected output is
reproducible:

```bash
git checkout -- config/policy.json
```

## Scripted scenarios

Each command must be a separate run (restart the controller and run `sudo mn -c`
between runs). Scripted modes run and exit automatically; add `--cli` if you
want to inspect the network afterwards:

```bash
sudo python3 topology/topo.py --demo                     # multi-client policy demo
sudo python3 topology/topo.py --test basic               # acceptance tests
sudo python3 topology/topo.py --test multi               # multi-client checks
sudo python3 topology/topo.py --hard                     # bypass/flood/policy/crash
sudo python3 topology/topo.py --policy-timing --cycles 20
sudo python3 topology/topo.py --test basic --cli         # keep the CLI open
```

Reports land in `results/mininet_basic.txt`, `mininet_multi.txt`,
`mininet_hard.txt` and `mininet_policy_timing.txt`. Compare them with the
committed expected output:

```bash
python3 tests/check_expected.py results/mininet_basic.txt tests/expected/mininet_basic.txt
python3 tests/check_expected.py results/mininet_multi.txt tests/expected/mininet_multi.txt
python3 tests/check_expected.py results/mininet_hard.txt tests/expected/mininet_hard.txt
python3 tests/check_expected.py results/mininet_policy_timing.txt tests/expected/mininet_policy_timing.txt
```

The policy-timing comparison assumes the default `--cycles 20` (40 measurements).

`--test basic` covers: allowed data, switch-level bypass failure, policy and
keyword blocks, permit/block logging, default and dynamic flows, and the
malformed-flood automatic block with a legitimate client (c3) still working.
`--hard` also covers a policy change in the middle of a slow 1 MB transfer and
a proxy crash/restart with STATS persistence and drop-rule re-sync.

## Automatic blocking

`config/network.json` controls the response to abuse:

```json
"auto_block": {
  "malformed_threshold": 5,
  "malformed_window_s": 10.0,
  "rate_threshold": 200,
  "rate_window_s": 1.0,
  "block_seconds": 30
}
```

A client that sends 5 malformed requests in 10 s, or 200 requests in 1 s, is
blocked by the proxy and gets a priority-200 drop rule in the switch
(client -> proxy). The block expires automatically, or can be removed with
`ctl.py UNBLOCK <ip>`. Automatic blocks are deliberately not saved to
`config/policy.json`; they are temporary. Automatic blocking is disabled during
performance runs (`topo.py --bench`) so legitimate load is not throttled.

## Performance study

The benchmark uses the load generator's own JSON measurements, not process
start-up time and not truncated console output:

```bash
# 1, 5 and 10 concurrent clients, index and 1 MB responses,
# 5 repetitions, 5 requests per client per batch
sudo python3 topology/topo.py --bench proxy
sudo python3 topology/topo.py --bench direct
```

The direct baseline is produced by the same topology script: it temporarily
adds priority-150 flows in both directions between each client and web, runs
the baseline, then removes them. There is no second controller or
`simple_switch_13` step.

Outputs:

* `results/benchmark_proxy.csv`, `results/benchmark_proxy_summary.csv`
* `results/benchmark_direct.csv`, `results/benchmark_direct_summary.csv`
* `results/policy_change.csv` from `--policy-timing`

Graphs and the summary table:

```bash
python3 results/plot.py
# -> results/latency.png, results/throughput.png,
#    results/policy_change.png, results/summary.md
```

A localhost-only pipeline check (real data, but no switch/Mininet) is available:

```bash
python3 tests/local_benchmark.py
python3 results/plot.py --dir results/localhost --out results/localhost
```

Use the Mininet numbers in the report and viva, not the localhost sanity data.

## Request format and policy

Request: `GET <service>/<resource>`. Replies: data, `BLOCKED <rule>`, or
`ERROR <why>`. Policy rules are checked top to bottom and the first match wins:
`client` (IP or `*`), `service` (name or `*`), `keyword` (substring or null),
`action` (`allow`/`deny`); otherwise `default` applies. Runtime commands are
`BLOCK`, `ALLOW`, `BLOCKCLIENT`, `ALLOWCLIENT`, `UNBLOCK`, `RELOAD`, `SHOW`,
`STATS` and `SYNC`.

Controller priorities: `200` dynamic drop, `100` allowed pair/ARP, `0` default
drop.

## Docs and evidence

* `docs/architecture.md` - diagram and why both enforcement points are needed
* `docs/implementation.md` - request flow, policy precedence, controller sync
* `docs/testing.md` - local and Mininet tests, hard scenarios, reproduction
* `docs/results.md` - what was measured and how to regenerate it
* `docs/viva.md` - likely viva questions and answers
* `results/` - CSV data, plots, `dump-flows` snapshots, proxy logs, screenshots

## Team

* UMANG VIJAY: proxy/services/client (`app/`)
* SHREYAS ARUN: controller + topology
* SUMANTH MANJUNATH SHASTRI: tests/, results/, STP, viva point of contact
