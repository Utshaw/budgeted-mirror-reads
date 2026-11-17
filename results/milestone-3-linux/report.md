# Milestone 3 Native Linux Evaluation

We compared round-robin, less-busy-first, fixed-delay hedging, and budget-limited hedging on two separate 1 TB SATA HDDs. The engine replayed the same 4 KiB arrival and offset sequence for every policy at a given offered rate. All policies shared a logical depth of eight and a foreground physical I/O cap of 32. Latency starts at the scheduled arrival and includes admission wait. Throughput counts successful logical reads over the run through final drain. Interference ran on separate files and is tracked separately in the per-run JSON.

## Study A Without Interference

The individual drives had median depth-one p99 latencies of 10.18 ms on A and 10.19 ms on B. Their median useful throughputs were 179.84 and 168.93 reads/s. We selected light and moderate offered rates of 116 and 231 reads/s from 35% and 70% of the sum of the individual drives' mean throughputs.

A separate paced less-busy-first trace gave p75, p90, and p95 delay candidates of 7.135, 9.214, and 9.847 ms. We measured fixed-delay hedging at all three candidates and used the preselected p90 delay of 9.214 ms for both hedging policies throughout the main studies. See [drive calibration](calibration/summary.csv) and [candidate trials](calibration/hedge-candidates.csv).

| Offered reads/s | Policy | Logical p99, ms | Replica reads per success |
| ---: | --- | ---: | ---: |
| 116 | Less-busy-first | 15.24 | 1.000 |
| 116 | Fixed-delay | 10.29 | 1.046 |
| 116 | Budget 2 | 10.80 | 1.014 |
| 231 | Less-busy-first | 12.77 | 1.000 |
| 231 | Fixed-delay | 17.34 | 1.202 |
| 231 | Budget 2 | 13.37 | 1.012 |

The table shows medians across three runs. At 116 reads/s the two-permit budget preserved most of the fixed-delay latency gain while issuing fewer duplicates. At 231 reads/s without interference, the same budget and fixed-delay configurations both added I/O and increased p99 relative to less-busy-first. Round-robin had the lowest median p99 at that offered rate, 11.82 ms. [Latency versus replica work](plots/p99-versus-replica-reads.png)

## Study B Steady Interference

At 116 reads/s with interference on A, the two-permit budget reduced median p99 from 36.57 ms for less-busy-first to 22.98 ms. Fixed-delay reached 25.46 ms. The budget issued about 13.5 duplicates per 100 logical reads versus 32.5 for fixed-delay, and its median peak of unfinished losers was 1 versus 3. The alternate won a median of 28 reads per budget run and 33 per fixed-delay run. With the interference reversed to B, the same budget reached 22.32 ms versus 45.91 ms for less-busy-first. Useful throughput in these light-load comparisons remained close to the offered rate.

At 231 reads/s with both drives under interference, fixed-delay lowered median p99 from 56.42 ms for less-busy-first to 37.80 ms and issued 1.635 replica reads per success. The one-permit policy reached 54.15 ms at 1.053 replica reads per success. With two or four permits, the threshold-enabled policy produced a higher p99 than the less-busy-first baseline in this condition. Fixed-delay reached a median peak of seven unfinished losers. The three threshold-enabled budgets peaked at one or two. [Moderate-load comparison](plots/rate-231-both.png)

## Study C Interference Transition

Each run started with interference on A. B started issuing interference reads 1.50013–1.50038 s after foreground time zero. We held the hedge delay and permit limits fixed and changed the alternate-drive threshold from 1 to disabled. The table groups requests by their scheduled arrival phase. Some requests from the first phase completed after the transition.

| Phase at arrival | Permits | p99 with threshold, ms | p99 without threshold, ms | Replicas per success with threshold | Replicas per success without threshold |
| --- | ---: | ---: | ---: | ---: | ---: |
| A only | 1 | 35.28 | 28.01 | 1.081 | 1.233 |
| A only | 2 | 35.54 | 29.67 | 1.089 | 1.366 |
| A only | 4 | 34.43 | 26.59 | 1.089 | 1.513 |
| Both drives | 1 | 54.38 | 51.39 | 1.052 | 1.234 |
| Both drives | 2 | 51.83 | 44.55 | 1.052 | 1.390 |
| Both drives | 4 | 50.23 | 38.71 | 1.064 | 1.575 |

In the disabled-threshold runs, 465, 787, and 1,133 duplicates for the respective permit limits of 1, 2, and 4 were submitted while the alternate had an outstanding foreground read. Reconstructing the queue from the logs confirms that the enabled threshold would deny each of those submissions at the recorded instant. The threshold lowered replica work in every permit and phase comparison. [Transition plot](plots/transition-threshold.png) · [Phase data](transition-phases.csv)

The threshold also raised median p99 in each of these transition comparisons. It traded some of the latency benefit of a permit-only policy for lower replica work.

## Drain and Accounting

The 171 main runs produced 93,663 successful logical reads and 106,051 completed replica reads totaling 434,384,896 bytes. There were no failed logical reads or invalid replica completions. The raw logs reproduce the summary totals. Replaying their submission and completion events verifies the 32-read physical cap, each run's permit cap, and release after the second completion for every budgeted pair. All runs ended with zero outstanding reads and zero held permits.

One example is logical request 6 in the light-load, A-interference run with two permits. The engine issued reads to A at 51.856 ms and B at 67.390 ms. It returned B's verified response at 69.125 ms from run start. The original on A finished at 71.756 ms. The pair remained charged for that 2.630 ms cleanup interval. Both 4 KiB operations appear in the replica totals. [Logical log](runs/rate116-a-r0-budget-9214-2-1/run-logical.csv) · [Replica log](runs/rate116-a-r0-budget-9214-2-1/run-replica.csv)

## Scope

The measurements describe one drive pair, one filesystem configuration, and short traces with 348 or 693 arrivals each. Firmware caches were left enabled. In the small depth-one mirrored calibration, p50 fell from 5.32 ms on the first repeat to about 0.073 ms on later repeats, consistent with cached reads. The main analysis uses the separate paced calibration for the delay and retains all repetitions. Observed replica requests and completed bytes describe the load that the prototype generated. They do not measure internal mechanical disk work.

See [environment notes](environment.md), [per-run measurements](summary.csv), [matched comparisons](matched-comparisons.csv), and [generated analysis](analysis.md) for the complete results.
