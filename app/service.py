#!/usr/bin/env python3
"""Simulated TCP service ("web" / "files"). One request line in, body out."""
import argparse
import socket
import threading
import time

LARGE = b"x" * 1_000_000


def handle(conn, name):
    try:
        conn.settimeout(5)
        buf = b""
        while b"\n" not in buf and len(buf) < 1024:
            chunk = conn.recv(256)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n")[0].decode(errors="replace").strip()
        resource = line[5:] if line.startswith("GET /") else line
        if "slow" in resource:
            # 1 MB in 20 chunks over ~1 s: used by the "policy change in the
            # middle of a transfer" hard scenario.
            chunk = LARGE[:len(LARGE) // 20]
            for _ in range(20):
                conn.sendall(chunk)
                time.sleep(0.05)
        elif "large" in resource:
            conn.sendall(LARGE)
        else:
            conn.sendall(("[%s] content of /%s\n" % (name, resource)).encode())
    except OSError:
        pass
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((a.host, a.port))
    s.listen(128)
    print("service %s on %s:%d" % (a.name, a.host, a.port), flush=True)
    while True:
        conn, _ = s.accept()
        threading.Thread(target=handle, args=(conn, a.name), daemon=True).start()


if __name__ == "__main__":
    main()
