#!/usr/bin/env python3
"""Run the three Milestone 3 studies on separate Linux block devices."""
import argparse
from contextlib import ExitStack
import csv
import hashlib
import json
import math
import mmap
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import threading
import time

from tools import BLOCK, percentile, read_rows, require, run, summarize


def shell(*args):
    return subprocess.check_output(args, text=True).strip()


def storage(path, wsl2=False):
    source = shell("findmnt", "-n", "-o", "SOURCE", "--target", str(path))
    if wsl2:
        match = re.fullmatch(r"([A-Za-z]):\\", source)
        require(match is not None, f"expected a Windows drive mount for {path}: {source}")
        letter = match.group(1).upper()
        disk = json.loads(shell("powershell.exe", "-NoProfile", "-Command",
                                f"$ErrorActionPreference='Stop'; Get-Partition -DriveLetter {letter} "
                                "| Get-Disk | Select-Object Number,FriendlyName,BusType "
                                "| ConvertTo-Json -Compress"))
        require(disk["BusType"] == "SATA", f"expected a SATA disk for {path}: {disk}")
        return {"source": source, "parent": disk["Number"], "drive": disk["FriendlyName"],
                "bus": disk["BusType"],
                "filesystem": shell("findmnt", "-n", "-o", "FSTYPE", "--target", str(path))}
    parent = shell("lsblk", "-n", "-d", "-o", "PKNAME", source)
    require(bool(parent), f"cannot identify a physical parent for {path}")
    drive = shell("lsblk", "-d", "-n", "-o", "TYPE,ROTA,MODEL,TRAN", f"/dev/{parent}")
    require(drive.split()[0] == "disk", f"expected a physical drive for {path}: {drive}")
    return {"source": source, "parent": parent, "drive": drive,
            "filesystem": shell("findmnt", "-n", "-o", "FSTYPE", "--target", str(path))}


class Noise:
    """One worker per outstanding slot, issuing aligned random direct reads."""

    def __init__(self, path, depth, seed, phase="initial"):
        self.path, self.depth, self.seed, self.phase = path, depth, seed, phase
        self.start_gate = threading.Event()
        self.stop = threading.Event()
        self.ready = threading.Barrier(depth + 1)
        self.records = [{} for _ in range(depth)]
        self.threads = [threading.Thread(target=self.work, args=(index,), daemon=True)
                        for index in range(depth)]

    def work(self, index):
        record = self.records[index]
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_DIRECT)
            try:
                blocks = os.fstat(fd).st_size // BLOCK
                rng = random.Random(self.seed + index)
                with mmap.mmap(-1, BLOCK) as buf:
                    self.ready.wait(timeout=5)
                    self.start_gate.wait()
                    record["first_issue_ns"] = time.monotonic_ns()
                    done = 0
                    while not self.stop.is_set():
                        require(os.preadv(fd, [buf], rng.randrange(blocks) * BLOCK) == BLOCK,
                                f"short interference read from {self.path}")
                        done += 1
                    record.update(reads=done, end_ns=time.monotonic_ns())
            finally:
                os.close(fd)
        except (OSError, ValueError, threading.BrokenBarrierError) as exc:
            record["error"] = str(exc)
            self.ready.abort()

    def __enter__(self):
        for worker in self.threads:
            worker.start()
        try:
            self.ready.wait(timeout=5)
        except threading.BrokenBarrierError:
            self.stop.set()
            self.start_gate.set()
            for worker in self.threads:
                worker.join()
            raise ValueError(f"could not prepare interference on {self.path}: {self.records}")
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.start_gate.set()
        for worker in self.threads:
            worker.join()

    def check(self):
        require(all(row.get("reads", 0) > 0 and "error" not in row for row in self.records),
                f"interference did not complete on {self.path}: {self.records}")


