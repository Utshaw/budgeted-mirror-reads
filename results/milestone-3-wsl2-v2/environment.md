# WSL2 benchmark environment

| Item | Recorded configuration |
|---|---|
| Date | November 17, 2026, America/Chicago |
| Host | Windows 11 Education, build 26300, Intel Core i7-9700 |
| Guest | Ubuntu 24.04.5 LTS, 6.18.58.1-microsoft-standard-WSL2, x86-64, eight available CPUs |
| Build | GCC 13.3.0, C++20, -O2, liburing 2.5, Python 3.12.3 |
| Replica A | Windows disk 0, D:, NTFS, WDC WD10EZEX-75WN4A0 SATA HDD, WSL mount /mnt/d |
| Replica B | Windows disk 1, E:, NTFS, WDC WD10EZEX-75WN4A0 SATA HDD, WSL mount /mnt/e |
| Storage path | WSL2 9p/DrvFS to Windows NTFS. The Windows volume serials CAB00CAD and AEB6365E match the low 32 bits of the recorded native volume identifiers in A/B order. Logs were written to the guest ext4 filesystem and copied into the repository afterward. |
| Input data | One 512 MiB replica and one separate 512 MiB noise file on each drive. The replica SHA-256 matches the native dataset. |
| Reads | Aligned 4 KiB random reads, foreground io_uring with O_DIRECT, background O_DIRECT preadv. Two workers per active drive, 200 ms warmup, no explicit cache flush. |
| Main matrix | Seed 720, logical depth 8, physical cap 32, three seconds of arrivals, three repetitions. Interference on neither, A, B or both drives, plus an A-to-both transition at moderate load. Permit counts 1, 2 and 4, threshold 1 with a threshold-disabled transition comparison. |
| Calibration | Single-drive depth-one trials and a paced less-busy trial. The p75/p90/p95 candidates were 267/324/350 µs. The p90 rule selected 324 µs. The two offered rates were 3,449 and 6,898 reads/s. |
| Native-rate replay | Separate 24-run set at 231 reads/s, 9,214 µs hedge delay, no interference or both drives active, three repetitions of round-robin, less-busy, fixed and budget with two permits. |

Windows Performance Monitor sampled the physical disk reads/s counters for disks 0 and 1 during two light-load windows, first with no interference and then with both drives targeted. All 28 valid one-second intervals recorded zero on both disks. Each initial counter sample lacks a preceding observation. The guest completed thousands of reads/s over this period. This supports a cache-served interpretation for the sampled window. The counters cover the host disks and were sampled for only part of the study. The native study accessed these volumes through Linux ntfs3. [No-interference counters](host-reads.csv) · [Both-drive counters](host-reads-both.csv) · [Recorded runner settings](environment.json)
