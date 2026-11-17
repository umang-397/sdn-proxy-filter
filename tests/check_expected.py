#!/usr/bin/env python3
"""Compare a scripted Mininet report with its expected PASS/FAIL lines.

    python3 tests/check_expected.py results/mininet_basic.txt \
        tests/expected/mininet_basic.txt
"""
import difflib
import os
import sys


def main():
    if len(sys.argv) != 3:
        print("usage: check_expected.py <actual report> <expected file>")
        return 2
    actual_path, expected_path = sys.argv[1], sys.argv[2]
    if not os.path.exists(actual_path):
        print("missing report: %s (run the Mininet test first)" % actual_path)
        return 2
    with open(actual_path) as f:
        actual = [line.rstrip() for line in f
                  if line.startswith(("PASS ", "FAIL "))]
    with open(expected_path) as f:
        expected = [line.rstrip() for line in f
                    if line.startswith(("PASS ", "FAIL "))]

    if actual == expected:
        print("OK: %d lines match %s" % (len(actual), expected_path))
        return 0

    print("MISMATCH: %s vs %s" % (actual_path, expected_path))
    for line in difflib.unified_diff(expected, actual,
                                     fromfile="expected", tofile="actual",
                                     lineterm=""):
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
