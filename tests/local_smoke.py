#!/usr/bin/env python3
"""End-to-end test of proxy + services + control channel on localhost, using a
fake controller. No Mininet/Ryu needed:  python3 tests/local_smoke.py

On Linux the fake controller uses the same unix socket as Ryu.  On systems
without socket.AF_UNIX (e.g. Python on Windows) it falls back to the
"controller_tcp" transport, which config/network.json also supports.
"""
import atexit
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PROXY_PORT = free_port()
CTL_PORT = free_port()
WEB_PORT = free_port()
FILES_PORT = free_port()

received = []
state = {"boot": "boot-1"}

if hasattr(socket, "AF_UNIX"):
    sock_path = tmp + "/ctl.sock"
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(sock_path)
    ctrl_cfg = {"controller_sock": sock_path}
else:
    srv = socket.socket(socket.AF_INET)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    ctrl_cfg = {"controller_tcp": {"host": "127.0.0.1",
                                   "port": srv.getsockname()[1]}}
srv.listen(5)


def fake_ctl():
    while True:
        c, _ = srv.accept()
        try:
            line = c.recv(200).decode().strip()
            received.append(line)
            if line == "PING":
                reply = "OK " + state["boot"]
            elif line == "CLEAR":
                reply = "OK all drops cleared"
            else:
                reply = "OK " + line
            c.sendall((reply + "\n").encode())
        finally:
            c.close()


threading.Thread(target=fake_ctl, daemon=True).start()

cfg = {
    "clients": {"c1": "127.0.0.1"},
    "proxy": {
        "ip": "127.0.0.1", "port": PROXY_PORT, "control_port": CTL_PORT,
        "stats_file": tmp + "/stats.json",
        "sync_interval_s": 0.25,
        "auto_block": {
            "malformed_threshold": 5,
            "malformed_window_s": 10.0,
            "rate_threshold": 40,
            "rate_window_s": 10.0,
            "block_seconds": 30,
        },
    },
    "services": {
        "web": {"ip": "127.0.0.1", "port": WEB_PORT},
        "files": {"ip": "127.0.0.1", "port": FILES_PORT},
    },
}
cfg.update(ctrl_cfg)
with open(tmp + "/net.json", "w") as f:
    json.dump(cfg, f)
with open(tmp + "/policy.json", "w") as f:
    json.dump({"default": "allow", "rules": [
        {"client": "*", "service": "*", "keyword": "secret",
         "action": "deny"}]}, f)

procs = []


def cleanup():
    for p in procs:
        if p.poll() is None:
            p.kill()


atexit.register(cleanup)


