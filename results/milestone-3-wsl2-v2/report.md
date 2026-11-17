# Milestone 3 on WSL2 and native Linux

The same two NTFS volumes backed both studies. The WSL2 application reached a much higher read rate through the Windows-mounted volumes. Across two light-load samples, Windows recorded zero physical reads/s on both disks in all 28 valid one-second intervals. This is consistent with host caching. The timings measure the complete application-visible storage path. They cannot isolate virtualization overhead or establish a change in mechanical HDD speed. [Environment and counter sample](environment.md)

## Replaying the native Linux workload

For the clearest comparison, we replayed 24 native cases on WSL2 at 231 reads/s, with three repetitions, the native 9.214 ms hedge delay and the same 693 scheduled arrivals and block offsets per run. All 24 trace hashes matched. Each table entry is the median of three runs. Duplicate rates count extra replica reads per 100 logical reads. Background workers used the same depth and independently completed as much work as each storage path allowed.

| Interference | Policy | Linux p99 (ms) | WSL2 p99 (ms) | Linux duplicates | WSL2 duplicates | Linux useful reads/s | WSL2 useful reads/s |
|---|---|---:|---:|---:|---:|---:|---:|
| none | round-robin | 11.818 | 0.492 | 0.0% | 0.0% | 231.0 | 231.3 |
| none | less-busy | 12.773 | 0.596 | 0.0% | 0.0% | 231.0 | 231.3 |
| none | fixed | 17.344 | 0.541 | 20.2% | 0.0% | 231.1 | 231.3 |
| none | Budget 2 | 13.365 | 0.511 | 1.2% | 0.0% | 231.1 | 231.3 |
| both | round-robin | 59.782 | 1.495 | 0.0% | 0.0% | 228.7 | 231.3 |
| both | less-busy | 56.417 | 0.575 | 0.0% | 0.0% | 230.0 | 231.3 |
| both | fixed | 37.800 | 0.543 | 63.5% | 0.0% | 228.8 | 231.3 |
| both | Budget 2 | 59.098 | 0.883 | 5.8% | 0.0% | 229.6 | 231.3 |

With both drives targeted, fixed-delay hedging issued a median of 63.5 extra reads per 100 logical reads on native Linux and 0.0 on WSL2. The same absolute hedge delay fired much less often on the WSL2 path.

[WSL2 replay measurements and raw logs](native-rate-replay/) · [Native Linux measurements](../milestone-3-linux/summary.csv)

## Studies A and B — calibrated load and steady interference

Each platform independently set light and moderate load to 35% and 70% of the sum of its single-drive calibration throughputs. This yielded 3,449 and 6,898 reads/s on WSL2 and 116 and 231 on native Linux. The paced calibration selected a 0.324 ms hedge delay on WSL2 and 9.214 ms on Linux. The table holds the budget at two permits and the alternate-drive threshold at one across all conditions. The accompanying analysis covers every permit count.

| Load | Interference | Linux budget p99 (ms) | WSL2 budget p99 (ms) | Linux duplicates | WSL2 duplicates |
|---|---|---:|---:|---:|---:|
| Light | none | 10.802 | 0.462 | 1.4% | 0.1% |
| Light | a | 22.983 | 0.381 | 13.5% | 0.0% |
| Light | b | 22.321 | 0.388 | 12.9% | 0.0% |
| Light | both | 44.462 | 0.483 | 17.0% | 0.3% |
| Moderate | none | 13.365 | 0.326 | 1.2% | 0.0% |
| Moderate | a | 35.637 | 0.379 | 9.4% | 0.0% |
| Moderate | b | 35.358 | 0.364 | 9.4% | 0.0% |
| Moderate | both | 59.098 | 0.514 | 5.8% | 0.5% |
| Moderate | transition | 51.450 | 0.487 | 7.1% | 0.2% |

[All WSL2 policies and paired comparisons](analysis.md) · [Calibration](calibration/) · [Plots](plots/)

On native Linux, the median budget-versus-fixed p99 change was +19.5% and the median replica-count change was -26.0%. Budget had lower p99 in 20 of 81 matched pairs. On WSL2, the median budget-versus-fixed p99 change was -2.1% and the median replica-count change was -0.9%. Budget had lower p99 in 49 of 81 matched pairs.

## Study C — adding interference to drive B

These WSL2 medians group requests by scheduled arrival before or after drive B’s first background read. Drive A remained active throughout. The two-permit limit was identical in both threshold settings.

| Phase at arrival | Threshold | WSL2 p99 (ms) | WSL2 replicas/success |
|---|---|---:|---:|
| a | Enabled | 0.402 | 1.000 |
| a | Disabled | 0.392 | 1.007 |
| both | Enabled | 0.504 | 1.004 |
| both | Disabled | 0.569 | 1.150 |

[All transition phases](transition-phases.csv) · [Native transition results](../milestone-3-linux/report.md)

## Read accounting

The 171 WSL2 main runs completed 2,793,690 logical reads and 2,836,314 replica reads (11,617,542,144 bytes). The 24 native-rate replays completed another 16,632 logical reads. Both suites recorded zero logical failures and zero invalid replicas. The runner checked each main trace, completion accounting and permit peak. Each WSL2 case includes both request logs and its background-worker timing record.

Three short repetitions describe this host and cache state. The native baseline was recorded in commit `39a46d1`; WSL2 used the Linux branch at `4d4c7b1`, which includes a subsequent policy refactor.
