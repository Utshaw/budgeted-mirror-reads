# Windows cache control on the two benchmark HDDs

On November 17, 2026, all 6,144 unbuffered 4 KiB reads produced 6,144 host physical-disk reads. Each of the twelve 512-request trials recorded exactly 512 disk reads. The per-trial p99 ranged from 9.79 to 10.08 ms. This is a queue-depth-one Windows storage reference for these files. The WSL2 policy suite in the parent folder still used DrvFS.

| Replica | Windows unbuffered median p99 | Native Linux direct median p99 |
|---|---:|---:|
| A (D:) | 9.88 ms | 10.18 ms |
| B (E:) | 9.92 ms | 10.19 ms |

Each number is a median across three repetitions. Both tests used aligned random 4 KiB reads. The programs, trace generators, and per-run request counts differed, so the small cross-platform differences include those effects. The native measurements are in [calibration/summary.csv](../../milestone-3-linux/calibration/summary.csv).

## Method

The script opened the existing replica and noise files read-only on both drives. Each trial issued synchronous 4 KiB reads through a page-aligned buffer, timed the seek and read, and checked each block's embedded offset. Only the open flag differed within a pair. Windows' FILE_FLAG_NO_BUFFERING requests system-cache bypass for that handle. Firmware caching remained enabled. The physical read count is the change in the raw cumulative Windows PhysicalDisk read counter for the whole target disk over each trial.

Each file had three pairs with seeds 720, 721 and 722, with identical offsets in both members of a pair. Each pair began with an untimed buffered pass. For the first and third pairs the measured buffered pass came first and incurred zero disk reads. For the middle pair the unbuffered pass came first and the subsequent buffered pass incurred 511 disk reads out of 512 on each file. A buffered handle permits caching, and actual cache residency depended on the sequence. See [per-trial measurements](windows-cache-baseline.csv).

## Repeat

From this directory, run the following in Windows PowerShell with the benchmark files still in the original locations. Pick a fresh output filename for each measurement.

```powershell
.\measure-cache.ps1 -Output .\repeat-01.csv
```

For comparison of future WSL2 policy runs, collect device-level counters during calibration and throughout the matrix. A depth-one unbuffered control should issue approximately one host disk read per logical read, and single-drive p99 on this pair was about 10 ms. The mirror application has independent foreground and background readers, so both paths need verified cache behavior.