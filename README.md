# Budgeted Mirror Reads

This prototype uses C++20, liburing, and 4 KiB aligned direct reads to compare four policies on two identical files. Use WSL 2 to develop and check correctness. Use the native Linux runner for measurements on two separate physical HDDs.

## Build and test in WSL 2

Open PowerShell and start Ubuntu with this command.

    wsl -d Ubuntu-24.04

In Ubuntu, run these commands from your checkout. The smoke tests create temporary files under Ubuntu's `/var/tmp`.

    cd /path/to/budgeted-mirror-reads
    make
    make test

On a new Ubuntu machine, install the same dependencies before building.

    sudo apt update
    sudo apt install build-essential liburing-dev python3 fio git python3-matplotlib

## Run a small example

Use a new directory on the Linux filesystem for data. The generator creates equally sized identical files containing deterministic records and refuses to overwrite existing files.

    trial=$(mktemp -d /var/tmp/csc720-example.XXXXXX)
    python3 tools.py prepare "$trial/a.dat" "$trial/b.dat" --mib 16
    ./mirror "$trial/a.dat" "$trial/b.dat" budget 10000 8 50 2 4 720 "$trial/run"
    python3 tools.py summarize "$trial/run"

The binary arguments are replica A, replica B, policy, logical read count, logical queue depth, hedge delay in microseconds, permit limit, alternate-drive outstanding-read threshold, seed, and log prefix. Use a threshold of zero to disable only the alternate-drive threshold. A permit limit of zero disables duplicates in budget mode. Send Ctrl+C to stop admission and drain submitted operations. The binary returns 130 after a drained interruption, 2 after a completed run containing logical failures, and 1 for setup or runtime errors.

## How the policies work

| Policy | Original replica | Duplicate |
| --- | --- | --- |
| round-robin | Alternates between A and B | None |
| less-busy | Drive with fewer outstanding reads | None |
| fixed | Drive with fewer outstanding reads | One after the configured delay while the original is pending |
| budget | Drive with fewer outstanding reads | One after the delay if a permit is free and the alternate drive is below its threshold |

The less-busy selector alternates between A and B on ties. Each logical request uses the same block offset for both replicas. The first verified 4 KiB completion wins. If every issued replica fails or returns incorrect data, the logical request fails. A replica with a visible completion is processed before a due hedge is issued. A completion that arrives after the last check can still race with hedge submission. Every issued operation is drained and counted. Each read owns an aligned buffer until it completes, and a budget permit stays held until both operations finish.

Logical depth controls how many unresolved logical reads can be admitted concurrently. A shared safety limit of four times that depth applies to physical reads in flight, including losers. A delayed hedge blocked by the budget or threshold can become eligible later if the original is still pending. Read offsets are generated from the same seed for each policy. With no optional offered-rate argument, load is closed-loop. With a rate, the engine replays arrivals at fixed intervals and includes any admission wait in logical latency. In the logical CSV, `start_ns` is the arrival and `admitted_ns` is when the engine admitted the request. The `disk-a` and `disk-b` modes measure each disk alone.

## Run Milestone 3 on native Linux

Use writable directories on separate physical drives for the replica and interference files. The runner verifies the physical parents, filesystem placement, and replica hashes. It runs single-drive measurements and hedge-delay calibration, then compares all four policies under no interference, A-only, B-only, and both-drive interference at two offered rates. At the moderate rate it also runs an A-to-both transition and repeats each budget setting with the alternate-drive threshold disabled. Each comparison uses the same arrivals, offsets, logical depth, and physical depth. Interference uses distinct files and separate direct-read workers.

```sh
make
make test
lsblk -o NAME,PKNAME,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINTS
python3 tools.py prepare /mnt/hdd-a/mirror.dat /mnt/hdd-b/mirror.dat --mib 512
python3 tools.py prepare /mnt/hdd-a/noise.dat /mnt/hdd-b/noise.dat --mib 512
python3 linux_experiment.py /mnt/hdd-a/mirror.dat /mnt/hdd-b/mirror.dat \
    /mnt/hdd-a/noise.dat /mnt/hdd-b/noise.dat results/new-linux-run \
    --seconds 3 --repeats 3 --depth 8 --noise-depth 2 --permits 1 2 4 --threshold 1
python3 analyze.py results/new-linux-run/summary.csv
python3 tools.py plot results/new-linux-run/summary.csv results/new-linux-run/plots
```

The built-in defaults use short runs suitable for reproducing the included measurement set. Increase `--seconds` to obtain more p99 samples. Each run starts fresh, and the output directory must be new. Use `summary.csv` for foreground totals, `transition-phases.csv` for the two phases, and each run's environment JSON for background read counts and first-issue timestamps. The logical and replica CSVs retain each request and completion, and the throughput denominator includes the final drain. Replica counts and bytes describe observed requests and completed bytes.

The WSL-oriented `tools.py experiment` runner remains available for a closed-loop functional trial. Use files on Linux ext4, add `--smoke-only`, and use `--interference none` to run without fio.

## Linux Milestone 3 results

See [results/milestone-3-linux](results/milestone-3-linux/) for the collected run, including the study report, environment notes, calibration, CSV tables, plots, and raw logs.

## WSL2 Milestone 3 results

The [WSL2 report and native Linux comparison](results/milestone-3-wsl2-v2/report.md) uses the same calibration, policy matrix, transition timing, analysis, and result layout as the native study. The WSL2 runner maps each Windows drive letter to its host SATA disk through PowerShell. Use two distinct host disks, one replica and one noise file per disk, and a fresh output directory on the WSL filesystem.

From the repository root in WSL2, after building and testing:

```sh
a=$(mktemp -d /mnt/d/mirror-reads.XXXXXX)
b=$(mktemp -d /mnt/e/mirror-reads.XXXXXX)
out=$(mktemp -d)/milestone-3-wsl2-v2
python3 tools.py prepare "$a/mirror.dat" "$b/mirror.dat" --mib 512
python3 tools.py prepare "$a/noise.dat" "$b/noise.dat" --mib 512
python3 linux_experiment.py --wsl2 "$a/mirror.dat" "$b/mirror.dat" \
    "$a/noise.dat" "$b/noise.dat" "$out"
python3 analyze.py "$out/summary.csv"
python3 tools.py plot "$out/summary.csv" "$out/plots"
python3 replay_linux_cases.py results/milestone-3-linux "$out"
```

## Transfer to native Linux

Clone the `linux` branch or transfer its source files and build instructions. Run make on the target and regenerate the data files on both HDDs. The project does not require migrating the WSL installation or copying its virtual disk.