def write_table(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def measured(args, prefix, mode, count, depth, delay=0, cap=0, threshold=0, rate=0,
             scenario="none"):
    origin = None
    noises = []
    with ExitStack() as cleanup:
        if scenario in ("a", "both", "transition"):
            noises.append(cleanup.enter_context(Noise(args.noise_a, args.noise_depth, args.seed + 1000)))
        if scenario in ("b", "both", "transition"):
            phase = "transition" if scenario == "transition" else "initial"
            noises.append(cleanup.enter_context(Noise(args.noise_b, args.noise_depth,
                                                       args.seed + 2000, phase)))
        for noise in noises:
            if noise.phase == "initial":
                noise.start_gate.set()
        if noises:
            time.sleep(0.2)
        with run(args.binary, args.a, args.b, prefix, mode, count, depth, delay,
                 cap, threshold, args.seed, rate) as process:
            try:
                header = process.stdout.readline()
                require(header.startswith("Origin monotonic ns: "), "read engine failed to start")
                origin = int(header.split(": ")[1])
                if scenario == "transition":
                    target = origin + int(args.seconds * 500_000_000)
                    time.sleep(max(0, (target - time.monotonic_ns()) / 1e9))
                    require(process.poll() is None, "reader finished before transition")
                    noises[-1].start_gate.set()
                output, _ = process.communicate(timeout=max(60, args.seconds * 20))
                require(process.returncode == 0, f"reader exited {process.returncode}: {output}")
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=15)

    for noise in noises:
        noise.check()
    transition = (min(row["first_issue_ns"] for row in noises[-1].records) - origin
                  if scenario == "transition" else None)
    summary = summarize(prefix)
    require(summary["logical_reads"] == count and summary["invalid_replicas"] == 0,
            f"incomplete or invalid foreground reads: {prefix}")
    Path(f"{prefix}-environment.json").write_text(json.dumps({
        "origin_monotonic_ns": origin, "transition_ns": transition,
        "background": [{"file": str(n.path), "workers": n.records} for n in noises],
    }, indent=2) + "\n")
    return summary, transition


def calibrate(args):
    folder = args.output / "calibration"
    folder.mkdir()
    rows = []
    for mode in ("disk-a", "disk-b", "less-busy"):
        for repeat in range(args.repeats):
            prefix = folder / f"{mode}-r{repeat}"
            result, _ = measured(args, prefix, mode, 256, 1)
            rows.append({"mode": mode, "repeat": repeat, **result})
    write_table(folder / "summary.csv", rows)

    capacity = sum(sum(row["useful_reads_per_sec"] for row in rows if row["mode"] == mode)
                   / args.repeats for mode in ("disk-a", "disk-b"))
    rates = [max(1, round(capacity * share)) for share in (0.35, 0.70)]
    require(rates[0] < rates[1], "calibration could not distinguish the two offered rates")
    prefix = folder / "paced-moderate"
    measured(args, prefix, "less-busy", max(256, 3 * rates[1]), args.depth, rate=rates[1])
    samples = [(row["end_ns"] - row["start_ns"]) / 1000
               for row in read_rows(Path(f"{prefix}-logical.csv"))]
    candidates = [math.ceil(percentile(samples, p)) for p in (.75, .90, .95)]
    trials = []
    for delay in sorted(set(candidates)):
        result, _ = measured(args, folder / f"fixed-{delay}", "fixed", max(256, 3 * rates[1]),
                             args.depth, delay=delay, rate=rates[1])
        trials.append({"delay_us": delay, **result})
    write_table(folder / "hedge-candidates.csv", trials)
    return rates, candidates


def phase_rows(prefix, transition, case):
    logical = read_rows(Path(f"{prefix}-logical.csv"))
    replicas = read_rows(Path(f"{prefix}-replica.csv"))
    rows = []
    for phase, before in (("a", True), ("both", False)):
        selected = [row for row in logical if (row["start_ns"] < transition) == before]
        ids = {row["id"] for row in selected}
        attempts = [row for row in replicas if row["id"] in ids]
        require(bool(selected), f"no arrivals in phase {phase} for {case}")
        rows.append({
            "case": case, "phase_at_arrival": phase, "logical_reads": len(selected),
            "p99_us": percentile([(r["end_ns"] - r["start_ns"]) / 1000 for r in selected], .99),
            "replicas_per_success": len(attempts) / len(selected),
            "alternate_wins": sum(r["attempt"] == 2 and r["winner"] for r in attempts),
            "admitted_after_transition": sum(r["admitted_ns"] >= transition for r in selected),
            "finished_after_transition": sum(r["end_ns"] >= transition for r in selected),
        })
    return rows


