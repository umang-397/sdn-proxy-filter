
#!/usr/bin/env python3

import os
import time
import argparse
import statistics
import subprocess

from concurrent.futures import ThreadPoolExecutor
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLIENTS = ["c1", "c2", "c3"]
PROXY_IP = "10.0.0.10"
PROXY_PORT = 8080
WEB_IP = "10.0.0.21"
WEB_PORT = 8001
FILES_IP = "10.0.0.22"
FILES_PORT = 8002


# ---------------------------------------------------------
# NETWORK TOPOLOGY
# ---------------------------------------------------------

class ProxyFilterTopo(Topo):

    def build(self):

        s1 = self.addSwitch("s1", protocols="OpenFlow13")

        c1 = self.addHost("c1", ip="10.0.0.1/24")
        c2 = self.addHost("c2", ip="10.0.0.2/24")
        c3 = self.addHost("c3", ip="10.0.0.3/24")

        proxy = self.addHost("proxy", ip="10.0.0.10/24")

        web = self.addHost("web", ip="10.0.0.21/24")
        files = self.addHost("files", ip="10.0.0.22/24")

        for host in [c1, c2, c3, proxy, web, files]:
            self.addLink(host, s1)


# ---------------------------------------------------------
# APPLICATION STARTUP
# ---------------------------------------------------------

def start_applications(net):

    os.makedirs(os.path.join(PROJECT_DIR, "logs"), exist_ok=True)

    web = net.get("web")
    files = net.get("files")
    proxy = net.get("proxy")

    info("\n*** Starting web service\n")
    web.cmd(
        "cd %s && python3 app/service.py "
        "--name web --port 8001 > logs/web.log 2>&1 &" % PROJECT_DIR
    )

    info("*** Starting files service\n")
    files.cmd(
        "cd %s && python3 app/service.py "
        "--name files --port 8002 > logs/files.log 2>&1 &" % PROJECT_DIR
    )

    info("*** Starting TCP proxy\n")
    start_proxy(proxy)

    time.sleep(2)
    info("*** Applications started\n")


def start_proxy(proxy):

    proxy.cmd(
        "cd %s && python3 app/proxy.py "
        "> logs/proxy.log 2>&1 &" % PROJECT_DIR
    )


def run_client(host, request, direct=False):

    if direct:
        command = (
            "cd %s && python3 app/client.py "
            "--host %s --port %s --req '%s' --timeout 5"
            % (PROJECT_DIR, WEB_IP, WEB_PORT, request)
        )
    else:
        command = (
            "cd %s && python3 app/client.py --req '%s'"
            % (PROJECT_DIR, request)
        )

    return host.cmd(command)


def control_command(proxy, command):

    return proxy.cmd(
        "cd %s && python3 app/ctl.py %s"
        % (PROJECT_DIR, command)
    )


# ---------------------------------------------------------
# FLOW MANAGEMENT FOR DIRECT BENCHMARK
# ---------------------------------------------------------

def enable_direct_benchmark(net):

    switch = net.get("s1")

    info("\n*** Temporarily enabling direct paths for baseline benchmark\n")

    pairs = [
        ("10.0.0.1", WEB_IP),
        ("10.0.0.2", WEB_IP),
        ("10.0.0.3", WEB_IP),
    ]

    for src, dst in pairs:
        switch.cmd(
            "ovs-ofctl -O OpenFlow13 add-flow s1 "
            "'priority=150,ip,nw_src=%s,nw_dst=%s,actions=NORMAL'"
            % (src, dst)
        )


def disable_direct_benchmark(net):

    switch = net.get("s1")

    info("\n*** Removing temporary direct benchmark flows\n")

    pairs = [
        ("10.0.0.1", WEB_IP),
        ("10.0.0.2", WEB_IP),
        ("10.0.0.3", WEB_IP),
    ]

    for src, dst in pairs:
        switch.cmd(
            "ovs-ofctl -O OpenFlow13 --strict del-flows s1 "
            "'priority=150,ip,nw_src=%s,nw_dst=%s'"
            % (src, dst)
        )


# ---------------------------------------------------------
# AUTOMATED DEMONSTRATION
# ---------------------------------------------------------

