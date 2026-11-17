#!/usr/bin/env python3
"""Prepare test files, validate logs, and run the experiment matrix."""
import argparse
import csv
import math
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import time
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from statistics import median

BLOCK = 4096
MODES = ("round-robin", "less-busy", "fixed", "budget")
INTERFERENCE_ORDER = ("none", "a", "b", "both")


def prepare(paths, mib):
    if mib < 1:
        raise ValueError("file size must be at least 1 MiB")
    if len({path.resolve() for path in paths}) != len(paths) or any(
        path.exists() for path in paths
    ):
        raise ValueError("use distinct output paths that do not already exist")
    created = []
    try:
        with ExitStack() as stack:
            files = []
            for path in paths:
                files.append(stack.enter_context(path.open("xb")))
                created.append(path)
            for block in range(mib * 256):
                record = struct.pack("<Q", block) * (BLOCK // 8)
                for file in files:
                    file.write(record)
            for file in files:
                file.flush()
                os.fsync(file.fileno())
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def read_rows(path):
    with path.open(newline="") as stream:
        return [{key: int(value) for key, value in row.items()}
                for row in csv.DictReader(stream)]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def percentile(samples, p):
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * p) - 1] if ordered else math.nan


def summarize(prefix):
    logical = read_rows(Path(f"{prefix}-logical.csv"))
    replicas = read_rows(Path(f"{prefix}-replica.csv"))
    grouped = defaultdict(list)
    for row in replicas:
        grouped[row["id"]].append(row)
    require(logical and len(grouped) == len(logical), "logical/replica ID mismatch")
    latencies, cleanup, loser_events = [], [], []
    alternate_wins = 0
    duplicates = 0
    for expected_id, row in enumerate(logical):
        require(row["id"] == expected_id, "missing or repeated logical ID")
        copies = sorted(grouped.get(row["id"], []), key=lambda copy: copy["attempt"])
        require(row["issued"] in (1, 2) and len(copies) == row["issued"],
                "missing completion or unexpected replica count")
        require([copy["attempt"] for copy in copies] == list(range(1, len(copies) + 1)),
                "duplicate or missing replica ID")
        require(len({copy["disk"] for copy in copies}) == len(copies),
                "both copies targeted the same disk")
        require(all(row["start_ns"] <= copy["start_ns"] <= copy["end_ns"]
                    for copy in copies), "invalid replica timestamps")
        require(all(copy["valid"] == 0 or copy["result"] == BLOCK for copy in copies),
                "an incomplete replica was marked valid")
        drained = max(copy["end_ns"] for copy in copies)
        require(drained == row["drained_ns"], "drain time disagrees with replica log")
        winners = [copy for copy in copies if copy["winner"]]
        valid = [copy for copy in copies if copy["valid"]]
        if row["winner"] >= 0:
            require(len(winners) == 1 and winners[0]["valid"] and
                    winners[0]["disk"] == row["winner"] and
                    row["end_ns"] == winners[0]["end_ns"] ==
                    min(copy["end_ns"] for copy in valid), "invalid first successful read")
            latencies.append((row["end_ns"] - row["start_ns"]) / 1000)
            if len(copies) == 2:
                cleanup.append((drained - row["end_ns"]) / 1000)
                alternate_wins += winners[0]["attempt"] == 2
                if drained > row["end_ns"]:
                    loser_events.extend(((row["end_ns"], 1), (drained, -1)))
        else:
            require(not winners and not valid and row["end_ns"] == drained,
                    "failed logical read finished before all attempts failed")
        require(not row["permit"] or len(copies) == 2, "permit without a duplicate")
        duplicates += len(copies) - 1

    active_losers = peak_losers = 0
    for _, change in sorted(loser_events):
        active_losers += change
        peak_losers = max(peak_losers, active_losers)

    # The denominator includes the time spent draining the last duplicates.
    duration = (max(row["drained_ns"] for row in logical) - logical[0]["start_ns"]) / 1e9
    return {
        "logical_reads": len(logical),
        "failed_logical": len(logical) - len(latencies),
        "invalid_replicas": sum(not row["valid"] for row in replicas),
        "p50_us": percentile(latencies, .50),
        "p99_us": percentile(latencies, .99),
        "useful_reads_per_sec": len(latencies) / duration if duration else math.nan,
        "replica_reads": len(replicas),
        "replica_bytes": sum(max(0, row["result"]) for row in replicas),
        "duplicate_fraction": duplicates / len(logical),
        "replicas_per_success": len(replicas) / len(latencies) if latencies else math.nan,
        "alternate_wins": alternate_wins,
        "peak_outstanding_losers": peak_losers,
        "peak_active_permits": max(row["permits_at_submit"] for row in replicas),
        "cleanup_p99_us": percentile(cleanup, .99),
    }