def experiment(args):
    if args.wsl2:
        require("wsl2" in shell("uname", "-r").lower(), "--wsl2 requires a WSL2 kernel")
    drives = [storage(path, args.wsl2) for path in (args.a, args.b)]
    require(drives[0]["parent"] != drives[1]["parent"], "replicas share a physical parent")
    files = (args.a, args.b, args.noise_a, args.noise_b)
    require(len({(p.stat().st_dev, p.stat().st_ino) for p in files}) == 4,
            "replica and interference files must be distinct")
    require(all(replica.stat().st_dev == noise.stat().st_dev
                for replica, noise in zip(files[:2], files[2:])),
            "each noise file must be on its replica filesystem")
    require(all(p.stat().st_size >= BLOCK and p.stat().st_size % BLOCK == 0 for p in files),
            "use aligned benchmark files")
    digests = []
    for path in files[:2]:
        with path.open("rb") as stream:
            digests.append(hashlib.file_digest(stream, "sha256").hexdigest())
    require(digests[0] == digests[1], "replica SHA-256 hashes differ")

    args.output.mkdir(parents=True, exist_ok=False)
    rates, candidates = calibrate(args)
    delay = candidates[1]
    settings = {
        "kernel": shell("uname", "-srmo"), "drives": drives, "replica_sha256": digests[0],
        "files": {str(p): p.stat().st_size for p in files}, "rates": rates,
        "candidate_delays_us": candidates, "selected_delay_us": delay,
        "delay_rule": "p90 of the independent moderate-load less-busy calibration",
        "seconds": args.seconds, "repeats": args.repeats, "seed": args.seed,
        "logical_depth": args.depth, "physical_depth": 4 * args.depth,
        "noise_depth_per_drive": args.noise_depth, "permit_counts": args.permits,
        "threshold": args.threshold, "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "cache_protocol": "4 KiB O_DIRECT for all reads, identical traces and noise warmup; device caches left enabled",
    }
    (args.output / "environment.json").write_text(json.dumps(settings, indent=2) + "\n")

    regular = [("round-robin", 0, 0, 0), ("less-busy", 0, 0, 0), ("fixed", delay, 0, 0)]
    regular += [("budget", delay, cap, args.threshold) for cap in args.permits]
    conditions = [(rate, scenario) for rate in rates for scenario in ("none", "a", "b", "both")]
    conditions.append((rates[1], "transition"))
    runs = args.output / "runs"
    runs.mkdir()
    traces = {}
    transition_rows = []
    with (args.output / "summary.csv").open("w", newline="") as stream:
        writer = None
        for rate, scenario in conditions:
            configs = regular.copy()
            if scenario == "transition":
                configs += [("budget", delay, cap, 0) for cap in args.permits]
            for repeat in range(args.repeats):
                shift = repeat % len(configs)
                for mode, hedge_delay, cap, threshold in configs[shift:] + configs[:shift]:
                    case = f"rate{rate}-{scenario}-r{repeat}-{mode}-{hedge_delay}-{cap}-{threshold}"
                    print(case, flush=True)
                    folder = runs / case
                    folder.mkdir()
                    prefix = folder / "run"
                    metrics, transition = measured(
                        args, prefix, mode, round(rate * args.seconds), args.depth,
                        hedge_delay, cap, threshold, rate, scenario)
                    logical = read_rows(Path(f"{prefix}-logical.csv"))
                    trace = [(r["start_ns"], r["offset"]) for r in logical]
                    require(all(start == i * 1_000_000_000 // rate
                                for i, (start, _) in enumerate(trace)), f"arrival mismatch: {case}")
                    trace_hash = hashlib.sha256(repr(trace).encode()).hexdigest()
                    require(traces.setdefault(rate, trace_hash) == trace_hash, f"trace mismatch: {case}")
                    if mode == "budget":
                        require(metrics["peak_active_permits"] <= cap, f"permit overrun: {case}")
                    if transition is not None:
                        transition_rows.extend(phase_rows(prefix, transition, case))
                    row = {"case": case, "environment": "wsl2" if args.wsl2 else "native-linux", "mode": mode,
                           "depth": args.depth, "interference": scenario, "repeat": repeat,
                           "seed": args.seed, "delay_us": hedge_delay, "permit_limit": cap,
                           "threshold": threshold, "offered_reads_per_sec": rate,
                           "trace_sha256": trace_hash, "transition_ns": transition, **metrics}
                    if writer is None:
                        writer = csv.DictWriter(stream, fieldnames=row.keys(), lineterminator="\n")
                        writer.writeheader()
                    writer.writerow(row)
                    stream.flush()
    write_table(args.output / "transition-phases.csv", transition_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for path in ("a", "b", "noise_a", "noise_b", "output"):
        parser.add_argument(path, type=Path)
    parser.add_argument("--binary", type=Path, default=Path("./mirror"))
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--noise-depth", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--permits", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--threshold", type=int, default=1)
    parser.add_argument("--seed", type=int, default=720)
    parser.add_argument("--wsl2", action="store_true",
                        help="resolve Windows-mounted SATA drives through the host under WSL2")
    args = parser.parse_args()
    if (args.seconds < 1 or not 1 <= args.depth <= 1024 or args.noise_depth < 1
            or args.repeats < 3 or len(set(args.permits)) not in (2, 3)
            or len(set(args.permits)) != len(args.permits) or not all(1 <= cap <= 4096 for cap in args.permits)
            or not 1 <= args.threshold < args.depth):
        parser.error("use at least 1 second, three repeats, two or three distinct positive permit counts, and a threshold below depth")
    try:
        experiment(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
