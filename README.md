# Budgeted Mirror Reads

A C++20 read engine that compares four policies using identical files on two separate physical drives and asynchronous 4 KiB direct reads.

## Policies

| Policy | Initial drive | Backup read |
| --- | --- | --- |
| Round-robin | Alternates A and B | None |
| Less-busy-first | Fewer outstanding reads, alternating ties | None |
| Fixed-delay | Less-busy-first | One backup after the delay if the original is pending |
| Budget-limited | Less-busy-first | Same delay, plus a free pair permit and alternate-drive threshold check |

The first verified result supplies the answer. Every issued read completes and is counted. A pair keeps its permit until both reads finish.

## Run the experiment on Linux

Install dependencies and build from the repository root.

```sh
sudo apt update
sudo apt install build-essential liburing-dev python3 python3-matplotlib
make
```

Replace the paths below with existing writable directories on two separate physical drives. Use fresh filenames and a new results directory.

```sh
python3 tools.py prepare /mnt/hdd-a/mirror.dat /mnt/hdd-b/mirror.dat --mib 512
python3 tools.py prepare /mnt/hdd-a/noise.dat /mnt/hdd-b/noise.dat --mib 512
python3 linux_experiment.py /mnt/hdd-a/mirror.dat /mnt/hdd-b/mirror.dat \
    /mnt/hdd-a/noise.dat /mnt/hdd-b/noise.dat results/new-linux-run
python3 analyze.py results/new-linux-run/summary.csv
python3 tools.py plot results/new-linux-run/summary.csv results/new-linux-run/plots
```

The runner calibrates the read rates and hedge delay, compares all policies under background interference, and repeats each configuration three times. Results include request logs, CSV summaries, and plots.
