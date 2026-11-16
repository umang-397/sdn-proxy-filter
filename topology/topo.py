#!/usr/bin/env python3
"""Mininet topology, scenario runner and benchmark for the SDN proxy project.

Modes (choose one):
    sudo python3 topology/topo.py                 interactive CLI
    sudo python3 topology/topo.py --demo          multi-client policy change demo
    sudo python3 topology/topo.py --test basic    scripted acceptance tests
    sudo python3 topology/topo.py --test multi    multi-client policy test
    sudo python3 topology/topo.py --hard          bypass/flood/policy/crash tests
    sudo python3 topology/topo.py --policy-timing 20 BLOCK/ALLOW measurements
    sudo python3 topology/topo.py --bench proxy   1/5/10 clients, 5 repetitions
    sudo python3 topology/topo.py --bench direct  same, with a temporary bypass

Every scripted mode writes evidence to results/ and prints PASS/FAIL lines.
Benchmarks use app/client.py --bench JSON output, never process start-up time.
"""
import argparse
import csv
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(PROJECT_DIR, "config", "network.json")) as _f:
    CFG = json.load(_f)

CLIENT_NAMES = list(CFG["clients"].keys())
PROXY_IP = CFG["proxy"]["ip"]
PROXY_PORT = int(CFG["proxy"]["port"])
CTL_PORT = int(CFG["proxy"].get("control_port", 9000))
SERVICES = CFG["services"]
WEB_IP = SERVICES["web"]["ip"]
WEB_PORT = int(SERVICES["web"]["port"])
FILES_IP = SERVICES["files"]["ip"]
FILES_PORT = int(SERVICES["files"]["port"])

CHECKS = []


# ---------------------------------------------------------
# NETWORK TOPOLOGY
# ---------------------------------------------------------

class ProxyFilterTopo(Topo):

    def build(self):
        s1 = self.addSwitch("s1", protocols="OpenFlow13")

        hosts = []
        for name, ip in CFG["clients"].items():
            hosts.append(self.addHost(name, ip=ip + "/24"))
        hosts.append(self.addHost("proxy", ip=PROXY_IP + "/24"))
        for name, svc in SERVICES.items():
            hosts.append(self.addHost(name, ip=svc["ip"] + "/24"))

        for host in hosts:
            self.addLink(host, s1)


# ---------------------------------------------------------
# APPLICATION STARTUP
# ---------------------------------------------------------

def _run_background(host, command, log):
    host.cmd("cd %s && %s > %s 2>&1 &" % (PROJECT_DIR, command, log))


def start_proxy(proxy, auto_block=True):
    extra = "" if auto_block else " --no-auto-block"
    _run_background(
        proxy,
        "python3 app/proxy.py --config config/network.json "
        "--policy config/policy.json --log logs/proxy.log "
        "--port %d --ctl-port %d%s"
        % (PROXY_PORT, CTL_PORT, extra),
        # Keep structured proxy.log separate from the interpreter output.
        "logs/proxy_stdout.log"
    )


