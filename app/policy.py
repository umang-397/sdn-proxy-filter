"""Policy table for the proxy.

Rules are checked top to bottom and the FIRST match wins (that is the
precedence order). A rule has: client (IP or "*"), service (name or "*"),
keyword (substring of the resource, or null) and action ("allow"/"deny").
If nothing matches, the "default" action is used.

Temporary automatic blocks (installed by the proxy when a client floods the
proxy with malformed or excessive requests) are checked before every rule and
are intentionally NOT written to disk: they expire on their own.
"""
import json
import os
import threading
import time


class Policy:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.default = "allow"
        self.rules = []
        self.auto_blocks = {}        # client -> {"until": epoch, "reason": str}
        self.mtime = 0
        if not os.path.exists(path):
            self.save()
        self.load()

    # ------------------------------------------------------------ disk
    def load(self):
        with self.lock:
            with open(self.path) as f:
                data = json.load(f)
            self.default = data.get("default", "allow")
            self.rules = data.get("rules", [])
            self.mtime = os.path.getmtime(self.path)

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"default": self.default, "rules": self.rules}, f, indent=2)
            os.replace(tmp, self.path)
            self.mtime = os.path.getmtime(self.path)

    def changed_on_disk(self):
        try:
            return os.path.getmtime(self.path) != self.mtime
        except OSError:
            return False

    # --------------------------------------------------------- decision
    def decide(self, client, service, resource):
        """Return (action, reason). First match wins; auto-blocks come first."""
        with self.lock:
            info = self.auto_blocks.get(client)
            if info and info["until"] > time.time():
                return "deny", info["reason"]
            for i, r in enumerate(self.rules, start=1):
                if r.get("client", "*") not in ("*", client):
                    continue
                if r.get("service", "*") not in ("*", service):
                    continue
                kw = r.get("keyword")
                if kw and kw not in resource:
                    continue
                return r["action"], "rule %d" % i
            return self.default, "default"

    # ------------------------------------------------ automatic blocks
    def auto_block(self, client, seconds, reason):
        """Block client for a while. Returns True if it was not already blocked."""
        now = time.time()
        with self.lock:
            current = self.auto_blocks.get(client)
            fresh = not current or current["until"] <= now
            self.auto_blocks[client] = {"until": now + seconds, "reason": reason}
            return fresh

    def auto_block_reason(self, client):
        with self.lock:
            info = self.auto_blocks.get(client)
            if info and info["until"] > time.time():
                return info["reason"]
            return None

    def clear_auto_block(self, client):
        with self.lock:
            return self.auto_blocks.pop(client, None) is not None

    def expire_auto_blocks(self):
        """Drop expired entries. Returns the list of clients that were released."""
        now = time.time()
        released = []
        with self.lock:
            for client, info in list(self.auto_blocks.items()):
                if info["until"] <= now:
                    del self.auto_blocks[client]
                    released.append(client)
        return released

    def active_auto_blocks(self):
        now = time.time()
        with self.lock:
            return {c: dict(i) for c, i in self.auto_blocks.items()
                    if i["until"] > now}

    # ---- runtime changes (each one is saved to disk so a restart keeps it)
    def _add_front(self, rule):
        with self.lock:
            if rule not in self.rules:
                self.rules.insert(0, rule)
            self.save()

    def _remove(self, rule):
        with self.lock:
            self.rules = [r for r in self.rules if r != rule]
            self.save()

    @staticmethod
    def _deny_service(s):
        return {"client": "*", "service": s, "keyword": None, "action": "deny"}

    @staticmethod
    def _deny_client(c):
        return {"client": c, "service": "*", "keyword": None, "action": "deny"}

    def block_service(self, s):
        self._add_front(self._deny_service(s))

    def allow_service(self, s):
        self._remove(self._deny_service(s))

    def block_client(self, c):
        self._add_front(self._deny_client(c))

    def allow_client(self, c):
        self._remove(self._deny_client(c))