def run(binary, a, b, prefix, mode, count, depth, delay, permits, threshold, seed, rate=0):
    cmd = [str(binary.resolve()), str(a), str(b), mode, str(count), str(depth),
           str(delay), str(permits), str(threshold), str(seed), str(prefix)]
    if rate:
        cmd.append(str(rate))
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)


def finished(process, expected=0):
    output, _ = process.communicate(timeout=300)
    if process.returncode != expected:
        raise RuntimeError(f"mirror exited with {process.returncode}: {output.strip()}")


def smoke(binary):
    with tempfile.TemporaryDirectory(prefix="csc720-", dir="/var/tmp") as directory:
        root = Path(directory)
        a, b = root / "a.dat", root / "b.dat"
        prepare([a, b], 1)
        offsets = None
        for mode in MODES:
            prefix = root / mode
            finished(run(binary, a, b, prefix, mode, 256, 8, 0, 1, 0, 720))
            result = summarize(prefix)
            rows = read_rows(Path(f"{prefix}-logical.csv"))
            trace = [row["offset"] for row in rows]
            offsets = trace if offsets is None else offsets
            require(trace == offsets, "the policies used different offsets")
            require(result["failed_logical"] == result["invalid_replicas"] == 0, mode)
            if mode in ("round-robin", "less-busy"):
                require(result["replica_reads"] == 256, mode)
            if mode == "round-robin":
                require(all(row["winner"] == row["id"] % 2 for row in rows), mode)
            if mode == "fixed":
                require(result["replica_reads"] == 512 and
                        result["peak_active_permits"] == 0, mode)
            if mode == "budget":
                require(result["peak_active_permits"] == 1 and
                        256 < result["replica_reads"] < 512, mode)

        prefix = root / "zero-permits"
        finished(run(binary, a, b, prefix, "budget", 64, 8, 0, 0, 0, 720))
        require(summarize(prefix)["replica_reads"] == 64, "zero permit cap")

        # One-record valid and corrupt files make every offset deterministic.
        a.write_bytes(bytes(BLOCK))
        b.write_bytes(b"x" * BLOCK)
        prefix = root / "one-invalid"
        finished(run(binary, a, b, prefix, "fixed", 32, 4, 0, 1, 0, 720))
        result = summarize(prefix)
        require(result["failed_logical"] == 0 and result["invalid_replicas"] == 32,
                "failed replica prevented a successful hedge")
        a.write_bytes(b"x" * BLOCK)
        prefix = root / "both-invalid"
        finished(run(binary, a, b, prefix, "budget", 32, 1, 0, 1, 0, 720), expected=2)
        result = summarize(prefix)
        require(result["failed_logical"] == 32 and result["replica_reads"] == 64,
                "both-invalid requests did not drain")
        completions = read_rows(Path(f"{prefix}-replica.csv"))
        require([row["permits_after_completion"] for row in completions] == [1, 0] * 32,
                "the permit must remain held until the second completion")

        a.write_bytes(bytes(BLOCK))
        b.write_bytes(bytes(BLOCK))
        prefix = root / "interrupt"
        process = run(binary, a, b, prefix, "fixed", 1000000, 32, 0, 1, 0, 720)
        time.sleep(.2)
        process.send_signal(signal.SIGINT)
        finished(process, expected=130)
        result = summarize(prefix)
        require(0 < result["logical_reads"] < 1000000 and result["failed_logical"] == 0,
                "interrupted run failed to drain cleanly")
        # Truncation is fault injection on temporary data, after the files passed startup checks.
        prefix = root / "paced-short-read"
        with run(binary, a, b, prefix, "disk-a", 32, 4, 0, 0, 0, 720, rate=100) as process:
            require(process.stdout.readline().startswith("Origin monotonic ns: "),
                    "paced reader failed to start")
            time.sleep(.05)
            a.write_bytes(b"")
            finished(process, expected=2)
        result = summarize(prefix)
        rows = read_rows(Path(f"{prefix}-logical.csv"))
        require(len(rows) == 32 and 0 < result["failed_logical"] <= 32, "short read did not fail")
        require(all(row["start_ns"] == i * 10_000_000 and
                    row["admitted_ns"] >= row["start_ns"] for i, row in enumerate(rows)),
                "paced starts or admissions do not match the arrival trace")
        require(any(row["result"] == 0 and not row["valid"]
                    for row in read_rows(Path(f"{prefix}-replica.csv"))),
                "short read completion was not logged")
    print("Smoke tests passed for all policies, paced arrivals, failure cases, and shutdown.")