def start_applications(net, auto_block=True):
    os.makedirs(os.path.join(PROJECT_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(PROJECT_DIR, "results", "evidence"),
                exist_ok=True)

    for name, svc in SERVICES.items():
        info("\n*** Starting %s service\n" % name)
        _run_background(
            net.get(name),
            "python3 app/service.py --name %s --port %d"
            % (name, int(svc["port"])),
            "logs/%s.log" % name
        )

    info("*** Starting TCP proxy\n")
    start_proxy(net.get("proxy"), auto_block=auto_block)

    time.sleep(2)
    info("*** Applications started\n")


def run_client(host, request, direct=False, timeout=5):
    if direct:
        target = "--host %s --port %d" % (WEB_IP, WEB_PORT)
    else:
        target = ""
    command = (
        "cd %s && python3 app/client.py %s --req '%s' --timeout %s"
        % (PROJECT_DIR, target, request, timeout)
    )
    return host.cmd(command)


def control_command(proxy, command):
    return proxy.cmd(
        "cd %s && python3 app/ctl.py --config config/network.json %s"
        % (PROJECT_DIR, command)
    )


def proxy_stats(proxy):
    raw = control_command(proxy, "STATS")
    try:
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except (ValueError, IndexError):
        return {}


def dumpflows(net):
    return net.get("s1").cmd("ovs-ofctl -O OpenFlow13 dump-flows s1")


def has_flow(flows, priority, src, dst):
    for line in flows.splitlines():
        if ("priority=%d" % priority) in line \
                and ("nw_src=%s" % src) in line \
                and ("nw_dst=%s" % dst) in line:
            return True
    return False


def blockedish(output):
    text = output.strip().upper()
    return (text.startswith("BLOCKED")
            or text.startswith("FAILED")
            or text.startswith("ERROR SERVICE UNAVAILABLE"))


def _int(text):
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else 0


def save_text(name, text):
    folder = os.path.join(PROJECT_DIR, "results", "evidence")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.write("# %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    info("*** Evidence saved to %s\n" % path)


def save_dumpflows(net, name):
    save_text("dumpflows_%s.txt" % name, dumpflows(net))


def save_proxy_log(name):
    source = os.path.join(PROJECT_DIR, "logs", "proxy.log")
    if not os.path.exists(source):
        return
    folder = os.path.join(PROJECT_DIR, "results", "evidence")
    os.makedirs(folder, exist_ok=True)
    shutil.copy2(source, os.path.join(folder, "proxy_%s.log" % name))


def check(name, condition, detail=""):
    ok = bool(condition)
    CHECKS.append((name, ok))
    if ok:
        info("PASS %s\n" % name)
    else:
        info("FAIL %s%s\n" % (name, (" :: " + str(detail)) if detail else ""))
    return ok


def report(name):
    folder = os.path.join(PROJECT_DIR, "results")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    fails = sum(1 for _, ok in CHECKS if not ok)
    with open(path, "w") as f:
        for check_name, ok in CHECKS:
            f.write("%s %s\n" % ("PASS" if ok else "FAIL", check_name))
        f.write("RESULT: %d passed, %d failed\n"
                % (len(CHECKS) - fails, fails))
    info("\n*** Test report saved to %s\n" % path)
    info("*** RESULT: %d passed, %d failed\n"
         % (len(CHECKS) - fails, fails))
    return fails


# ---------------------------------------------------------
# DIRECT BENCHMARK BYPASS
# ---------------------------------------------------------

def _direct_pairs():
    pairs = []
    for client_name in CLIENT_NAMES:
        client_ip = CFG["clients"][client_name]
        # Both directions are needed: the request and the response otherwise
        # hit the controller's default drop rule.
        pairs.append((client_ip, WEB_IP))
        pairs.append((WEB_IP, client_ip))
    return pairs


def enable_direct_benchmark(net):
    switch = net.get("s1")
    info("\n*** Temporarily enabling direct paths for baseline benchmark\n")
    for src, dst in _direct_pairs():
        switch.cmd(
            "ovs-ofctl -O OpenFlow13 add-flow s1 "
            "'priority=150,ip,nw_src=%s,nw_dst=%s,actions=NORMAL'"
            % (src, dst)
        )


def disable_direct_benchmark(net):
    switch = net.get("s1")
    info("\n*** Removing temporary direct benchmark flows\n")
    for src, dst in _direct_pairs():
        switch.cmd(
            "ovs-ofctl -O OpenFlow13 --strict del-flows s1 "
            "'priority=150,ip,nw_src=%s,nw_dst=%s'"
            % (src, dst)
        )


# ---------------------------------------------------------
# BASIC ACCEPTANCE TESTS (plan step 3)
# ---------------------------------------------------------

def run_basic_tests(net):
    c1, c2, c3 = [net.get(n) for n in CLIENT_NAMES]
    proxy = net.get("proxy")
    info("\n========== BASIC ACCEPTANCE TESTS ==========\n")

    save_dumpflows(net, "basic_before")

    out = run_client(c1, "GET web/index")
    check("allowed request returns data", "content of /index" in out, out)

    out = run_client(c1, "GET /x", direct=True, timeout=3)
    check("direct bypass fails at the switch", out.startswith("FAILED"), out)

    out = run_client(c2, "GET files/index")
    check("blocked request gets BLOCKED", out.startswith("BLOCKED"), out)

    out = run_client(c1, "GET web/secret-plan")
    check("keyword rule blocks", out.startswith("BLOCKED"), out)

    permits = _int(proxy.cmd(
        "cd %s && grep -c ',permit,' logs/proxy.log" % PROJECT_DIR))
    blocks = _int(proxy.cmd(
        "cd %s && grep -c ',block,' logs/proxy.log" % PROJECT_DIR))
    check("log shows both permit and block lines", permits > 0 and blocks > 0,
          "permits=%d blocks=%d" % (permits, blocks))

    flows = dumpflows(net)
    check("default drop flow is installed",
          any("priority=0" in line and "actions=drop" in line
              for line in flows.splitlines()), flows)
    check("allowed client-to-proxy flow is installed",
          has_flow(flows, 100, CFG["clients"][CLIENT_NAMES[0]], PROXY_IP),
          flows)

    control_command(proxy, "BLOCK web")
    time.sleep(0.3)
    out = run_client(c1, "GET web/index")
    check("dynamic BLOCK takes effect in the proxy",
          out.startswith("BLOCKED"), out)
    check("dynamic drop rule reaches the switch",
          has_flow(dumpflows(net), 200, PROXY_IP, WEB_IP), dumpflows(net))

    control_command(proxy, "ALLOW web")
    time.sleep(0.3)
    out = run_client(c1, "GET web/index")
    check("dynamic ALLOW restores service", "content of /index" in out, out)

    control_command(proxy, "UNBLOCK %s" % CFG["clients"][CLIENT_NAMES[0]])
    before = proxy_stats(proxy).get("auto_blocks", 0)
    flood = c1.cmd(
        "cd %s && python3 tests/flood.py --host %s --port %d "
        "--count 8 --mode malformed"
        % (PROJECT_DIR, PROXY_IP, PROXY_PORT))
    time.sleep(0.3)
    stats = proxy_stats(proxy)
    check("malformed flood is detected",
          stats.get("auto_blocks", 0) > before, flood)
    check("flooding client is auto-blocked",
          CFG["clients"][CLIENT_NAMES[0]] in stats.get("active_auto_blocks", {}),
          stats)
    check("switch drop is installed for the flooding client",
          has_flow(dumpflows(net), 200,
                   CFG["clients"][CLIENT_NAMES[0]], PROXY_IP),
          dumpflows(net))
    out = run_client(c3, "GET web/index")
    check("legitimate client keeps working during the flood",
          "content of /index" in out, out)

    save_dumpflows(net, "basic_autoblock")
    save_text("basic_flood.txt", flood)

    control_command(proxy, "UNBLOCK %s" % CFG["clients"][CLIENT_NAMES[0]])
    time.sleep(0.3)
    out = run_client(c1, "GET web/index", timeout=3)
    check("client works again after UNBLOCK", "content of /index" in out, out)

    save_proxy_log("basic")
    save_dumpflows(net, "basic_after")
    report("mininet_basic.txt")


# ---------------------------------------------------------
# MULTI-CLIENT DEMO (plan step 4)
# ---------------------------------------------------------

def run_multi_tests(net):
    proxy = net.get("proxy")
    info("\n========== MULTI-CLIENT POLICY TEST ==========\n")
    save_dumpflows(net, "multi_before")

    def batch(jobs):
        # A Mininet host has ONE shell, so host.cmd() must never run twice
        # at once on the same host. Different hosts run in parallel; the
        # jobs of one host run one after another inside a single worker.
        per_host = {}
        for host, req in jobs:
            per_host.setdefault(host, []).append(req)

        def run_host(host, reqs):
            return {(host, req): run_client(net.get(host), req)
                    for req in reqs}

        results = {}
        with ThreadPoolExecutor(max_workers=len(per_host)) as pool:
            futures = [pool.submit(run_host, host, reqs)
                       for host, reqs in per_host.items()]
            for future in futures:
                results.update(future.result())
        return results

    def show(results):
        return json.dumps({"%s %s" % key: value
                           for key, value in results.items()}, indent=2)

    first = batch([
        ("c1", "GET web/index"),
        ("c2", "GET files/index"),
        ("c3", "GET files/index"),
    ])
    save_text("multi_baseline.txt", show(first))
    check("c1 can read web",
          "content of /index" in first[("c1", "GET web/index")])
    check("c2 is denied files by the saved policy",
          first[("c2", "GET files/index")].startswith("BLOCKED"),
          first[("c2", "GET files/index")])
    check("c3 can read files",
          "content of /index" in first[("c3", "GET files/index")])

    info("\n*** Live change: BLOCK files (c2 and c3 are connected)\n")
    info(control_command(proxy, "BLOCK files"))
    time.sleep(0.5)
    second = batch([
        ("c1", "GET web/index"),
        ("c2", "GET files/index"),
        ("c3", "GET files/index"),
        ("c2", "GET web/index"),
    ])
    save_text("multi_block_files.txt", show(second))
    check("c2 is still denied files",
          second[("c2", "GET files/index")].startswith("BLOCKED"))
    check("c3 is now denied files",
          second[("c3", "GET files/index")].startswith("BLOCKED"),
          second[("c3", "GET files/index")])
    check("c1 web traffic is unaffected (first match wins)",
          "content of /index" in second[("c1", "GET web/index")])
    check("c2 web traffic still works",
          "content of /index" in second[("c2", "GET web/index")])
    check("files drop rule is in the switch",
          has_flow(dumpflows(net), 200, PROXY_IP, FILES_IP))

    info("\n*** Live change: BLOCKCLIENT 10.0.0.1\n")
    info(control_command(proxy, "BLOCKCLIENT %s"
                         % CFG["clients"][CLIENT_NAMES[0]]))
    time.sleep(0.5)
    third = batch([
        ("c1", "GET web/index"),
        ("c2", "GET web/index"),
        ("c3", "GET web/index"),
    ])
    save_text("multi_block_client.txt", show(third))
    check("blocked client c1 is cut off",
          blockedish(third[("c1", "GET web/index")]),
          third[("c1", "GET web/index")])
    check("c2 keeps working",
          "content of /index" in third[("c2", "GET web/index")])
    check("c3 keeps working",
          "content of /index" in third[("c3", "GET web/index")])
    check("client drop rule is in the switch",
          has_flow(dumpflows(net), 200,
                   CFG["clients"][CLIENT_NAMES[0]], PROXY_IP))
    save_dumpflows(net, "multi_after")

    info("\n*** Restoring policy\n")
    info(control_command(proxy, "ALLOWCLIENT %s"
                         % CFG["clients"][CLIENT_NAMES[0]]))
    info(control_command(proxy, "ALLOW files"))
    save_proxy_log("multi")
    report("mininet_multi.txt")


# ---------------------------------------------------------
# HARD SCENARIOS (plan step 5)
# ---------------------------------------------------------

def run_hard(net):
    c1, c2, c3 = [net.get(n) for n in CLIENT_NAMES]
    proxy = net.get("proxy")
    info("\n========== HARD SCENARIO TESTS ==========\n")

    save_dumpflows(net, "hard_before")

    # ---- 1: direct bypass ------------------------------------------------
    info("\n*** HARD TEST 1: direct service bypass\n")
    attempts = [run_client(c1, "GET /x", direct=True, timeout=2)
                for _ in range(3)]
    save_text("hard_bypass.txt", "\n---\n".join(attempts))
    check("all direct bypass attempts fail",
          all(a.startswith("FAILED") for a in attempts), attempts)
    check("legitimate client works during bypass",
          "content of /index" in run_client(c3, "GET web/index"))

    # ---- 2: malformed flood ---------------------------------------------
    info("\n*** HARD TEST 2: malformed request flood\n")
    control_command(proxy, "UNBLOCK %s" % CFG["clients"][CLIENT_NAMES[0]])
    before = proxy_stats(proxy).get("auto_blocks", 0)
    flood = c1.cmd(
        "cd %s && python3 tests/flood.py --host %s --port %d "
        "--count 20 --mode malformed"
        % (PROJECT_DIR, PROXY_IP, PROXY_PORT))
    save_text("hard_flood.txt", flood)
    time.sleep(0.3)
    stats = proxy_stats(proxy)
    check("malformed flood triggers an automatic block",
          stats.get("auto_blocks", 0) > before, flood)
    check("flooding client is listed as auto-blocked",
          CFG["clients"][CLIENT_NAMES[0]] in stats.get("active_auto_blocks", {}),
          stats)
    check("switch enforces the automatic block",
          has_flow(dumpflows(net), 200,
                   CFG["clients"][CLIENT_NAMES[0]], PROXY_IP))
    check("c3 is unaffected during the flood",
          "content of /index" in run_client(c3, "GET web/index"))
    save_dumpflows(net, "hard_flood")
    control_command(proxy, "UNBLOCK %s" % CFG["clients"][CLIENT_NAMES[0]])
    time.sleep(0.3)
    check("flooding client recovers after UNBLOCK",
          "content of /index" in run_client(c1, "GET web/index", timeout=3))

    # ---- 3: policy change during a transfer -----------------------------
    info("\n*** HARD TEST 3: policy change during a slow transfer\n")
    proc = c1.popen(
        "cd %s && python3 app/client.py --req 'GET web/slow' --timeout 15"
        % PROJECT_DIR,
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True)
    time.sleep(0.3)
    activation = control_command(proxy, "BLOCK web")
    try:
        output, _ = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        output = "TRANSFER STILL RUNNING AFTER 20s"
    save_text("hard_policy_change.txt",
              "ctl: %s\nclient after change: %s" % (activation, output))
    check("new requests are blocked after the mid-transfer policy change",
          run_client(c2, "GET web/index").startswith("BLOCKED"))
    time.sleep(0.3)
    check("mid-transfer BLOCK reaches the switch",
          has_flow(dumpflows(net), 200, PROXY_IP, WEB_IP))
    info("*** In-flight transfer ended with: %s\n" % output.strip()[:200])
    control_command(proxy, "ALLOW web")
    time.sleep(0.3)
    check("service is allowed again after ALLOW",
          "content of /index" in run_client(c3, "GET web/index"))

    # ---- 4: proxy crash and restart -------------------------------------
    info("\n*** HARD TEST 4: proxy crash and restart\n")
    control_command(proxy, "BLOCK files")
    time.sleep(0.3)
    check("files drop is installed before the crash",
          has_flow(dumpflows(net), 200, PROXY_IP, FILES_IP))
    before_stats = proxy_stats(proxy)
    save_text("hard_stats_before_crash.txt", json.dumps(before_stats, indent=2))

    proxy.cmd("pkill -f '[a]pp/proxy.py'")
    time.sleep(1)
    out = run_client(c1, "GET web/index", timeout=2)
    check("request fails while the proxy is down", out.startswith("FAILED"),
          out)

    info("*** Restarting proxy\n")
    start_proxy(proxy)
    time.sleep(2)
    out = run_client(c1, "GET web/index")
    check("service works after proxy restart", "content of /index" in out, out)
    after_stats = proxy_stats(proxy)
    check("STATS survived the proxy restart",
          after_stats.get("permitted", 0) >= before_stats.get("permitted", 0)
          and after_stats.get("blocked", 0) >= before_stats.get("blocked", 0),
          "before=%s after=%s" % (before_stats, after_stats))
    check("dynamic drop is re-synced after proxy restart",
          has_flow(dumpflows(net), 200, PROXY_IP, FILES_IP))
    control_command(proxy, "ALLOW files")
    time.sleep(0.3)
    check("ALLOW after restart removes the switch drop",
          not has_flow(dumpflows(net), 200, PROXY_IP, FILES_IP))

    save_proxy_log("hard")
    save_dumpflows(net, "hard_after")
    report("mininet_hard.txt")


# ---------------------------------------------------------
# DEMO
# ---------------------------------------------------------

def run_demo(net):
    c1, c2, c3 = [net.get(n) for n in CLIENT_NAMES]
    proxy = net.get("proxy")
    info("\n========== SDN PROXY DEMONSTRATION ==========\n")
    save_dumpflows(net, "demo_before")

    info("\n*** TEST 1: allowed request through proxy\n")
    info(run_client(c1, "GET web/index"))
    time.sleep(0.5)

    info("\n*** TEST 2: direct bypass attempt\n")
    info(run_client(c1, "GET /x", direct=True, timeout=3))
    time.sleep(0.5)

    info("\n*** TEST 3: client-specific policy (c2 denied files)\n")
    info(run_client(c2, "GET files/index"))
    info(run_client(c3, "GET files/index"))
    time.sleep(0.5)

    info("\n*** TEST 4: dynamically block web\n")
    info(control_command(proxy, "BLOCK web"))
    time.sleep(0.5)
    info(run_client(c1, "GET web/index"))
    info(run_client(c3, "GET web/index"))
    save_dumpflows(net, "demo_blocked")

    info("\n*** TEST 5: dynamically allow web\n")
    info(control_command(proxy, "ALLOW web"))
    time.sleep(0.5)
    info(run_client(c1, "GET web/index"))

    info("\n*** TEST 6: statistics\n")
    info(control_command(proxy, "STATS"))
    save_dumpflows(net, "demo_after")
    save_proxy_log("demo")

    info("\n========== DEMONSTRATION COMPLETE ==========\n")


# ---------------------------------------------------------
# BENCHMARKING
# ---------------------------------------------------------

BENCH_FIELDS = ["mode", "resource", "clients", "repeat", "requests",
                "errors", "mean_ms", "p95_ms", "rps", "mbps"]


def parse_bench(output):
    for line in reversed((output or "").splitlines()):
        if line.startswith("BENCHJSON "):
            try:
                return json.loads(line[len("BENCHJSON "):])
            except ValueError:
                return None
    return None


def bench_command(host, request, direct, reps, label):
    target = ("--host %s --port %d" % (WEB_IP, WEB_PORT)) if direct else ""
    command = (
        "cd %s && python3 app/client.py --bench --reps %d --conc 1 "
        "--timeout 30 --label %s %s --req '%s'"
        % (PROJECT_DIR, reps, label, target, request)
    )
    return host.popen(command, shell=True, stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, text=True)


def aggregate_bench(results):
    results = [r for r in results if r]
    latencies = [x for r in results for x in r.get("latencies_ms", [])]
    requests = sum(r.get("requests", 0) for r in results)
    successful = sum(r.get("ok", 0) for r in results)
    errors = sum(r.get("errors", 0) for r in results)
    nbytes = sum(r.get("bytes", 0) for r in results)
    duration = max((r.get("duration_s", 0) for r in results), default=0)
    if latencies:
        ordered = sorted(latencies)
        mean = statistics.mean(ordered)
        p95 = ordered[max(math.ceil(len(ordered) * 0.95) - 1, 0)]
    else:
        mean = p95 = 0
    rps = successful / duration if duration else 0
    mbps = nbytes * 8 / duration / 1e6 if duration else 0
    return {
        "requests": requests,
        "errors": errors,
        "mean_ms": mean,
        "p95_ms": p95,
        "rps": rps,
        "mbps": mbps,
    }


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarise_bench(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["resource"], row["clients"]), []).append(row)
    summary = []
    for (resource, clients), group in sorted(groups.items()):
        summary.append({
            "mode": group[0]["mode"],
            "resource": resource,
            "clients": clients,
            "repeats": len(group),
            "mean_ms": statistics.mean(r["mean_ms"] for r in group),
            "p95_ms": statistics.mean(r["p95_ms"] for r in group),
            "rps": statistics.mean(r["rps"] for r in group),
            "mbps": statistics.mean(r["mbps"] for r in group),
            "requests": sum(r["requests"] for r in group),
            "errors": sum(r["errors"] for r in group),
        })
    return summary


def run_benchmark(net, mode, repeats, reps):
    info("\n========== %s BENCHMARK ==========\n" % mode.upper())
    info("*** %d repetition(s) x %d request(s) per client per batch\n"
         % (repeats, reps))
    if mode == "direct":
        enable_direct_benchmark(net)

    hosts = [net.get(name) for name in CLIENT_NAMES]
    rows = []

    try:
        # Short warm-up, not recorded.
        warm_req = "GET /index" if mode == "direct" else "GET web/index"
        warm = bench_command(hosts[0], warm_req, mode == "direct",
                             max(reps // 2, 1), "warmup")
        try:
            warm.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            warm.kill()
            warm.communicate()

        for repeat in range(1, repeats + 1):
            for resource in ("index", "large"):
                request = ("GET /%s" % resource) if mode == "direct" \
                    else ("GET web/%s" % resource)
                for clients in (1, 5, 10):
                    info("\n*** repeat %d/%d | %s | %d client(s)\n"
                         % (repeat, repeats, resource, clients))
                    procs = []
                    for i in range(clients):
                        host = hosts[i % len(hosts)]
                        procs.append(bench_command(
                            host, request, mode == "direct", reps,
                            "%s_%s_%dc" % (mode, resource, clients)))
                    outputs = []
                    for proc in procs:
                        try:
                            out, _ = proc.communicate(timeout=180)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            out, _ = proc.communicate()
                        outputs.append(out)
                    result = aggregate_bench(
                        [parse_bench(out) for out in outputs])
                    row = {
                        "mode": mode,
                        "resource": resource,
                        "clients": clients,
                        "repeat": repeat,
                    }
                    row.update(result)
                    rows.append(row)
                    info("    mean %.2f ms | p95 %.2f ms | %.1f req/s | "
                         "%.2f Mbps | errors %d\n"
                         % (row["mean_ms"], row["p95_ms"], row["rps"],
                            row["mbps"], row["errors"]))
    finally:
        if mode == "direct":
            disable_direct_benchmark(net)

    result_dir = os.path.join(PROJECT_DIR, "results")
    raw_path = os.path.join(result_dir, "benchmark_%s.csv" % mode)
    summary_path = os.path.join(result_dir,
                                "benchmark_%s_summary.csv" % mode)
    write_csv(raw_path, BENCH_FIELDS, rows)
    write_csv(summary_path,
              ["mode", "resource", "clients", "repeats", "mean_ms",
               "p95_ms", "rps", "mbps", "requests", "errors"],
              summarise_bench(rows))
    info("\n*** Raw benchmark saved to %s\n" % raw_path)
    info("*** Summary saved to %s\n" % summary_path)


# ---------------------------------------------------------
# POLICY CHANGE TIMING (plan step 6)
# ---------------------------------------------------------

def run_policy_timing(net, cycles):
    proxy = net.get("proxy")
    info("\n========== POLICY CHANGE ACTIVATION TIME ==========\n")
    control_command(proxy, "ALLOW web")
    rows = []
    for i in range(1, cycles + 1):
        for action in ("BLOCK", "ALLOW"):
            out = control_command(proxy, "%s web" % action)
            match = re.search(r"after ([\d.]+) ms", out)
            ms = float(match.group(1)) if match else -1.0
            rows.append({"call": i, "action": action, "ms": ms})
            info("    %2d %-5s %8.2f ms\n" % (i, action, ms))
            time.sleep(0.05)

    path = os.path.join(PROJECT_DIR, "results", "policy_change.csv")
    write_csv(path, ["call", "action", "ms"], rows)
    valid = [r["ms"] for r in rows if r["ms"] >= 0]
    check("policy change timing has %d measurements" % (2 * cycles),
          len(valid) == 2 * cycles)
    if valid:
        ordered = sorted(valid)
        info("*** mean %.2f ms, p95 %.2f ms, max %.2f ms\n"
             % (statistics.mean(ordered),
                ordered[max(math.ceil(len(ordered) * 0.95) - 1, 0)],
                ordered[-1]))
    time.sleep(0.3)
    check("policy is restored to ALLOW web",
          "content of /index" in run_client(net.get(CLIENT_NAMES[0]),
                                            "GET web/index"))
    info("*** Policy timing saved to %s\n" % path)
    report("mininet_policy_timing.txt")


# ---------------------------------------------------------
# MAIN PROGRAM
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SDN Proxy and Content Filtering System")
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--hard", action="store_true")
    parser.add_argument("--test", choices=["basic", "multi"],
                        help="run scripted Mininet acceptance tests")
    parser.add_argument("--bench", choices=["proxy", "direct"])
    parser.add_argument("--policy-timing", action="store_true",
                        help="measure BLOCK/ALLOW activation time")
    parser.add_argument("--repeats", type=int, default=5,
                        help="benchmark repetitions (default 5)")
    parser.add_argument("--reps", type=int, default=5,
                        help="requests per client per benchmark batch")
    parser.add_argument("--cycles", type=int, default=20,
                        help="BLOCK/ALLOW pairs for --policy-timing")
    parser.add_argument("--cli", action="store_true",
                        help="enter the Mininet CLI after a scripted mode")
    args = parser.parse_args()

    selected = sum([args.demo, args.hard, args.test is not None,
                    args.bench is not None, args.policy_timing])
    if selected > 1:
        parser.error("Choose only one execution mode at a time")

    os.makedirs(os.path.join(PROJECT_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(PROJECT_DIR, "results", "evidence"),
                exist_ok=True)
    if selected:
        # Keep each scripted run's evidence self-contained.
        try:
            os.remove(os.path.join(PROJECT_DIR, "logs", "proxy.log"))
        except OSError:
            pass

    net = Mininet(
        topo=ProxyFilterTopo(),
        controller=None,
        switch=OVSSwitch,
        autoSetMacs=True,
        waitConnected=True
    )
    net.addController(
        "c0",
        controller=RemoteController,
        ip=args.controller_ip,
        port=args.controller_port
    )

    try:
        info("\n*** Starting SDN network\n")
        net.start()
        # Automatic blocking stays on except for performance runs: a
        # benchmark is a legitimate load, not an attack, and must not be
        # throttled by the abuse detector.
        start_applications(net, auto_block=args.bench is None)

        info("\n*** Network ready\n")
        info("*** Hosts: %s\n" % " ".join(CLIENT_NAMES + ["proxy"]
                                          + list(SERVICES)))
        info("*** Switch: s1 (OpenFlow 1.3)\n")

        if args.demo:
            run_demo(net)
        elif args.hard:
            run_hard(net)
        elif args.test == "basic":
            run_basic_tests(net)
        elif args.test == "multi":
            run_multi_tests(net)
        elif args.bench:
            run_benchmark(net, args.bench, args.repeats, args.reps)
        elif args.policy_timing:
            run_policy_timing(net, args.cycles)

        if selected == 0 or args.cli:
            info("\n*** Entering Mininet CLI\n\n")
            CLI(net)

    finally:
        info("\n*** Stopping network\n")
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    main()
