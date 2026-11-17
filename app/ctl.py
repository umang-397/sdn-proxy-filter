#!/usr/bin/env python3
"""Send a runtime command to the proxy, e.g.  ctl.py BLOCK files"""
import socket
import sys

port = 9000
args = sys.argv[1:]
if args and args[0] == "--port":
    port, args = int(args[1]), args[2:]
s = socket.create_connection(("127.0.0.1", port), timeout=5)
s.sendall((" ".join(args) + "\n").encode())
print(s.recv(4096).decode().strip())
s.close()