@contextmanager
def interference(targets, depth, directory):
    processes = []
    with ExitStack() as stack:
        try:
            for index, target in enumerate(targets):
                log = stack.enter_context((directory / f"fio-{index}.txt").open("w"))
                args = ["fio", "--name=interference", f"--filename={target}",
                        "--ioengine=io_uring", "--direct=1", "--rw=randread", "--bs=4k",
                        f"--iodepth={depth}", "--time_based", "--runtime=86400",
                        "--readonly", "--eta=never"]
                processes.append(subprocess.Popen(args, stdout=log, stderr=log))
            if processes:
                time.sleep(.75)
            yield processes
        finally:
            for process in processes:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def experiment(args):
    if not args.smoke_only:
        require(args.a.stat().st_dev != args.b.stat().st_dev,
                "benchmark replicas must be on separate filesystems; use --smoke-only for WSL")
        require(args.repeats >= 3, "use at least three repetitions for benchmark runs")
    if args.interference != ["none"]:
        require(args.noise_a is not None and args.noise_b is not None,
                "provide --noise-a and --noise-b for interference")
        paths = [args.a, args.b, args.noise_a, args.noise_b]
        require(len({(p.stat().st_dev, p.stat().st_ino) for p in paths}) == len(paths),
                "all replica and interference files must be distinct")
        require(args.a.stat().st_dev == args.noise_a.stat().st_dev and
                args.b.stat().st_dev == args.noise_b.stat().st_dev,
                "each noise file must be on the same filesystem as its target replica")

    args.output.mkdir(parents=True, exist_ok=False)
    strategies = [("round-robin", 0, 0, 0), ("less-busy", 0, 0, 0)]
    strategies += [("fixed", delay, 0, 0) for delay in args.delays]
    strategies += [("budget", delay, cap, args.threshold)
                   for delay in args.delays for cap in args.permits]
    columns = None
    with (args.output / "summary.csv").open("w", newline="") as table:
        for load in args.depths:
            for scenario in args.interference:
                targets = {"none": [], "a": [args.noise_a], "b": [args.noise_b],
                           "both": [args.noise_a, args.noise_b]}[scenario]
                for repeat in range(args.repeats):
                    cases = list(strategies)
                    if scenario == "none" and load == args.depths[0] and args.threshold:
                        cases.append(("budget", args.delays[0], args.permits[0], 0))
                    # Rotate strategy order across repeats while holding offsets fixed.
                    shift = repeat % len(cases)
                    for mode, delay, cap, threshold in cases[shift:] + cases[:shift]:
                        case = f"d{load}-{scenario}-r{repeat}-{mode}-{delay}-{cap}-{threshold}"
                        directory = args.output / case
                        directory.mkdir()
                        prefix = directory / "run"
                        print(case, flush=True)
                        with interference(targets, args.noise_depth, directory) as processes:
                            require(all(p.poll() is None for p in processes),
                                    f"interference startup failed; see {directory}")
                            finished(run(args.binary, args.a, args.b, prefix, mode,
                                         args.count, load, delay, cap, threshold, args.seed))
                            require(all(p.poll() is None for p in processes),
                                    f"interference ended early; see {directory}")
                        summary = summarize(prefix)
                        require(summary["invalid_replicas"] == 0, f"invalid replica in {directory}")
                        row = {"case": case, "environment": "smoke" if args.smoke_only else "benchmark",
                               "mode": mode, "depth": load, "interference": scenario,
                               "repeat": repeat, "seed": args.seed, "delay_us": delay,
                               "permit_limit": cap, "threshold": threshold, **summary}
                        if columns is None:
                            columns = csv.DictWriter(table, fieldnames=row.keys())
                            columns.writeheader()
                        columns.writerow(row)
                        table.flush()