def run_demo(net):

    c1 = net.get("c1")
    c2 = net.get("c2")
    proxy = net.get("proxy")

    info("\n========== SDN PROXY DEMONSTRATION ==========\n")

    info("\n*** TEST 1: Allowed request through proxy\n")
    info(run_client(c1, "GET web/index"))

    time.sleep(1)

    info("\n*** TEST 2: Direct bypass attempt\n")
    info(
        c1.cmd(
            "cd %s && python3 app/client.py "
            "--host %s --port %s --req 'GET /x' --timeout 3"
            % (PROJECT_DIR, WEB_IP, WEB_PORT)
        )
    )

    time.sleep(1)

    info("\n*** TEST 3: Client-specific policy\n")
    info(run_client(c2, "GET files/index"))

    time.sleep(1)

    info("\n*** TEST 4: Dynamically block web\n")
    info(control_command(proxy, "BLOCK web"))

    time.sleep(1)

    info(run_client(c1, "GET web/index"))

    time.sleep(1)

    info("\n*** TEST 5: Dynamically allow web\n")
    info(control_command(proxy, "ALLOW web"))

    time.sleep(1)

    info(run_client(c1, "GET web/index"))

    info("\n*** TEST 6: Display policy statistics\n")
    info(control_command(proxy, "STATS"))

    info("\n========== DEMONSTRATION COMPLETE ==========\n")


# ---------------------------------------------------------
# HARD SCENARIO TESTS
# ---------------------------------------------------------

def run_hard(net):

    c1 = net.get("c1")
    c2 = net.get("c2")
    proxy = net.get("proxy")

    info("\n========== HARD SCENARIO TESTS ==========\n")

    # Test 1: Direct bypass attempt
    info("\n*** HARD TEST 1: Direct service bypass\n")

    for i in range(5):
        info(
            c1.cmd(
                "cd %s && python3 app/client.py "
                "--host %s --port %s --req 'GET /x' --timeout 2"
                % (PROJECT_DIR, WEB_IP, WEB_PORT)
            )
        )

    # Test 2: Malformed request flood
    info("\n*** HARD TEST 2: Malformed request flood\n")

    for i in range(20):
        c1.cmd(
            "python3 -c \"import socket; "
            "s=socket.socket(); "
            "s.settimeout(2); "
            "s.connect(('10.0.0.10',8080)); "
            "s.sendall(b'MALFORMED\\\\n'); "
            "s.close()\""
        )

    info("*** Sent 20 malformed requests\n")

    # Test 3: Policy change during active transfer
    info("\n*** HARD TEST 3: Policy change during transfer\n")

    command = (
        "cd %s && python3 app/client.py --req 'GET web/large'"
        % PROJECT_DIR
    )

    client_process = c1.popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    time.sleep(0.2)

    info(control_command(proxy, "BLOCK web"))

    try:
        output, _ = client_process.communicate(timeout=15)
        info(output)
    except subprocess.TimeoutExpired:
        client_process.kill()
        info("*** Transfer timed out\n")

    time.sleep(1)

    info("*** Testing blocked access after policy change\n")
    info(run_client(c2, "GET web/index"))

    info(control_command(proxy, "ALLOW web"))

    # Test 4: Proxy crash and restart
    info("\n*** HARD TEST 4: Proxy crash and restart\n")

    proxy.cmd("pkill -f '[a]pp/proxy.py'")

    time.sleep(1)

    info("*** Restarting proxy\n")
    start_proxy(proxy)

    time.sleep(2)

    info("*** Testing service access after proxy restart\n")
    info(run_client(c1, "GET web/index"))

    info(control_command(proxy, "STATS"))

    info("\n========== HARD SCENARIOS COMPLETE ==========\n")


# ---------------------------------------------------------
# BENCHMARKING
# ---------------------------------------------------------

def benchmark_request(host, mode, resource):

    start = time.perf_counter()

    if mode == "proxy":
        output = run_client(host, "GET web/" + resource)

    else:
        output = host.cmd(
            "cd %s && python3 app/client.py "
            "--host %s --port %s --req 'GET /%s' --timeout 15"
            % (PROJECT_DIR, WEB_IP, WEB_PORT, resource)
        )

    elapsed = time.perf_counter() - start

    return elapsed, len(output.encode("utf-8"))