def spawn(*a):
    p = subprocess.Popen([sys.executable] + list(a), cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def start_proxy():
    return spawn("app/proxy.py", "--config", tmp + "/net.json",
                 "--policy", tmp + "/policy.json", "--log", tmp + "/proxy.log",
                 "--listen", "127.0.0.1", "--port", str(PROXY_PORT),
                 "--ctl-port", str(CTL_PORT))


def req(line, port=None, timeout=5):
    port = port or PROXY_PORT
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall((line + "\n").encode())
    d = b""
    try:
        while True:
            c = s.recv(65536)
            if not c:
                break
            d += c
    except OSError:
        # Windows can turn "server closed while request was unread" into a
        # reset; treat it as a dropped connection.
        pass
    finally:
        s.close()
    return d.decode(errors="replace").strip() or "FAILED"


def ctl(line):
    s = socket.create_connection(("127.0.0.1", CTL_PORT), timeout=5)
    s.sendall((line + "\n").encode())
    r = s.recv(500).decode().strip()
    s.close()
    return r


def burst(n, line="GET web/index"):
    outputs = []
    lock = threading.Lock()

    def worker():
        try:
            text = req(line, timeout=3)
        except OSError:
            text = "FAILED"
        with lock:
            outputs.append(text)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return outputs


def blockedish(text):
    return text.startswith("BLOCKED") or text == "FAILED"


def wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


spawn("app/service.py", "--name", "web", "--host", "127.0.0.1",
      "--port", str(WEB_PORT))
files_proc = spawn("app/service.py", "--name", "files", "--host",
                   "127.0.0.1", "--port", str(FILES_PORT))
pr = start_proxy()
time.sleep(1)

check("allowed request returns data", "content of /index" in req("GET web/index"))
check("keyword rule blocks", req("GET web/secret-plan").startswith("BLOCKED"))
check("malformed request rejected", req("hello").startswith("ERROR malformed"))
check("unknown service rejected", req("GET nope/x").startswith("ERROR"))
rules_before = json.loads(ctl("SHOW"))["rules"]
unknown = ctl("BLOCK nosuchservice")
rules_after = json.loads(ctl("SHOW"))["rules"]
check("BLOCK unknown service rejected and policy unchanged",
      unknown == "ERROR unknown service" and rules_before == rules_after)
check("large response complete", len(req("GET web/large")) == 1_000_000)
r = ctl("BLOCK files")
check("BLOCK files accepted", r.startswith("OK"))
check("controller was told to DROP", "DROP 127.0.0.1 127.0.0.1" in received)
check("blocked service gets BLOCKED", req("GET files/a").startswith("BLOCKED"))

# Controller restart: a new boot id must make the proxy push the whole set.
marker = len(received)
state["boot"] = "boot-2"
rebooted = wait_for(
    lambda: any(line.startswith("DROP ") for line in received[marker:]), 3)
check("drop rules are pushed again after controller restart", rebooted)

before_stats = json.loads(ctl("STATS"))
pr.kill()
time.sleep(0.5)
pr = start_proxy()
time.sleep(1)
check("block survives proxy restart", req("GET files/a").startswith("BLOCKED"))
check("legit traffic works after restart", "content of /index" in req("GET web/index"))
after_stats = json.loads(ctl("STATS"))
check("STATS survive proxy restart",
      after_stats["permitted"] >= before_stats["permitted"]
      and after_stats["blocked"] >= before_stats["blocked"])
check("STATS file exists", os.path.exists(tmp + "/stats.json"))

ctl("ALLOW files")
check("controller told to ALLOW", "ALLOW 127.0.0.1 127.0.0.1" in received)
check("ALLOW restores service", "content of /a" in req("GET files/a"))
st = json.loads(ctl("STATS"))
check("counters kept (permitted>0, blocked>0)",
      st["permitted"] > 0 and st["blocked"] > 0)

# Malformed flood -> automatic block in the proxy and in the controller.
ctl("UNBLOCK 127.0.0.1")
flood = burst(8, "MALFORMED")
st = json.loads(ctl("STATS"))
check("malformed flood is auto-blocked", st["auto_blocks"] >= 1
      and "127.0.0.1" in st["active_auto_blocks"])
check("flood response is BLOCKED or dropped",
      any(blockedish(x) for x in flood))
check("legit request is also denied while auto-blocked",
      blockedish(req("GET web/index")))
ctl("UNBLOCK 127.0.0.1")
check("UNBLOCK restores the client", "content of /index" in req("GET web/index"))

# Request-rate flood -> automatic block (threshold 40 / 10 s).
flood = burst(60)
st = json.loads(ctl("STATS"))
check("request-rate flood is auto-blocked", st["auto_blocks"] >= 2
      and "127.0.0.1" in st["active_auto_blocks"])
check("rate flood response is BLOCKED",
      any(blockedish(x) for x in flood))
ctl("UNBLOCK 127.0.0.1")

files_proc.kill()
time.sleep(0.3)
check("service down handled", "service unavailable" in req("GET files/a"))
with open(tmp + "/proxy.log") as f:
    log = f.read()
check("log has permit and block lines", ",permit," in log and ",block," in log)
for p in procs:
    p.kill()
print("\nFAILED: %d" % fails)
sys.exit(1 if fails else 0)
