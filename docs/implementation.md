# Implementation notes

## Files

| File | Responsibility |
|---|---|
| `app/proxy.py` | concurrent TCP proxy, logging/counters, controller sync, automatic blocking |
| `app/policy.py` | first-match policy table, runtime rules, temporary auto-blocks |
| `app/service.py` | simulated web/files service; 1 MB `large`; 1 s `slow` for mid-transfer tests |
| `app/client.py` | one request or `--bench` load generator with JSON output |
| `app/ctl.py` | control client; port read from `config/network.json` |
| `controller/filter_controller.py` | Ryu app: default pairs, dynamic drops, reconnect re-install |
| `topology/topo.py` | Mininet topology, demo/tests/hard/benchmark/timing modes |
| `tests/flood.py` | malformed or valid request flood helper |

## Proxy

### Concurrency

One thread per client connection. Shared state is protected by:

* `stats_lock` for counters and `logs/stats.json`,
* `log_lock` for the CSV log,
* `sync_lock` (`RLock`) for the controller view,
* `ab_lock` for per-client rate/fault deques,
* `Policy.lock` (`RLock`) for rules and auto-blocks.

A slow client only blocks its own thread (5 s socket timeout). A slow service
only blocks the client's thread (3 s connect, 10 s read). New clients are
accepted by the main thread.

### Request handling

```
auto-block active? -> BLOCKED <auto-block reason>
rate limit crossed? -> install auto-block, BLOCKED
read one line <= 1024 bytes
parse GET service/resource (regex)
bad line -> count malformed; maybe auto-block; else ERROR malformed request
policy deny -> BLOCKED <rule n / default / auto-block>
unknown service -> ERROR unknown service
service connect fails -> ERROR service unavailable
else relay response bytes, log permit
```

Every decision writes
`time,client,service,resource,action,reason` to `logs/proxy.log`.

### Automatic blocking

Two sliding windows per source IP:

* malformed requests: default 5 in 10 s,
* all requests: default 200 in 1 s.

The first request that reaches a threshold installs an automatic block for
`block_seconds` (default 30). The proxy answers `BLOCKED auto-block: ...`,
increments `auto_blocks`, logs an `auto-block` event, and pushes
`DROP <client> <proxy>` to the controller. When the block expires (or
`UNBLOCK` is used), the proxy sends `ALLOW`, and it also clears the client's
counters so the next request is not immediately blocked again.

Automatic blocks live only in memory. They are not written to
`config/policy.json`, so a restart does not leave a client permanently banned.

### Statistics persistence

`stats.json` is updated atomically (`tmp` + `os.replace`) after every counted
decision. It contains `permitted`, `blocked`, `errors`, `auto_blocks`; active
automatic blocks are added to the `STATS` reply at query time. A proxy restart
therefore keeps the totals.

### Controller protocol

Transport: unix socket `controller_sock`, or TCP `controller_tcp` when set
(used by local tests on systems without `AF_UNIX`).

| Command | Meaning |
|---|---|
| `DROP <src> <dst>` | install priority-200 drop |
| `ALLOW <src> <dst>` | remove it |
| `CLEAR` | remove every dynamic drop |
| `PING` | return `OK <boot-id>` |

`sync()` computes the desired set from the policy:

* service-wide deny -> `(proxy_ip, service_ip)`,
* client-wide deny -> `(client_ip, proxy_ip)`,
* active automatic block -> `(client_ip, proxy_ip)`.

Only differences from the `synced` set are sent, and a rule is added to
`synced` only after an `OK` reply. A maintenance thread runs every
`sync_interval_s` (default 2 s): it expires blocks, pings the controller,
detects a new boot id, and retries any mismatch. That makes startup order
(controller before/after proxy) and controller restarts converge without
manual intervention.

## Policy

Rules are a JSON list; the first match wins. Runtime commands insert at the
front, so a new `BLOCK` overrides older rules, and `ALLOW` removes the exact
generated rule. The file is replaced atomically. If the file is edited by hand,
the next request notices the mtime change and reloads it (then re-syncs).

## Controller

* Reads `config/network.json` (override with `SDN_NETWORK_CONFIG`).
* Builds allowed pairs from clients, proxy and services.
* Uses `OFPFC_DELETE_STRICT` at priority 200 for removal.
* On `EventOFPSwitchFeatures`, installs defaults and re-installs every tracked
  dynamic drop.
* The socket server is a daemon thread; a lock protects `datapaths` and
  `dynamic_drops` from concurrent socket/OFP events.
* `CLEAR` removes every tracked drop from every connected switch and clears the
  set; the proxy calls it at startup to avoid stale rules.

## Benchmark methodology

`client.py --bench` measures the loop in-process and prints a `BENCHJSON` line:

```
label, concurrency, reps, requests, ok, errors, bytes,
duration_s, mean_ms, p95_ms, latencies_ms[]
```

`topo.py` launches 1, 5 or 10 client processes (spread over c1-c3), waits for
all of them, and aggregates across processes:

* latency: mean/p95 over all request samples,
* request rate: total successful requests / longest client duration,
* byte rate: total bytes × 8 / longest client duration / 1e6.

Process start-up and console truncation are therefore excluded. The benchmark
runs proxy and direct modes with the same client code. `--no-auto-block` is
passed to the proxy for benchmark runs so legitimate load is not detected as an
attack.

The direct baseline adds temporary priority-150 flows in both directions
(`client <-> 10.0.0.21`) with the `NORMAL` action, then removes them. Both
directions are required, otherwise the response hits the controller's
priority-0 drop. This is the one chosen baseline method; it does not use a
second controller or `simple_switch_13`.

## Configuration reference

`config/network.json`:

* `controller_sock` / `controller_tcp`
* `clients` name -> IP
* `proxy.ip`, `proxy.port`, `proxy.control_port`
* `proxy.stats_file`, `proxy.sync_interval_s`
* `proxy.auto_block.*`
* `services` name -> `{ip, port}`

`config/policy.json`: `default` and ordered `rules`.
