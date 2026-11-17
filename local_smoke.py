#!/usr/bin/env python3
"""End-to-end test of proxy + services + control channel on localhost, using a
fake controller. No Mininet/Ryu needed:  python3 tests/local_smoke.py"""
import json, os, socket, subprocess, sys, tempfile, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
sock_path = tmp + "/ctl.sock"
cfg = {"controller_sock": sock_path, "clients": {"c1": "127.0.0.1"},
       "proxy": {"ip": "127.0.0.1", "port": 18080, "control_port": 19000},
       "services": {"web": {"ip": "127.0.0.1", "port": 18001},
                    "files": {"ip": "127.0.0.1", "port": 18002}}}
json.dump(cfg, open(tmp + "/net.json", "w"))
json.dump({"default": "allow", "rules": [
    {"client": "*", "service": "*", "keyword": "secret", "action": "deny"}]},
    open(tmp + "/policy.json", "w"))

received = []
srv = socket.socket(socket.AF_UNIX); srv.bind(sock_path); srv.listen(5)
def fake_ctl():
    while True:
        c, _ = srv.accept()
        line = c.recv(200).decode().strip(); received.append(line)
        c.sendall(b"OK " + line.encode()); c.close()
threading.Thread(target=fake_ctl, daemon=True).start()

procs = []
def spawn(*a):
    p = subprocess.Popen([sys.executable] + list(a), cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p); return p
def start_proxy():
    return spawn("app/proxy.py", "--config", tmp + "/net.json", "--policy", tmp + "/policy.json",
                 "--log", tmp + "/proxy.log", "--listen", "127.0.0.1", "--port", "18080", "--ctl-port", "19000")
def req(line, port=18080):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall((line + "\n").encode()); d = b""
    while True:
        c = s.recv(65536)
        if not c: break
        d += c
    return d.decode(errors="replace").strip()
def ctl(line):
    s = socket.create_connection(("127.0.0.1", 19000), timeout=5)
    s.sendall((line + "\n").encode()); r = s.recv(500).decode().strip(); s.close(); return r

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += 0 if cond else 1

spawn("app/service.py", "--name", "web", "--host", "127.0.0.1", "--port", "18001")
files_proc = spawn("app/service.py", "--name", "files", "--host", "127.0.0.1", "--port", "18002")
pr = start_proxy(); time.sleep(1)

check("allowed request returns data", "content of /index" in req("GET web/index"))
check("keyword rule blocks", req("GET web/secret-plan").startswith("BLOCKED"))
check("malformed request rejected", req("hello").startswith("ERROR malformed"))
check("unknown service rejected", req("GET nope/x").startswith("ERROR"))
check("BLOCK/ALLOW reject unknown service",
      ctl("BLOCK nosuch").startswith("ERROR unknown service")
      and ctl("ALLOW nosuch").startswith("ERROR unknown service")
      and "nosuch" not in ctl("SHOW"))
check("large response complete", len(req("GET web/large")) == 1_000_000)
r = ctl("BLOCK files")
check("BLOCK files accepted", r.startswith("OK"))
check("controller was told to DROP", "DROP 127.0.0.1 127.0.0.1" in received)
check("blocked service gets BLOCKED", req("GET files/a").startswith("BLOCKED"))
pr.kill(); time.sleep(0.5); pr = start_proxy(); time.sleep(1)
check("block survives proxy restart", req("GET files/a").startswith("BLOCKED"))
check("legit traffic works after restart", "content of /index" in req("GET web/index"))
ctl("ALLOW files")
check("controller told to ALLOW", "ALLOW 127.0.0.1 127.0.0.1" in received)
check("ALLOW restores service", "content of /a" in req("GET files/a"))
st = json.loads(ctl("STATS"))
check("counters kept (permitted>0, blocked>0)", st["permitted"] > 0 and st["blocked"] > 0)
files_proc.kill(); time.sleep(0.3)
check("service down handled", "service unavailable" in req("GET files/a"))
log = open(tmp + "/proxy.log").read()
check("log has permit and block lines", ",permit," in log and ",block," in log)
for p in procs: p.kill()
print("\nFAILED: %d" % fails); sys.exit(1 if fails else 0)
