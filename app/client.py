#!/usr/bin/env python3
"""Client: single request, or a small load generator (--bench).

--bench prints one human readable CSV line and one machine readable line:

    BENCHJSON {"label": ..., "latencies": [...], "requests": N, ...}

topology/topo.py parses the BENCHJSON line, so a benchmark never measures
interpreter startup or truncated console output.
"""
import argparse
import json
import math
import socket
import threading
import time


def one_request(host, port, line, timeout):
    t0 = time.perf_counter()
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    s.sendall((line + "\n").encode())
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return time.perf_counter() - t0, data


def bench(host, port, line, conc, reps, timeout, label):
    lat, nbytes, errors = [], [0], [0]
    lock = threading.Lock()

    def worker():
        for _ in range(reps):
            try:
                t, d = one_request(host, port, line, timeout)
                with lock:
                    lat.append(t)
                    nbytes[0] += len(d)
            except OSError:
                with lock:
                    errors[0] += 1

    t0 = time.perf_counter()
    ths = [threading.Thread(target=worker) for _ in range(conc)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    total = time.perf_counter() - t0
    lat.sort()
    requests = len(lat) + errors[0]
    mean = sum(lat) / len(lat) * 1000 if lat else 0
    p95 = (lat[max(math.ceil(len(lat) * 0.95) - 1, 0)] * 1000
           if lat else 0)
    print("%s,%d,%d,%.2f,%.2f,%.1f,%.2f,%d" % (
        label, conc, reps, mean, p95, len(lat) / total,
        nbytes[0] * 8 / total / 1e6, errors[0]))
    print("BENCHJSON " + json.dumps({
        "label": label,
        "concurrency": conc,
        "reps": reps,
        "requests": requests,
        "ok": len(lat),
        "errors": errors[0],
        "bytes": nbytes[0],
        "duration_s": total,
        "mean_ms": mean,
        "p95_ms": p95,
        # Enough precision for aggregate statistics, small enough for stdout.
        "latencies_ms": [round(x * 1000, 3) for x in lat],
    }), flush=True)


def main():
    cfg = json.load(open("config/network.json"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=cfg["proxy"]["ip"])
    ap.add_argument("--port", type=int, default=cfg["proxy"]["port"])
    ap.add_argument("--req", required=True, help='e.g. "GET web/index"')
    ap.add_argument("--timeout", type=float, default=5)
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--conc", type=int, default=1)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--label", default="proxy")
    a = ap.parse_args()
    if a.bench:
        bench(a.host, a.port, a.req, a.conc, a.reps, a.timeout, a.label)
        return
    try:
        t, data = one_request(a.host, a.port, a.req, a.timeout)
        text = data[:120].decode(errors="replace").strip()
        print("%s (%d bytes, %.1f ms)" % (text, len(data), t * 1000))
    except OSError as e:
        print("FAILED: %s" % e)


if __name__ == "__main__":
    main()
