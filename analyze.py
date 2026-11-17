#!/usr/bin/env python3
"""Compare matched experimental runs and write a Markdown report and a CSV table."""
import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import median

from tools import require

METRICS = ("p50_us", "p99_us", "useful_reads_per_sec", "duplicate_fraction",
           "replica_reads", "replica_bytes", "peak_active_permits", "cleanup_p99_us")


def key(row):
    return (int(row["depth"]), row["interference"], int(row["repeat"]), int(row["seed"]),
            int(row.get("offered_reads_per_sec", 0)))


def budget_config(row):
    return int(row["delay_us"]), int(row["permit_limit"]), int(row["threshold"])


def delta(value, baseline):
    return 100 * (float(value) / float(baseline) - 1)


def compare(rows, output):
    by_run = defaultdict(list)
    for row in rows:
        by_run[key(row)].append(row)
        require(int(row["failed_logical"]) == int(row["invalid_replicas"]) == 0,
                f"unexpected read failure in {row['case']}")

    metrics = METRICS + tuple(metric for metric in ("replicas_per_success", "alternate_wins",
                                                     "peak_outstanding_losers")
                              if metric in rows[0])
    comparisons = []
    for group in by_run.values():
        baseline = {r["mode"]: r for r in group if r["mode"] in ("round-robin", "less-busy")}
        fixed = {int(r["delay_us"]): r for r in group if r["mode"] == "fixed"}
        require(baseline.keys() == {"round-robin", "less-busy"} and fixed,
                "missing baseline in an experiment group")
        for row in group:
            if row["mode"] != "budget":
                continue
            matches = dict(baseline, fixed=fixed[int(row["delay_us"])])
            for label, other in matches.items():
                require(row["logical_reads"] == other["logical_reads"],
                        "matched runs used different logical read counts")
                require(row.get("trace_sha256") == other.get("trace_sha256"),
                        "matched runs used different arrival traces")
                comparisons.append({
                    **{k: row[k] for k in ("depth", "interference", "repeat", "seed",
                                          "delay_us", "permit_limit", "threshold")},
                    "offered_reads_per_sec": row.get("offered_reads_per_sec", ""),
                    "baseline": label,
                    **{f"budget_{metric}": row[metric] for metric in metrics},
                    **{f"baseline_{metric}": other[metric] for metric in metrics},
                    "p99_delta_pct": delta(row["p99_us"], other["p99_us"]),
                    "throughput_delta_pct": delta(row["useful_reads_per_sec"],
                                                  other["useful_reads_per_sec"]),
                    "replica_delta_pct": delta(row["replica_reads"], other["replica_reads"]),
                })
    require(bool(comparisons), "no budget comparisons found")
    with (output / "matched-comparisons.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=comparisons[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(comparisons)
    return by_run, comparisons


def describe(rows, by_run, comparisons):
    conditions = defaultdict(lambda: defaultdict(list))
    for row in rows:
        depth, noise, _, _, rate = key(row)
        config = (row["mode"], *budget_config(row))
        conditions[rate, depth, noise][config].append(row)

    n_reads = sum(int(r["logical_reads"]) for r in rows)
    cap_rows = [r for r in rows if r["mode"] == "budget"]
    require(all(int(r["peak_active_permits"]) <= int(r["permit_limit"]) for r in cap_rows),
            "a run exceeded its permit limit")
    enabled_thresholds = any(int(r["threshold"]) > 0 for r in cap_rows)
    lines = [
        "# Milestone 3 Experiment Analysis", "",
        f"Analyzed {len(rows):,} runs and {n_reads:,} logical reads. "
        f"All runs had zero failed logical reads and zero invalid replica reads.", "",
        "## Latency and duplicate I/O by condition", "",
        "Each number is a median across repetitions. Fixed and budget show the settings "
        "with the lowest observed median p99 within that condition. Budget excludes the "
        "threshold-disabled ablation. The delay is in microseconds. Duplicate rates are "
        "duplicates divided by logical reads.", "",
        "| Offered reads/s | Depth | Interference | Round-robin p99 µs | Less-busy p99 µs | "
        "Fixed p99 µs (delay, duplicates) | Budget p99 µs (delay, permits, duplicates) |",
        "|---:|---|---:|---:|---|---|",
    ]

    def mid(runs, metric):
        return median(float(run[metric]) for run in runs)

    for (rate, depth, noise), groups in sorted(conditions.items()):
        fixed_cfg, fixed = min(((c, g) for c, g in groups.items() if c[0] == "fixed"),
                               key=lambda item: mid(item[1], "p99_us"))
        budget_cfg, budget = min(((c, g) for c, g in groups.items()
                                  if c[0] == "budget" and (c[3] > 0 or not enabled_thresholds)),
                                 key=lambda item: mid(item[1], "p99_us"))
        rr = mid(groups[("round-robin", 0, 0, 0)], "p99_us")
        lb = mid(groups[("less-busy", 0, 0, 0)], "p99_us")
        lines.append(
            f"| {rate or 'closed loop'} | {depth} | {noise} | {rr:.1f} | {lb:.1f} | "
            f"{mid(fixed, 'p99_us'):.1f} ({fixed_cfg[1]}, "
            f"{mid(fixed, 'duplicate_fraction'):.1%}) | "
            f"{mid(budget, 'p99_us'):.1f} ({budget_cfg[1]}, "
            f"{budget_cfg[2]}, {mid(budget, 'duplicate_fraction'):.1%}) |"
        )

    lines += ["", "## Paired comparisons across settings", "",
              "Each budget run is paired with a baseline from the same depth, "
              "interference condition, and repetition. The fixed baseline also uses "
              "the same hedge delay. Runs with the threshold enabled are used when available.", "",
              "| Baseline | Matched pairs | Lower budget p99 | Lower budget replica count | "
              "Lower p99 and fewer replicas | Median p99 change | Median replica count change | Median throughput change |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for baseline in ("round-robin", "less-busy", "fixed"):
        pairs = [p for p in comparisons if p["baseline"] == baseline and
                 (int(p["threshold"]) > 0 or not enabled_thresholds)]
        lower_latency = sum(p["p99_delta_pct"] < 0 for p in pairs)
        lower_io = sum(p["replica_delta_pct"] < 0 for p in pairs)
        both = sum(p["p99_delta_pct"] < 0 and p["replica_delta_pct"] < 0 for p in pairs)
        lines.append(f"| {baseline} | {len(pairs)} | {lower_latency} | {lower_io} | {both} | "
                     f"{mid(pairs, 'p99_delta_pct'):+.1f}% | "
                     f"{mid(pairs, 'replica_delta_pct'):+.1f}% | "
                     f"{mid(pairs, 'throughput_delta_pct'):+.1f}% |")

    ablation = []
    for group in by_run.values():
        disabled = [r for r in group if r["mode"] == "budget" and int(r["threshold"]) == 0]
        for row in disabled:
            enabled = next((r for r in group if r["mode"] == "budget" and
                           budget_config(row)[:2] == budget_config(r)[:2] and
                           int(r["threshold"]) > 0), None)
            if enabled is not None:
                ablation.append((row, enabled))
    if ablation:
        lines += ["", "## Alternate-drive threshold ablation", "",
                  "The permit limit and delay are held fixed. Values compare threshold off "
                  "with threshold on within each repetition.", "",
                  "| Depth | Interference | Repeat | Permits | p99 delta | Duplicates on | Duplicates off |",
                  "|---:|---|---:|---:|---:|---:|---:|"]
        for off, on in ablation:
            lines.append(f"| {off['depth']} | {off['interference']} | {int(off['repeat']) + 1} | "
                         f"{off['permit_limit']} | {delta(off['p99_us'], on['p99_us']):+.1f}% | "
                         f"{float(on['duplicate_fraction']):.1%} | {float(off['duplicate_fraction']):.1%} |")

    lines += ["", "See summary.csv for p50, p99, throughput, replica counts and bytes, "
              "duplicate fraction, peak active permits, and p99 loser cleanup for every run. "
              "See matched-comparisons.csv for the individual paired comparisons.", ""]
    if all(row["environment"] == "smoke" for row in rows):
        lines += ["## Storage environment", "",
                  "The replicas and interference files shared one WSL 2 ext4 virtual "
                  "filesystem. The interference labels identify the workload's target file. "
                  "All four files shared the same storage path. Use separate physical HDDs "
                  "and recalibrate delays before drawing conclusions about independent "
                  "drive behavior.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    args = parser.parse_args()
    with args.summary.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(bool(rows), "summary is empty")
    require(len({row["environment"] for row in rows}) == 1, "mixed storage environments")
    output = args.summary.parent
    by_run, comparisons = compare(rows, output)
    (output / "analysis.md").write_text(describe(rows, by_run, comparisons), encoding="utf-8")


if __name__ == "__main__":
    main()
