# Viva preparation

## 1. Why both a proxy and an SDN controller?

They enforce different things. The proxy understands the application request
(`GET service/resource`), so it can apply keyword/client/service policy and log
every permit/block. The switch cannot read that. The switch can stop a client
from bypassing the proxy by connecting directly to a service, which the proxy
cannot prevent. Together: app-layer policy + network-layer enforcement.

## 2. How does a request flow?

`c1 -> s1 (priority 100 pair) -> proxy:8080 -> policy -> service:800x -> proxy
-> c1`. A direct `c1 -> service` packet has no priority-100 pair and is dropped
by the priority-0 default rule.

## 3. How does first-match precedence work?

Rules are ordered. For each request, the proxy compares source IP, service and
optional keyword substring, starting at the top. The first full match decides;
if none match, `default` applies. Runtime `BLOCK` inserts at the front, so it
overrides existing allow rules; `ALLOW` removes that exact rule.

Example: c2 is denied `files` by rule 1, so c2's `files` request is denied even
though the default is allow. A keyword rule `secret` denies `web/secret-plan`
but not `web/index`.

## 4. What exactly is installed in the switch?

* priority 200: dynamic `ip nw_src=X nw_dst=Y` drop (policy or auto-block),
* priority 100: ARP NORMAL, allowed client↔proxy and proxy↔service pairs,
* priority 0: drop everything else.

The controller uses `OFPFC_DELETE_STRICT` at priority 200 to remove a dynamic
rule. Dynamic rules are re-installed on switch reconnect.

## 5. What happens when the controller restarts?

The proxy pings the controller every `sync_interval_s`; the reply contains a
boot id. A new boot id means the controller lost its dynamic table, so the proxy
clears its `synced` set and re-pushes all desired drops. If the switch
reconnects to the same controller, `EventOFPSwitchFeatures` re-installs the
controller's known `dynamic_drops`.

## 6. What happens when the proxy restarts?

It loads counters from `logs/stats.json`, sends `CLEAR` to remove stale dynamic
rules, then re-pushes the policy. The saved policy (including manual blocks)
survives; automatic blocks do not (they are temporary and are not saved).

## 7. How does the automatic block work?

Two sliding windows per source IP: 5 malformed requests in 10 s or 200 requests
in 1 s. Crossing either installs a memory-only deny + a priority-200
client→proxy drop, so the flood is stopped at the switch. It expires after
30 s, or `ctl.py UNBLOCK <ip>` clears it (and the burst counters, so the next
request is not immediately re-blocked).

## 8. Why is the benchmark trustworthy?

`client.py --bench` measures the request loop inside the process and emits
JSON with per-request latencies, bytes, duration and errors. `topo.py`
aggregates those JSON lines across 1/5/10 client processes and 5 repetitions.
It does not time `python3` start-up and does not parse the 120-character
console reply. The direct baseline uses temporary priority-150 flows from the
same script, so the only difference is the proxy hop.

## 9. What do the performance results mean?

Latency increases because every request passes through one extra process and
TCP connection; throughput drops for the same reason and because policy/logging
run per request. Large responses are dominated by data transfer, so the
relative overhead is smaller than for small responses. Real numbers must come
from the Mininet VM; the repo's `results/localhost/` is only a pipeline check.

## 10. How do you know blocked content stays blocked?

Three independent checks: the proxy returns `BLOCKED`, the switch has a
priority-200 drop for the service/client pair, and a direct bypass to the
service still fails. The hard scenario repeats the check while a legitimate
client (c3) keeps using the proxy.

## 11. What did you do for the challenging scenarios?

* bypass from c1 to the web port: times out at the switch,
* malformed flood from c1: auto-block + switch drop, c3 unaffected,
* policy change during a 1 MB slow transfer: established flow is cut by the
  priority-200 rule; new requests are blocked at the proxy,
* proxy crash/restart: requests fail during the outage, then work again;
  counters persist and dynamic drops are re-synced.

## 12. Why is STP not in the running topology?

The topology is a single switch with hosts attached, so there are no Layer-2
loops and no need for STP. The concept was studied for the report; adding a
second switch with a redundant link would require STP/loop prevention, but it
would not change the filtering design. If asked: OVS enables STP per bridge,
but with one switch it is unnecessary.

## 13. What are the main concurrency risks?

Multiple client threads share the policy, counters, log and controller view.
Locks protect each structure; the controller sync lock is held around
compute-and-send so two threads cannot push contradictory drop sets. The log is
appended line by line under a lock. A slow client/service blocks only its own
thread because sockets have timeouts.

## 14. What would you improve next?

* persistent controller state or an explicit reconciliation version,
* IPv6 and hostname resolution,
* TLS on the management channel,
* per-user identities instead of source IP,
* a real HTTP parser/header policy,
* smarter rate limiting (token bucket plus penalties).
