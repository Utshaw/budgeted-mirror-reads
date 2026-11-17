# Milestone 3 Experiment Analysis

Analyzed 171 runs and 93,663 logical reads. All runs had zero failed logical reads and zero invalid replica reads.

## Latency and duplicate I/O by condition

Each number is a median across repetitions. Fixed and budget show the settings with the lowest observed median p99 within that condition. Budget excludes the threshold-disabled ablation. The delay is in microseconds. Duplicate rates are duplicates divided by logical reads.

| Offered reads/s | Depth | Interference | Round-robin p99 µs | Less-busy p99 µs | Fixed p99 µs (delay, duplicates) | Budget p99 µs (delay, permits, duplicates) |
|---:|---|---:|---:|---|---|
| 116 | 8 | a | 38112.5 | 36574.2 | 25463.3 (9214, 32.5%) | 22983.2 (9214, 2, 13.5%) |
| 116 | 8 | b | 43413.2 | 45905.7 | 23420.8 (9214, 32.5%) | 22320.7 (9214, 2, 12.9%) |
| 116 | 8 | both | 52168.9 | 51193.1 | 38137.6 (9214, 62.6%) | 41099.3 (9214, 4, 15.8%) |
| 116 | 8 | none | 26677.5 | 15237.6 | 10290.8 (9214, 4.6%) | 10801.8 (9214, 2, 1.4%) |
| 231 | 8 | a | 55832.7 | 44257.3 | 28796.4 (9214, 51.8%) | 30255.9 (9214, 1, 8.4%) |
| 231 | 8 | b | 52495.1 | 41767.3 | 26439.6 (9214, 48.5%) | 32822.0 (9214, 1, 10.1%) |
| 231 | 8 | both | 59782.1 | 56416.8 | 37800.3 (9214, 63.5%) | 54148.6 (9214, 1, 5.3%) |
| 231 | 8 | none | 11818.2 | 12772.7 | 17344.1 (9214, 20.2%) | 12863.5 (9214, 1, 1.3%) |
| 231 | 8 | transition | 62469.7 | 58068.4 | 38363.4 (9214, 57.9%) | 45992.0 (9214, 4, 7.5%) |

## Paired comparisons across settings

Each budget run is paired with a baseline from the same depth, interference condition, and repetition. The fixed baseline also uses the same hedge delay. Runs with the threshold enabled are used when available.

| Baseline | Matched pairs | Lower budget p99 | Lower budget replica count | Lower p99 and fewer replicas | Median p99 change | Median replica count change | Median throughput change |
|---|---:|---:|---:|---:|---:|---:|---:|
| round-robin | 81 | 73 | 0 | 0 | -28.6% | +8.8% | +0.0% |
| less-busy | 81 | 65 | 0 | 0 | -21.2% | +8.8% | -0.1% |
| fixed | 81 | 20 | 81 | 20 | +19.5% | -26.0% | +0.0% |

## Alternate-drive threshold ablation

The permit limit and delay are held fixed. Values compare threshold off with threshold on within each repetition.

| Depth | Interference | Repeat | Permits | p99 delta | Duplicates on | Duplicates off |
|---:|---|---:|---:|---:|---:|---:|
| 8 | transition | 1 | 1 | -2.7% | 7.2% | 22.5% |
| 8 | transition | 1 | 2 | -25.1% | 7.1% | 37.8% |
| 8 | transition | 1 | 4 | -25.6% | 7.4% | 54.5% |
| 8 | transition | 2 | 1 | -4.3% | 6.9% | 23.4% |
| 8 | transition | 2 | 2 | -25.7% | 6.8% | 38.7% |
| 8 | transition | 2 | 4 | -39.0% | 8.1% | 55.4% |
| 8 | transition | 3 | 1 | -19.5% | 6.1% | 24.0% |
| 8 | transition | 3 | 2 | -3.0% | 7.9% | 38.2% |
| 8 | transition | 3 | 4 | -34.3% | 7.5% | 53.7% |

See summary.csv for p50, p99, throughput, replica counts and bytes, duplicate fraction, peak active permits, and p99 loser cleanup for every run. See matched-comparisons.csv for the individual paired comparisons.
