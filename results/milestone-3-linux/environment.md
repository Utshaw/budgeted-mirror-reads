# Linux Benchmark Environment

| Item | Configuration |
| --- | --- |
| Experiment date | November 15, 2026, America/Chicago |
| Operating system | Ubuntu 24.04.5 LTS, native Linux 7.0.0-43-generic, x86-64 |
| CPU | Intel Core i7-9700, eight logical CPUs available to all foreground and background runs |
| Build | GCC 13.3, C++20, -O2, liburing 2.5 |
| Drive A | WDC WD10EZEX-75WN4A0, 1 TB rotational SATA, /dev/sda2, ntfs3, ATA port 3 |
| Drive B | WDC WD10EZEX-75WN4A0, 1 TB rotational SATA, /dev/sdb2, ntfs3, ATA port 4 |
| I/O path | Separate physical disks and SATA ports on the same PCI SATA controller (0000:00:17.0), mq-deadline on both, device queue depth 32 on each |
| Files | One immutable 512 MiB replica and one distinct 512 MiB interference file per drive. Replica hashes match. |
| Read setup | 4 KiB aligned random reads. Foreground uses io_uring and O_DIRECT. Each affected disk has two background workers issuing O_DIRECT preadv reads on its interference file. |
| Cache preparation | Every foreground run uses the same deterministic offset stream for its rate and direct reads. Interference starts with a 200 ms warmup on its initially active drives. Device caches remain enabled. |
| Limits | Logical depth 8, shared foreground outstanding-I/O cap 32, same buffer allocation strategy and CPU affinity for all four policies |
| Calibration | Three depth-one runs per individual drive and for the mirrored less-busy baseline. A separate paced less-busy run selected the p90 delay. Fixed-delay trials measured all three candidates. |
| Main matrix | 116 and 231 arrivals/s, 3 s of arrivals per run, three repetitions, seed 720, 9,214 µs hedge delay, budgets 1/2/4, alternate outstanding threshold 1 |
| Transition | A active before foreground time zero. B starts issuing around 1.5 s while A stays active. Actual first-issue timestamps and background counts are kept with the raw logs. |

The two NTFS volumes were mounted with the desktop disk service using their existing filesystems. The experiment used fresh files inside dedicated directories. The file contents are reproducible with `tools.py prepare`. See [environment.json](environment.json) for exact files, hashes, and machine-readable settings. Drive behavior includes effects of this filesystem and shared controller.
