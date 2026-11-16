#!/usr/bin/env python3
"""Send a runtime command to the proxy, e.g.  ctl.py BLOCK files

The control port is read from config/network.json (proxy.control_port).  The
proxy only listens on 127.0.0.1, so run this on the proxy host.
"""
import argparse
import json
import socket

ap = argparse.ArgumentParser()
ap.add_argument("--config", default="config/network.json")
ap.add_argument("--port", type=int, default=None,
                help="override the control port from the config")
ap.add_argument("command", nargs="+")
a = ap.parse_args()

port = a.port
if port is None:
    with open(a.config) as f:
        port = json.load(f)["proxy"].get("control_port", 9000)

s = socket.create_connection(("127.0.0.1", port), timeout=5)
s.sendall((" ".join(a.command) + "\n").encode())
print(s.recv(65536).decode().strip())
s.close()
