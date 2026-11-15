"""Policy table for the proxy.

Rules are checked top to bottom and the FIRST match wins (that is the
precedence order). A rule has: client (IP or "*"), service (name or "*"),
keyword (substring of the resource, or null) and action ("allow"/"deny").
If nothing matches, the "default" action is used.
"""
import json
import os
import threading


class Policy:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.default = "allow"
        self.rules = []
        self.mtime = 0
        if not os.path.exists(path):
            self.save()
        self.load()

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

    def decide(self, client, service, resource):
        """Return (action, reason)."""
        with self.lock:
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
