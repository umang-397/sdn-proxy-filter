"""Unit tests for policy precedence (no Mininet needed): python3 tests/test_policy.py"""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from policy import Policy


def make(rules, default="allow"):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"default": default, "rules": rules}, f)
    f.close()
    return Policy(f.name)


class T(unittest.TestCase):
    def test_default(self):
        self.assertEqual(make([]).decide("1.1.1.1", "web", "x")[0], "allow")
        self.assertEqual(make([], "deny").decide("1.1.1.1", "web", "x")[0], "deny")

    def test_first_match_wins(self):
        p = make([{"client": "1.1.1.1", "service": "web", "keyword": None, "action": "allow"},
                  {"client": "*", "service": "web", "keyword": None, "action": "deny"}])
        self.assertEqual(p.decide("1.1.1.1", "web", "x")[0], "allow")
        self.assertEqual(p.decide("2.2.2.2", "web", "x")[0], "deny")

    def test_keyword(self):
        p = make([{"client": "*", "service": "*", "keyword": "secret", "action": "deny"}])
        self.assertEqual(p.decide("1.1.1.1", "web", "my-secret")[0], "deny")
        self.assertEqual(p.decide("1.1.1.1", "web", "public")[0], "allow")

    def test_runtime_block_allow(self):
        p = make([])
        p.block_service("files")
        self.assertEqual(p.decide("1.1.1.1", "files", "a")[0], "deny")
        p.allow_service("files")
        self.assertEqual(p.decide("1.1.1.1", "files", "a")[0], "allow")


if __name__ == "__main__":
    unittest.main()