def run_benchmark(net, mode):

    info("\n========== %s BENCHMARK ==========\n" % mode.upper())

    if mode == "direct":
        enable_direct_benchmark(net)

    hosts = [net.get(name) for name in CLIENTS]

    results = []

    try:

        for resource in ["index", "large"]:

            for concurrency in [1, 5, 10]:

                info(
                    "\n*** Resource: %s | Concurrent clients: %d\n"
                    % (resource, concurrency)
                )

                processes = []
                start_time = time.perf_counter()

                for i in range(concurrency):

                    host = hosts[i % len(hosts)]

                    if mode == "proxy":
                        command = (
                            "cd %s && python3 app/client.py "
                            "--req 'GET web/%s'"
                            % (PROJECT_DIR, resource)
                        )
                    else:
                        command = (
                            "cd %s && python3 app/client.py "
                            "--host %s --port %s "
                            "--req 'GET /%s' --timeout 15"
                            % (PROJECT_DIR, WEB_IP, WEB_PORT, resource)
                        )

                    process = host.popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True
                    )

                    processes.append(process)

                durations = []
                total_bytes = 0
                successful = 0

                for process in processes:

                    try:
                        output, _ = process.communicate(timeout=30)

                        duration = time.perf_counter() - start_time
                        durations.append(duration)
                        total_bytes += len(output.encode("utf-8"))

                        if process.returncode == 0:
                            successful += 1

                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()

                total_time = max(durations) if durations else 0

                avg_latency = (
                    statistics.mean(durations)
                    if durations else 0
                )

                throughput = (
                    total_bytes / total_time
                    if total_time > 0 else 0
                )

                requests_per_second = (
                    successful / total_time
                    if total_time > 0 else 0
                )

                result = {
                    "mode": mode,
                    "resource": resource,
                    "clients": concurrency,
                    "successful": successful,
                    "avg_latency": avg_latency,
                    "throughput": throughput,
                    "requests_per_second": requests_per_second
                }

                results.append(result)

                info("\nResults:\n")
                info("Successful requests: %d/%d\n" %
                     (successful, concurrency))
                info("Average completion time: %.4f seconds\n" %
                     avg_latency)
                info("Request throughput: %.4f requests/second\n" %
                     requests_per_second)
                info("Output throughput: %.2f bytes/second\n" %
                     throughput)

    finally:

        if mode == "direct":
            disable_direct_benchmark(net)

    save_benchmark_results(results, mode)


def save_benchmark_results(results, mode):

    results_dir = os.path.join(PROJECT_DIR, "results")
    os.makedirs(results_dir, exist_ok=True)

    output_file = os.path.join(
        results_dir,
        "benchmark_%s.csv" % mode
    )

    with open(output_file, "w") as file:

        file.write(
            "mode,resource,clients,successful,avg_latency,"
            "requests_per_second,throughput_bytes_per_second\n"
        )

        for result in results:

            file.write(
                "{mode},{resource},{clients},{successful},"
                "{avg_latency:.6f},{requests_per_second:.6f},"
                "{throughput:.2f}\n".format(**result)
            )

    info("\n*** Benchmark results saved to %s\n" % output_file)


# ---------------------------------------------------------
# MAIN PROGRAM
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="SDN Proxy and Content Filtering System"
    )

    parser.add_argument(
        "--controller-ip",
        default="127.0.0.1"
    )

    parser.add_argument(
        "--controller-port",
        type=int,
        default=6653
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run automated demonstration"
    )

    parser.add_argument(
        "--hard",
        action="store_true",
        help="Run hard scenario tests"
    )

    parser.add_argument(
        "--bench",
        choices=["proxy", "direct"],
        help="Run proxy or direct benchmark"
    )

    args = parser.parse_args()

    selected_modes = sum([
        args.demo,
        args.hard,
        args.bench is not None
    ])

    if selected_modes > 1:
        parser.error("Choose only one execution mode at a time")

    os.makedirs(os.path.join(PROJECT_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(PROJECT_DIR, "results"), exist_ok=True)

    topo = ProxyFilterTopo()

    net = Mininet(
        topo=topo,
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

        start_applications(net)

        info("\n*** Network ready\n")
        info("*** Hosts: c1 c2 c3 proxy web files\n")
        info("*** Switch: s1 (OpenFlow 1.3)\n")

        if args.demo:
            run_demo(net)

        elif args.hard:
            run_hard(net)

        elif args.bench:
            run_benchmark(net, args.bench)

        info("\n*** Entering Mininet CLI\n\n")
        CLI(net)

    finally:

        info("\n*** Stopping network\n")
        net.stop()


if __name__ == "__main__":

    setLogLevel("info")
    main()
