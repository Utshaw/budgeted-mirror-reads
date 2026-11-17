"""Replay selected native Linux cases under WSL2 at identical rates and hedge delays."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from linux_experiment import measured, storage, write_table
from tools import read_rows, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native_results", type=Path)
    parser.add_argument("wsl_results", type=Path)
    parser.add_argument("--binary", type=Path, default=Path("./mirror"))
    args = parser.parse_args()
    native = json.loads((args.native_results / "environment.json").read_text())
    wsl = json.loads((args.wsl_results / "environment.json").read_text())
    # The main runner records files in replica A, replica B, noise A, noise B order.
    args.a, args.b, args.noise_a, args.noise_b = map(Path, wsl["files"])
    require([storage(path, True) for path in (args.a, args.b)] == wsl["drives"],
            "host disk mapping changed since calibration")
    args.seconds = native["seconds"]
    args.seed = native["seed"]
    args.noise_depth = native["noise_depth_per_drive"]
    with (args.native_results / "summary.csv").open(newline="") as stream:
        cases = [r for r in csv.DictReader(stream)
                 if int(r["offered_reads_per_sec"]) == max(native["rates"])
                 and r["interference"] in ("none", "both")
                 and (r["mode"] != "budget" or (r["permit_limit"], r["threshold"]) == ("2", "1"))]
    require(len(cases) == 8 * native["repeats"], "unexpected native replay matrix")
    folder = args.wsl_results / "native-rate-replay"
    folder.mkdir()
    rows = []
    for case in cases:
        name = case["case"]
        prefix = folder / name / "run"
        prefix.parent.mkdir()
        print(name, flush=True)
        metrics, _ = measured(args, prefix, case["mode"], int(case["logical_reads"]),
                              int(case["depth"]), int(case["delay_us"]), int(case["permit_limit"]),
                              int(case["threshold"]), int(case["offered_reads_per_sec"]),
                              case["interference"])
        trace = [(r["start_ns"], r["offset"]) for r in read_rows(Path(f"{prefix}-logical.csv"))]
        digest = hashlib.sha256(repr(trace).encode()).hexdigest()
        require(digest == case["trace_sha256"], f"native arrival or offset mismatch: {name}")
        rows.append({**case, "environment": "wsl2", "trace_sha256": digest, **metrics})
    write_table(folder / "summary.csv", rows)


if __name__ == "__main__":
    main()
