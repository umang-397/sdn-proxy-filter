#!/usr/bin/env python3
"""Localhost-only sanity benchmark (no Mininet needed).

This exercises exactly the same client JSON protocol and CSV schema as the
Mininet benchmark, so results/plot.py can be tested without a VM.  It is NOT
a substitute for the Mininet study: there is no switch, and "direct" simply
connects to the service.  Output goes to results/localhost/.

    python3 tests/local_benchmark.py
    python3 results/plot.py --dir results/localhost --out results/localhost
"""
import argparse
import atexit
import csv
import json
import math
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results", "localhost")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeController:
    """Accepts proxy notifications so policy changes do not wait on timeouts."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            conn, _ = self.sock.accept()
            try:
                line = conn.recv(500).decode(errors="replace").strip()
                reply = "OK boot-local" if line == "PING" else "OK " + line
                conn.sendall((reply + "\n").encode())
            except OSError:
                pass
            finally:
                conn.close()


def parse_json(text):
    for line in reversed((text or "").splitlines()):
        if line.startswith("BENCHJSON "):
            try:
                return json.loads(line[len("BENCHJSON "):])
            except ValueError:
                return None
    return None


def aggregate(results):
    results = [r for r in results if r]
    latencies = sorted(x for r in results for x in r.get("latencies_ms", []))
    requests = sum(r.get("requests", 0) for r in results)
    successful = sum(r.get("ok", 0) for r in results)
    errors = sum(r.get("errors", 0) for r in results)
    nbytes = sum(r.get("bytes", 0) for r in results)
    duration = max((r.get("duration_s", 0) for r in results), default=0)
    return {
        "requests": requests,
        "errors": errors,
        "mean_ms": statistics.mean(latencies) if latencies else 0,
        "p95_ms": latencies[max(math.ceil(len(latencies) * 0.95) - 1, 0)]
        if latencies else 0,
        "rps": successful / duration if duration else 0,
        "mbps": nbytes * 8 / duration / 1e6 if duration else 0,
    }


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarise(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["resource"], row["clients"]), []).append(row)
    out = []
    for (resource, clients), group in sorted(groups.items()):
        out.append({
            "mode": group[0]["mode"], "resource": resource,
            "clients": clients, "repeats": len(group),
            "mean_ms": statistics.mean(r["mean_ms"] for r in group),
            "p95_ms": statistics.mean(r["p95_ms"] for r in group),
            "rps": statistics.mean(r["rps"] for r in group),
            "mbps": statistics.mean(r["mbps"] for r in group),
            "requests": sum(r["requests"] for r in group),
            "errors": sum(r["errors"] for r in group),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp()
    proxy_port, web_port, files_port, ctl_port = [free_port() for _ in range(4)]
    controller = FakeController()

    cfg = {
        "controller_tcp": {"host": "127.0.0.1", "port": controller.port},
        "clients": {"c1": "127.0.0.1"},
        "proxy": {
            "ip": "127.0.0.1", "port": proxy_port, "control_port": ctl_port,
            "stats_file": tmp + "/stats.json", "sync_interval_s": 5,
            "auto_block": {"malformed_threshold": 0, "rate_threshold": 0},
        },
        "services": {
            "web": {"ip": "127.0.0.1", "port": web_port},
            "files": {"ip": "127.0.0.1", "port": files_port},
        },
    }
    with open(tmp + "/net.json", "w") as f:
        json.dump(cfg, f)
    with open(tmp + "/policy.json", "w") as f:
        json.dump({"default": "allow", "rules": []}, f)

    procs = []

    def cleanup():
        for p in procs:
            if p.poll() is None:
                p.kill()

    atexit.register(cleanup)

    def spawn(*args):
        p = subprocess.Popen([sys.executable] + list(args), cwd=ROOT,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        procs.append(p)
        return p

    spawn("app/service.py", "--name", "web", "--host", "127.0.0.1",
          "--port", str(web_port))
    spawn("app/service.py", "--name", "files", "--host", "127.0.0.1",
          "--port", str(files_port))
    spawn("app/proxy.py", "--config", tmp + "/net.json",
          "--policy", tmp + "/policy.json", "--log", tmp + "/proxy.log",
          "--listen", "127.0.0.1", "--port", str(proxy_port),
          "--ctl-port", str(ctl_port), "--no-auto-block")
    time.sleep(1.5)

    fields = ["mode", "resource", "clients", "repeat", "requests", "errors",
              "mean_ms", "p95_ms", "rps", "mbps"]

    for mode in ("proxy", "direct"):
        rows = []
        for repeat in range(1, a.repeats + 1):
            for resource in ("index", "large"):
                for clients in (1, 5, 10):
                    batch = []
                    for _ in range(clients):
                        if mode == "proxy":
                            host, port = "127.0.0.1", proxy_port
                            req = "GET web/%s" % resource
                        else:
                            host, port = "127.0.0.1", web_port
                            req = "GET /%s" % resource
                        cmd = [sys.executable, "app/client.py", "--bench",
                               "--host", host, "--port", str(port),
                               "--req", req, "--timeout", "30",
                               "--reps", str(a.reps), "--conc", "1",
                               "--label", "localhost"]
                        batch.append(subprocess.Popen(
                            cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True))
                    outputs = []
                    for p in batch:
                        try:
                            out, _ = p.communicate(timeout=180)
                        except subprocess.TimeoutExpired:
                            p.kill()
                            out, _ = p.communicate()
                        outputs.append(out)
                    result = aggregate([parse_json(o) for o in outputs])
                    row = {"mode": mode, "resource": resource,
                           "clients": clients, "repeat": repeat}
                    row.update(result)
                    rows.append(row)
                    print("%s %s %2d clients repeat %d: %.2f ms, %.1f req/s, "
                          "%.2f Mbps, errors %d" %
                          (mode, resource, clients, repeat, row["mean_ms"],
                           row["rps"], row["mbps"], row["errors"]))
        write_csv(os.path.join(OUT, "benchmark_%s.csv" % mode), fields, rows)
        write_csv(os.path.join(OUT, "benchmark_%s_summary.csv" % mode),
                  ["mode", "resource", "clients", "repeats", "mean_ms",
                   "p95_ms", "rps", "mbps", "requests", "errors"],
                  summarise(rows))

    cleanup()
    print("\nLocalhost benchmark written to %s" % OUT)
    print("Plot with: python3 results/plot.py --dir results/localhost "
          "--out results/localhost")
    return 0


if __name__ == "__main__":
    sys.exit(main())
