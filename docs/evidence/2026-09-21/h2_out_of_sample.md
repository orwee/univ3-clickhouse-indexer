# H2, out of sample and against a placebo

Protocol committed before the hold-out data existed: docs/H2_PREREGISTRATION.md. Numbers only.

Displaced = more than 100 ticks from the centred 21-swap median. Threshold 1%, flagged = also beyond 1,000 USD. Only complete days with a closed external candle.

## 1. The same adjustment, in sample and on the hold-out

| Set, adjustment | Pool-days compared | Beyond 1% before | Positive fixed | Negative fixed | Inside before, broken | Flagged before | Flagged after | r |
|---|---|---|---|---|---|---|---|---|
| In sample: revalue every swap (H2 as first tested) | 120 | 24 | 7 of 15 | 8 of 9 | 6 of 96 | 12 | 4 | +0.716 |
| In sample: revalue displaced swaps only | 120 | 24 | 8 of 15 | 8 of 9 | 6 of 96 | 12 | 4 | +0.726 |
| HOLD-OUT: revalue every swap (H2 as first tested) | 39 | 10 | 5 of 8 | 1 of 2 | 3 of 29 | 4 | 2 | +0.046 |
| HOLD-OUT: revalue displaced swaps only | 39 | 10 | 5 of 8 | 1 of 2 | 2 of 29 | 4 | 2 | +0.062 |
| Secondary (2026-08-20): revalue every swap (H2 as first tested) | 4 | 1 | 0 of 1 | 0 of 0 | 1 of 3 | 1 | 2 | +0.298 |
| Secondary (2026-08-20): revalue displaced swaps only | 4 | 1 | 0 of 1 | 0 of 0 | 1 of 3 | 1 | 2 | +0.309 |

## 2. Placebo, on the in-sample pool-days

For each pool-day, the same NUMBER of swaps is revalued, but NON-displaced ones picked by a seeded hash. 20 seeds (1 to 20).

| Set, adjustment | Pool-days compared | Beyond 1% before | Positive fixed | Negative fixed | Inside before, broken | Flagged before | Flagged after | r |
|---|---|---|---|---|---|---|---|---|
| In sample: revalue displaced swaps only | 120 | 24 | 8 of 15 | 8 of 9 | 6 of 96 | 12 | 4 | +0.726 |
| In sample: placebo, seed 1 | 120 | 24 | 0 of 15 | 0 of 9 | 1 of 96 | 12 | 12 | -0.045 |

Placebo over 20 seeds: pool-days fixed min 0, median 0, max 0; broken min 1, median 1, max 1.

## 3. The hold-out pool-days beyond the threshold, one by one

| pool | date | rel diff | abs diff USD | displaced swaps | rel diff, every swap revalued | rel diff, displaced only |
|---|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-08-19 | +1.21% | 2 | 10 | +0.91% | +0.91% |
| wstETH/USDC 0.05% | 2026-08-10 | +9.64% | 368 | 9 | +0.11% | +0.10% |
| wstETH/USDC 0.05% | 2026-08-11 | -9.01% | -372 | 9 | +2.50% | +2.51% |
| wstETH/USDC 0.05% | 2026-08-12 | +1.57% | 12 | 3 | +0.24% | +0.22% |
| wstETH/USDC 0.05% | 2026-08-14 | -1.34% | -18 | 8 | +0.16% | +0.19% |
| wstETH/USDC 0.05% | 2026-08-17 | +121.53% | 812 | 7 | +128.34% | +128.39% |
| USDC/WETH 0.05% | 2026-08-19 | +2.63% | 7,766,114 | 7 | +2.65% | +2.64% |
| USDC/WETH 0.01% | 2026-08-11 | +1.31% | 396,150 | 25 | +1.93% | +1.92% |
| USDC/WETH 0.01% | 2026-08-14 | +2.82% | 1,070,036 | 18 | +0.14% | +0.13% |
| USDC/WETH 0.01% | 2026-08-15 | +1.01% | 221,082 | 24 | +0.10% | +0.09% |
| USDC/WETH 0.05% | 2026-08-20 | +1.07% | 1,273,956 | 0 | +1.08% | +1.07% |
