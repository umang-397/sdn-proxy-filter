#!/usr/bin/env python3
"""Small flood helper for the hard scenarios.

    python3 tests/flood.py --host 10.0.0.10 --port 8080 --count 20 --mode malformed

Modes:
    malformed  send "MALFORMED" (invalid request line)
    valid      send "GET web/index" (valid request)
Prints one summary line that the Mininet tests can check.
"""
import argparse
import socket
import threading


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="10.0.0.10")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--mode", choices=["malformed", "valid"],
                    default="malformed")
    ap.add_argument("--timeout", type=float, default=2)
    a = ap.parse_args()

    line = "MALFORMED\n" if a.mode == "malformed" else "GET web/index\n"
    counts = {"blocked": 0, "error": 0, "data": 0, "failed": 0}
    lock = threading.Lock()

    def worker(n):
        for _ in range(n):
            try:
                s = socket.create_connection((a.host, a.port),
                                             timeout=a.timeout)
                s.settimeout(a.timeout)
                s.sendall(line.encode())
                data = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                s.close()
                text = data.decode(errors="replace").strip()
                key = ("blocked" if text.startswith("BLOCKED")
                       else "data" if text else "error")
                with lock:
                    counts[key] += 1
            except OSError:
                with lock:
                    counts["failed"] += 1

    per = [a.count // a.workers] * a.workers
    for i in range(a.count % a.workers):
        per[i] += 1
    threads = [threading.Thread(target=worker, args=(n,))
               for n in per if n]
    [t.start() for t in threads]
    [t.join() for t in threads]

    print("FLOOD mode=%s count=%d blocked=%d error=%d data=%d failed=%d" % (
        a.mode, a.count, counts["blocked"], counts["error"],
        counts["data"], counts["failed"]))


if __name__ == "__main__":
    main()
