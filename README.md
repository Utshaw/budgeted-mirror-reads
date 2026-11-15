# Budgeted Mirror Reads

This prototype uses C++20, liburing, and 4 KiB aligned direct reads to compare four policies on two identical files. Use WSL 2 to develop and check correctness. Run the final latency experiments on Linux with two independent physical HDDs.

## Build and test in WSL 2

Open PowerShell and start Ubuntu with this command.

    wsl -d Ubuntu-24.04

In Ubuntu, run the following commands. The source is on the Windows Desktop and the smoke-test files are created temporarily on Ubuntu's ext4 filesystem.

    cd /mnt/c/Users/fu774s/Desktop/budgeted-mirror-reads
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

Ties use the same alternating order as round-robin. Each logical request uses the same block offset for both replicas. The first verified 4 KiB completion wins. If every issued replica fails or returns incorrect data, the logical request fails. A replica with a visible completion is processed before a due hedge is issued. A completion that arrives after the last check can still race with hedge submission. Every issued operation is drained and counted. Each read owns an aligned buffer until it completes, and a budget permit stays held until both operations finish.

Logical depth controls how many unresolved logical reads can be admitted concurrently. A shared safety limit of four times that depth applies to physical reads in flight, including losers. A delayed hedge blocked by the budget or threshold can become eligible later if the original is still pending. Read offsets are generated from the same seed for each policy so the logical offset sequence matches for comparisons with identical file sizes and counts. Load is closed-loop, so admission times depend on prior completions.

## Run the final experiments on Linux

First confirm that your two mount points map to separate physical HDDs and can each complete direct I/O. Two partitions on one drive can have different filesystem identifiers, so check the physical parents with lsblk. Use separate files for benchmark reads and interference. The paths below are examples. The directories must already exist and be writable.

    lsblk -o NAME,PKNAME,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINTS
    python3 tools.py prepare /mnt/hdd-a/mirror.dat /mnt/hdd-b/mirror.dat --mib 1024
    python3 tools.py prepare /mnt/hdd-a/noise.dat /mnt/hdd-b/noise.dat --mib 1024
    python3 tools.py calibrate /mnt/hdd-a/mirror.dat /mnt/hdd-b/mirror.dat results/calibration --depth 4

Pick a candidate delay from calibration. The command below uses 2000 microseconds as an example. Add more delay values after the option to test a sweep. Use a fresh output directory for every experiment.

    python3 tools.py experiment /mnt/hdd-a/mirror.dat /mnt/hdd-b/mirror.dat results/final \
      --noise-a /mnt/hdd-a/noise.dat --noise-b /mnt/hdd-b/noise.dat \
      --depths 4 16 --delays 2000 --permits 1 2 4 --threshold 8 --repeats 3
    python3 tools.py plot results/final/summary.csv results/final/plots
    python3 analyze.py results/final/summary.csv

The experiment runs with no interference, interference on A, interference on B, and interference on both. It rotates policy order across repetitions and adds a threshold-disabled budget case at the first depth and delay with the first permit limit. The summary reports p50 and p99 logical latency for successful reads, useful logical reads per second including final drain time, completed replica reads and bytes, duplicate fraction, peak permits, and p99 loser cleanup time among successful hedged reads. The raw logical log records when each request first returned and when its final replica drained. The replica log records the read result, data verification, winning attempt, and active permits at submission and after completion. A logical log row with issued equal to two and drained_ns greater than end_ns shows a result returned while a second read was still outstanding.

For a WSL trial of the experiment script, use files on Ubuntu ext4 and add --smoke-only. Use --interference none to skip the noise-file arguments. These trials are labeled smoke in summary.csv. Check the storage layout and recalibrate on the native Linux machine before collecting measurements for the report. Record the OS and kernel, drive models, mount points and filesystems, test sizes, and all experiment settings alongside the report.

## WSL Milestone 3 results

The local results are in results/milestone-3-wsl. The report, environment notes, plots, CSV tables, and raw logs document the WSL evaluation. The two HDDs will need their own calibration and experiment run after transfer.

## Transfer to native Linux

Copy mirror.cpp, Makefile, tools.py, analyze.py, and README.md to the Linux machine or add them to your team's Git repository. Run make on the target and regenerate the data files on both HDDs. The project does not require migrating the WSL installation or copying its virtual disk.
