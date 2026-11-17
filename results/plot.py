#!/usr/bin/env python3
"""Turn benchmark CSVs into the graphs and summary table used in the report.

    python3 results/plot.py                     # reads results/benchmark_*.csv
    python3 results/plot.py --dir results/localhost --out results/localhost

Inputs (produced by topology/topo.py --bench proxy|direct):
    benchmark_proxy.csv, benchmark_direct.csv, policy_change.csv
Outputs:
    latency.png, throughput.png, policy_change.png, summary.md
"""
import argparse
import csv
import math
import os
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


RESOURCES = ["index", "large"]
CLIENTS = [1, 5, 10]
COLOURS = {"proxy": "#1f77b4", "direct": "#ff7f0e"}
LABELS = {"proxy": "via proxy", "direct": "direct (baseline)"}


def load_csv(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "mode": row.get("mode", ""),
                    "resource": row["resource"],
                    "clients": int(row["clients"]),
                    "repeat": int(row.get("repeat", 1)),
                    "requests": int(float(row.get("requests", 0))),
                    "errors": int(float(row.get("errors", 0))),
                    "mean_ms": float(row["mean_ms"]),
                    "p95_ms": float(row["p95_ms"]),
                    "rps": float(row["rps"]),
                    "mbps": float(row["mbps"]),
                })
            except (KeyError, ValueError):
                continue
    return rows


def aggregate(rows):
    groups = {}
    for row in rows:
        key = (row["mode"], row["resource"], row["clients"])
        groups.setdefault(key, []).append(row)
    result = {}
    for key, group in groups.items():
        result[key] = {
            "mean_ms": statistics.mean(r["mean_ms"] for r in group),
            "mean_ms_sd": (statistics.stdev(r["mean_ms"] for r in group)
                           if len(group) > 1 else 0),
            "p95_ms": statistics.mean(r["p95_ms"] for r in group),
            "p95_ms_sd": (statistics.stdev(r["p95_ms"] for r in group)
                          if len(group) > 1 else 0),
            "rps": statistics.mean(r["rps"] for r in group),
            "rps_sd": (statistics.stdev(r["rps"] for r in group)
                       if len(group) > 1 else 0),
            "mbps": statistics.mean(r["mbps"] for r in group),
            "mbps_sd": (statistics.stdev(r["mbps"] for r in group)
                        if len(group) > 1 else 0),
            "repeats": len(group),
            "requests": sum(r["requests"] for r in group),
            "errors": sum(r["errors"] for r in group),
        }
    return result


