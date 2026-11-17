# Milestone 3 Experiment Analysis

Analyzed 171 runs and 2,793,690 logical reads. All runs had zero failed logical reads and zero invalid replica reads.

## Latency and duplicate I/O by condition

Each number is a median across repetitions. Fixed and budget show the settings with the lowest observed median p99 within that condition. Budget excludes the threshold-disabled ablation. The delay is in microseconds. Duplicate rates are duplicates divided by logical reads.

| Offered reads/s | Depth | Interference | Round-robin p99 µs | Less-busy p99 µs | Fixed p99 µs (delay, duplicates) | Budget p99 µs (delay, permits, duplicates) |
|---:|---|---:|---:|---|---|
| 3449 | 8 | a | 386.6 | 385.5 | 381.9 (324, 0.1%) | 381.4 (324, 2, 0.0%) |
| 3449 | 8 | b | 389.0 | 379.7 | 387.4 (324, 0.2%) | 387.3 (324, 4, 0.0%) |
| 3449 | 8 | both | 478.7 | 480.2 | 1388.4 (324, 7.3%) | 480.7 (324, 1, 0.3%) |
| 3449 | 8 | none | 587.4 | 473.7 | 455.2 (324, 1.0%) | 417.1 (324, 4, 0.1%) |
| 6898 | 8 | a | 365.6 | 377.3 | 377.6 (324, 0.6%) | 378.5 (324, 2, 0.0%) |
| 6898 | 8 | b | 357.2 | 370.5 | 445.8 (324, 1.4%) | 363.9 (324, 2, 0.0%) |
| 6898 | 8 | both | 521.4 | 507.0 | 595.4 (324, 18.8%) | 504.8 (324, 4, 0.5%) |
| 6898 | 8 | none | 335.2 | 333.0 | 334.2 (324, 0.2%) | 325.9 (324, 2, 0.0%) |
| 6898 | 8 | transition | 482.1 | 476.3 | 536.2 (324, 9.4%) | 483.4 (324, 4, 0.2%) |

## Paired comparisons across settings

Each budget run is paired with a baseline from the same depth, interference condition, and repetition. The fixed baseline also uses the same hedge delay. Runs with the threshold enabled are used when available.

| Baseline | Matched pairs | Lower budget p99 | Lower budget replica count | Lower p99 and fewer replicas | Median p99 change | Median replica count change | Median throughput change |
|---|---:|---:|---:|---:|---:|---:|---:|
| round-robin | 81 | 44 | 0 | 0 | -0.5% | +0.0% | -0.0% |
| less-busy | 81 | 37 | 0 | 0 | +0.3% | +0.0% | +0.0% |
| fixed | 81 | 49 | 81 | 49 | -2.1% | -0.9% | +0.0% |

## Alternate-drive threshold ablation

The permit limit and delay are held fixed. Values compare threshold off with threshold on within each repetition.

| Depth | Interference | Repeat | Permits | p99 delta | Duplicates on | Duplicates off |
|---:|---|---:|---:|---:|---:|---:|
| 8 | transition | 1 | 1 | +3.2% | 0.2% | 4.9% |
| 8 | transition | 1 | 2 | +5.1% | 0.3% | 7.6% |
| 8 | transition | 1 | 4 | +21.0% | 0.3% | 10.9% |
| 8 | transition | 2 | 1 | +10.7% | 0.2% | 4.9% |
| 8 | transition | 2 | 2 | +197.2% | 0.2% | 11.3% |
| 8 | transition | 2 | 4 | +29.3% | 0.2% | 9.9% |
| 8 | transition | 3 | 1 | -99.3% | 1.1% | 4.7% |
| 8 | transition | 3 | 2 | +9.5% | 0.2% | 8.0% |
| 8 | transition | 3 | 4 | +11.7% | 0.2% | 9.5% |

See summary.csv for p50, p99, throughput, replica counts and bytes, duplicate fraction, peak active permits, and p99 loser cleanup for every run. See matched-comparisons.csv for the individual paired comparisons.
