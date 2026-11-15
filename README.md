# Proxy and Content Filtering System (TCP + SDN)

Clients reach simulated services only through a concurrent TCP proxy. The proxy
allows/blocks requests by policy; the Ryu controller (OpenFlow 1.3) drops direct
client-to-service traffic in the switch and installs extra drop rules when the
policy changes at runtime.

    c1 c2 c3 ----+
    proxy -------+---- s1 (OVS, OF1.3) ---- Ryu controller (6653)
    web, files --+          ^
                            +-- proxy tells controller via unix socket /tmp/sdn_ctrl.sock

## Layout
topology/ Mininet script | controller/ Ryu app | app/ proxy, service, client, ctl, policy
config/ network + policy JSON | tests/ | results/ | docs/ | logs/

## Setup (Ubuntu 20.04+)
    sudo apt update && sudo apt install -y mininet openvswitch-switch python3-pip netcat-openbsd
    pip3 install ryu matplotlib

## Quick check without Mininet
    python3 tests/test_policy.py
    python3 tests/local_smoke.py        # expect: FAILED: 0

## Run (exact steps)
Terminal 1 (controller):
    cd sdn-proxy-filter
    ryu-manager --ofp-tcp-listen-port 6653 controller/filter_controller.py
Terminal 2 (topology, starts services + proxy):
    sudo mn -c
    sudo python3 topology/topo.py            # interactive, opens mininet>
Examples inside mininet>:
    c1 python3 app/client.py --req "GET web/index"                       # allowed
    c1 python3 app/client.py --host 10.0.0.21 --port 8001 --req "GET /x" --timeout 3   # bypass: fails
    proxy python3 app/ctl.py BLOCK web         # live policy change
    proxy python3 app/ctl.py ALLOW web
    proxy python3 app/ctl.py STATS
    sh ovs-ofctl -O OpenFlow13 dump-flows s1
Scripted scenarios (one run each, then restart controller+mn -c):
    sudo python3 topology/topo.py --demo
    sudo python3 topology/topo.py --hard

## Performance study
Proxy run: start filter_controller, then
    sudo python3 topology/topo.py --bench proxy
Baseline (direct, no filtering): stop it, start
    ryu-manager --ofp-tcp-listen-port 6653 ryu.app.simple_switch_13
    sudo mn -c && sudo python3 topology/topo.py --bench direct
Graphs: python3 results/plot.py  -> results/latency.png, throughput.png
Policy-change time is printed by `ctl.py BLOCK ...` ("policy active after X ms").

## Request format / policy
Request: `GET <service>/<resource>`. Replies: data, `BLOCKED <rule>`, `ERROR <why>`.
Policy (config/policy.json): rules checked top to bottom, first match wins;
fields client (IP or *), service (name or *), keyword, action; else "default".
Controller default rules: clients->proxy, proxy->services/clients, services->proxy,
everything else dropped. Dynamic: BLOCK <svc> => drop proxy->svc; BLOCKCLIENT <ip> => drop ip->proxy.

## Team
UMANG VIJAY: proxy/services/client (app/)   SHREYAS ARUN: controller + topology
SUMANTH MANJUNATH SHASTRI: tests/, results/, STP, viva point of contact