def plot_latency(agg, out):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, resource in zip(axes, RESOURCES):
        for mode in ("proxy", "direct"):
            points = [(c, agg[(mode, resource, c)])
                      for c in CLIENTS if (mode, resource, c) in agg]
            if not points:
                continue
            x = [p[0] for p in points]
            y = [p[1]["mean_ms"] for p in points]
            err = [p[1]["mean_ms_sd"] for p in points]
            ax.errorbar(x, y, yerr=err, marker="o", capsize=3,
                        color=COLOURS[mode], label=LABELS[mode])
        ax.set_title("Response: %s" % resource)
        ax.set_xlabel("concurrent clients")
        ax.set_ylabel("mean latency (ms)")
        ax.set_xticks(CLIENTS)
        ax.grid(alpha=0.3)
        ax.legend()
    fig.suptitle("Latency vs concurrent clients (mean of repeats)")
    fig.tight_layout()
    path = os.path.join(out, "latency.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_throughput(agg, out):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.5))
    for col, resource in enumerate(RESOURCES):
        for row, metric, unit in ((0, "rps", "requests/s"),
                                  (1, "mbps", "Mbps")):
            ax = axes[row][col]
            for mode in ("proxy", "direct"):
                points = [(c, agg[(mode, resource, c)])
                          for c in CLIENTS if (mode, resource, c) in agg]
                if not points:
                    continue
                x = [p[0] for p in points]
                y = [p[1][metric] for p in points]
                err = [p[1][metric + "_sd"] for p in points]
                ax.errorbar(x, y, yerr=err, marker="o", capsize=3,
                            color=COLOURS[mode], label=LABELS[mode])
            ax.set_title("%s: %s" % (resource, unit))
            ax.set_xlabel("concurrent clients")
            ax.set_ylabel(unit)
            ax.set_xticks(CLIENTS)
            ax.grid(alpha=0.3)
            ax.legend()
    fig.suptitle("Throughput vs concurrent clients (mean of repeats)")
    fig.tight_layout()
    path = os.path.join(out, "throughput.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_policy(path, out):
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                rows.append((int(row["call"]), row["action"],
                             float(row["ms"])))
            except (KeyError, ValueError):
                continue
    if not rows:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for action, colour in (("BLOCK", "#d62728"), ("ALLOW", "#2ca02c")):
        points = [(c, ms) for c, a, ms in rows if a == action and ms >= 0]
        axes[0].plot([p[0] for p in points], [p[1] for p in points],
                     marker="o", color=colour, label=action)
    values = [ms for _, _, ms in rows if ms >= 0]
    if values:
        axes[0].axhline(statistics.mean(values), color="grey", linestyle="--",
                        label="mean %.1f ms" % statistics.mean(values))
    axes[0].set_xlabel("BLOCK/ALLOW pair")
    axes[0].set_ylabel("activation time (ms)")
    axes[0].set_title("Policy change activation time")
    axes[0].grid(alpha=0.3)
    axes[0].legend()

    axes[1].hist(values, bins=12, color="#1f77b4", edgecolor="white")
    axes[1].set_xlabel("activation time (ms)")
    axes[1].set_ylabel("count")
    axes[1].set_title("Distribution (%d measurements)" % len(values))
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    destination = os.path.join(out, "policy_change.png")
    fig.savefig(destination, dpi=150)
    plt.close(fig)
    return destination


def write_summary(agg, out):
    lines = ["# Benchmark summary", ""]
    available = sorted({mode for mode, _, _ in agg})
    lines.append("Modes: %s. Values are means across repeats."
                 % ", ".join(available))
    lines.append("")
    lines.append("| resource | clients | proxy mean ms | direct mean ms | "
                 "latency overhead | proxy req/s | direct req/s | "
                 "proxy Mbps | direct Mbps |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for resource in RESOURCES:
        for clients in CLIENTS:
            p = agg.get(("proxy", resource, clients))
            d = agg.get(("direct", resource, clients))
            if not p and not d:
                continue
            overhead = ""
            if p and d and d["mean_ms"]:
                overhead = "%+.1f%%" % (
                    (p["mean_ms"] - d["mean_ms"]) / d["mean_ms"] * 100)
            lines.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
                resource, clients,
                "%.2f" % p["mean_ms"] if p else "-",
                "%.2f" % d["mean_ms"] if d else "-",
                overhead,
                "%.1f" % p["rps"] if p else "-",
                "%.1f" % d["rps"] if d else "-",
                "%.2f" % p["mbps"] if p else "-",
                "%.2f" % d["mbps"] if d else "-",
            ))
    lines.append("")
    lines.append("`mean` is the mean per-request latency; request and byte "
                 "rates are measured by the load generator itself "
                 "(`app/client.py --bench`), not from process start-up time.")
    path = os.path.join(out, "summary.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join("results"))
    ap.add_argument("--out", default=None,
                    help="output directory (default: same as --dir)")
    a = ap.parse_args()
    out = a.out or a.dir
    os.makedirs(out, exist_ok=True)

    proxy = load_csv(os.path.join(a.dir, "benchmark_proxy.csv"))
    direct = load_csv(os.path.join(a.dir, "benchmark_direct.csv"))
    if not proxy and not direct:
        print("No benchmark CSVs in %s. Run topology/topo.py --bench first."
              % a.dir)
        return 1
    agg = aggregate(proxy + direct)

    for path in (plot_latency(agg, out),
                 plot_throughput(agg, out),
                 plot_policy(os.path.join(a.dir, "policy_change.csv"), out),
                 write_summary(agg, out)):
        if path:
            print("wrote %s" % path)

    policy_path = os.path.join(a.dir, "policy_change.csv")
    if os.path.exists(policy_path):
        values = []
        with open(policy_path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    ms = float(row["ms"])
                except (KeyError, ValueError):
                    continue
                if ms >= 0:
                    values.append(ms)
        if values:
            ordered = sorted(values)
            print("policy change: mean %.2f ms, p95 %.2f ms, max %.2f ms"
                  % (statistics.mean(ordered),
                     ordered[max(math.ceil(len(ordered) * 0.95) - 1, 0)],
                     ordered[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