def calibration(args):
    args.output.mkdir(parents=True, exist_ok=False)
    prefix = args.output / "calibration"
    finished(run(args.binary, args.a, args.b, prefix, "less-busy",
                 args.count, args.depth, 0, 0, 0, args.seed))
    require(summarize(prefix)["invalid_replicas"] == 0, "calibration read failed")
    rows = read_rows(Path(f"{prefix}-logical.csv"))
    times = [(row["end_ns"] - row["start_ns"]) / 1000 for row in rows]
    for p in (.75, .90, .95):
        print(f"p{int(p * 100)} candidate hedge delay: {max(1, math.ceil(percentile(times, p)))} us")


def plot(summary, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with summary.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    groups = defaultdict(lambda: defaultdict(list))
    metrics = (("p99_us", "p99 read latency (µs)"),
               ("duplicate_fraction", "Duplicate reads per logical read"))
    for row in rows:
        label = row["mode"]
        if label in ("fixed", "budget"):
            label += f" {row['delay_us']} µs"
        if row["mode"] == "budget":
            label += f", permits {row['permit_limit']}, threshold {row['threshold']}"
        rate = int(row.get("offered_reads_per_sec", 0))
        groups[(rate, int(row["depth"]), row["interference"])][label].append(row)
    require(bool(groups), "summary has no measurements")
    output.mkdir(parents=True, exist_ok=True)
    for (rate, depth, scenario), policies in groups.items():
        fig, axes = plt.subplots(1, 2, figsize=(12, max(3, .37 * len(policies) + 1)))
        for axis, (metric, title) in zip(axes, metrics):
            axis.barh(list(policies), [median(float(r[metric]) for r in group)
                                      for group in policies.values()])
            axis.invert_yaxis()
            axis.set_xlabel(title)
        axes[1].tick_params(labelleft=False)
        load = f"{rate} offered reads/s" if rate else f"Depth {depth}"
        fig.suptitle(f"{load}, interference {scenario} (median across runs)")
        fig.tight_layout()
        label = f"rate-{rate}" if rate else f"depth-{depth}"
        fig.savefig(output / f"{label}-{scenario}.png", dpi=180)
        plt.close(fig)


    if "replicas_per_success" in rows[0]:
        tradeoff_plot(groups, output, plt)
    phases = summary.parent / "transition-phases.csv"
    if phases.is_file():
        transition_plot(rows, phases, output, plt)


def tradeoff_plot(groups, output, plt):
    no_noise = [(rate, depth, policies) for (rate, depth, case), policies in groups.items()
                if case == "none"]
    if not no_noise:
        return
    fig, axes = plt.subplots(1, len(no_noise), figsize=(5.8 * len(no_noise), 4.4),
                             squeeze=False)
    colors = {"round-robin": "#575d65", "less-busy": "#25842b",
              "fixed": "#c24a25", "budget": "#2b5aaa"}
    markers = {"round-robin": "s", "less-busy": "D", "fixed": "^", "budget": "o"}
    legend = {}
    for axis, (rate, depth, policies) in zip(axes[0], no_noise):
        for label, group in policies.items():
            mode = group[0]["mode"]
            x = [float(r["replicas_per_success"]) for r in group]
            y = [float(r["p99_us"]) / 1000 for r in group]
            axis.scatter(x, y, color=colors[mode], marker=markers[mode], alpha=.24)
            legend[mode] = axis.scatter(median(x), median(y), color=colors[mode],
                                        marker=markers[mode], s=55, label=mode)
        axis.set_title(f"{rate} offered reads/s" if rate else f"Depth {depth}")
        axis.set_xlabel("Replica reads per successful logical read")
        axis.set_ylabel("Logical p99 latency (ms)")
        axis.grid(alpha=.22)
    fig.legend(list(legend.values()), list(legend), loc="lower center", ncol=4)
    fig.suptitle("Tail latency and replica I/O without interference")
    fig.tight_layout(rect=(0, .09, 1, .95))
    fig.savefig(output / "p99-versus-replica-reads.png", dpi=180)
    plt.close(fig)


def transition_plot(runs, phases, output, plt):
    budget = {row["case"]: row for row in runs
              if row["interference"] == "transition" and row["mode"] == "budget"}
    if not budget:
        return
    groups = defaultdict(list)
    with phases.open(newline="") as stream:
        for phase in csv.DictReader(stream):
            run = budget.get(phase["case"])
            if run:
                key = (phase["phase_at_arrival"], int(run["permit_limit"]), int(run["threshold"]))
                groups[key].append(phase)

    permits = sorted({cap for _, cap, _ in groups})
    thresholds = sorted({threshold for _, _, threshold in groups}, reverse=True)
    fig, axes = plt.subplots(2, 2, figsize=(9.3, 6.7), sharex=True)
    for column, (phase, title) in enumerate((("a", "A under interference"),
                                             ("both", "Both drives under interference"))):
        axes[0, column].set_title(title)
        for row, (metric, label, scale) in enumerate((
            ("p99_us", "Logical p99 latency (ms)", 1000),
            ("replicas_per_success", "Replica reads per success", 1),
        )):
            axis = axes[row, column]
            for threshold in thresholds:
                samples = [groups[phase, cap, threshold] for cap in permits]
                values = [median(float(item[metric]) for item in group) / scale
                          for group in samples]
                style = {"color": "#295b97", "linestyle": "-"} if threshold else {
                    "color": "#ad4f25", "linestyle": "--"}
                axis.plot(permits, values, marker="o", label=f"Threshold {threshold or 'off'}",
                          **style)
            axis.set_ylabel(label)
            axis.grid(alpha=.22)
            axis.set_xticks(permits)
        axes[1, column].set_xlabel("Pair permits")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2)
    fig.suptitle("Threshold effect during the interference transition")
    fig.tight_layout(rect=(0, .08, 1, .95))
    fig.savefig(output / "transition-threshold.png", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    prep = command.add_parser("prepare")
    prep.add_argument("paths", type=Path, nargs="+")
    prep.add_argument("--mib", type=int, default=16)

    test = command.add_parser("smoke")
    test.add_argument("--binary", type=Path, default=Path("./mirror"))

    stats = command.add_parser("summarize")
    stats.add_argument("prefix", type=Path)

    for name in ("calibrate", "experiment"):
        sub = command.add_parser(name)
        sub.add_argument("a", type=Path)
        sub.add_argument("b", type=Path)
        sub.add_argument("output", type=Path)
        sub.add_argument("--binary", type=Path, default=Path("./mirror"))
        sub.add_argument("--count", type=int, default=10000)
        sub.add_argument("--seed", type=int, default=720)
        if name == "calibrate":
            sub.add_argument("--depth", type=int, default=8)
        else:
            sub.add_argument("--depths", type=int, nargs="+", default=[4, 16])
            sub.add_argument("--delays", type=int, nargs="+", default=[2000])
            sub.add_argument("--permits", type=int, nargs="+", default=[1, 2, 4])
            sub.add_argument("--threshold", type=int, default=8)
            sub.add_argument("--repeats", type=int, default=3)
            sub.add_argument("--interference", choices=INTERFERENCE_ORDER, nargs="+",
                             default=list(INTERFERENCE_ORDER))
            sub.add_argument("--noise-a", type=Path)
            sub.add_argument("--noise-b", type=Path)
            sub.add_argument("--noise-depth", type=int, default=4)
            sub.add_argument("--smoke-only", action="store_true")

    charts = command.add_parser("plot")
    charts.add_argument("summary", type=Path)
    charts.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.paths, args.mib)
        elif args.command == "smoke":
            smoke(args.binary)
        elif args.command == "summarize":
            for key, value in summarize(args.prefix).items():
                print(f"{key}: {value}")
        elif args.command == "calibrate":
            calibration(args)
        elif args.command == "experiment":
            experiment(args)
        else:
            plot(args.summary, args.output)
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
