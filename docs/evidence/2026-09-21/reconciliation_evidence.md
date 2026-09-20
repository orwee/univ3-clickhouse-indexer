# Reconciliation evidence

Numbers only, from section 1 on: what was measured, not why, and not what is acceptable. The one exception is the list right below, which is a draft and says so.

## Hallazgos

**DRAFT — to be reviewed and rewritten by Roberto**

Drafted by a coding agent from the numbers of one run; the text, with each figure and the section of this report behind it, is `docs/RECONCILIATION_FINDINGS.md`. Titles and states only:

- 1. The pipeline agrees with itself exactly — EXPLAINED
- 2. Partial days and open candles — EXPLAINED
- 3. The day boundary is not the cause — EXPLAINED (a negative result)
- 4. Which leg is valued does not matter in the liquid pools — EXPLAINED
- 5. In the liquid pools the 30-day totals agree and the daily noise is centred — EXPLAINED
- 6. 2026-08-27: two pools of the same pair off in opposite directions — PARTLY EXPLAINED
- 7. Round trips inside one block, valued differently — PARTLY EXPLAINED
- 8. 2026-08-29: three pools high on a quiet Saturday — PARTLY EXPLAINED
- 9. Days on which the source reports more than the chain — PARTLY EXPLAINED
- 10. In thin pools a percentage alone does not discriminate — EXPLAINED

## 1. Day boundary

Our volume recomputed with the day cut moved from -12 h to +12 h in steps of 1 h, against the external days, over 2026-08-10 to 2026-09-19 (days complete on our side under every shift). A positive shift moves swaps from late in the day into the next day. Cell: sum of |our day - external day| divided by the external total.

| Shift (h) | wstETH/USDC 0.3% | wstETH/USDC 0.05% | USDC/WETH 0.05% | USDC/WETH 0.01% |
|---|---|---|---|---|
| -12 | 12.46% | 1.19% | 16.20% | 14.86% |
| -11 | 14.16% | 1.18% | 14.81% | 13.74% |
| -10 | 12.70% | 1.18% | 13.48% | 13.16% |
| -9 | 12.51% | 0.97% | 11.83% | 12.37% |
| -8 | 16.52% | 0.43% | 11.18% | 10.55% |
| -7 | 12.46% | 0.42% | 10.07% | 9.61% |
| -6 | 10.65% | 0.42% | 9.25% | 8.99% |
| -5 | 9.66% | 0.40% | 8.02% | 5.90% |
| -4 | 9.62% | 0.40% | 7.41% | 5.38% |
| -3 | 11.85% | 0.40% | 6.29% | 4.20% |
| -2 | 6.45% | 0.35% | 4.58% | 3.02% |
| -1 | 2.05% | 0.24% | 2.83% | 1.76% |
| +0 | 0.42% | 0.14% | 0.53% | 0.66% |
| +1 | 13.00% | 0.18% | 2.57% | 1.87% |
| +2 | 13.96% | 0.20% | 5.48% | 3.97% |
| +3 | 16.40% | 0.30% | 10.13% | 8.54% |
| +4 | 20.04% | 0.32% | 14.02% | 9.59% |
| +5 | 21.51% | 0.32% | 15.62% | 10.01% |
| +6 | 27.37% | 0.39% | 18.11% | 11.34% |
| +7 | 26.63% | 0.41% | 19.56% | 11.56% |
| +8 | 27.74% | 0.45% | 23.99% | 12.95% |
| +9 | 30.37% | 102.74% | 29.56% | 14.27% |
| +10 | 32.78% | 197.73% | 33.75% | 17.26% |
| +11 | 36.02% | 197.75% | 37.89% | 19.56% |
| +12 | 41.75% | 197.77% | 41.16% | 20.86% |

| Pool | Shift with the smallest value | Value there | Value at shift 0 |
|---|---|---|---|
| wstETH/USDC 0.3% | +0 h | 0.42% | 0.42% |
| wstETH/USDC 0.05% | +0 h | 0.14% | 0.14% |
| USDC/WETH 0.05% | +0 h | 0.53% | 0.53% |
| USDC/WETH 0.01% | +0 h | 0.66% | 0.66% |

## 2. The stablecoin leg against the other leg at the pool's own price

Same swaps valued two ways: the stablecoin leg at 1 USD, and the other leg converted at the pool price right after each swap (`sqrt_price_x96`). Swaps with a zero leg are left out of this table, and so are swaps that left the pool at the price limit (|tick| > 800,000), which are counted in their own column.

| Pool | Swaps valued | Swaps at the price limit | Stable leg USD | Other leg USD | Other / stable - 1 | Per swap: p1 | median | p99 |
|---|---|---|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 669 | 3 | 58,512 | 58,101 | -0.7016% | -8.0947% | +0.0223% | +3.2932% |
| wstETH/USDC 0.05% | 5,672 | 0 | 26,376,642 | 26,372,801 | -0.0146% | -1.3915% | +0.0015% | +1.3924% |
| USDC/WETH 0.05% | 276,450 | 0 | 3,393,719,460 | 3,393,758,128 | +0.0011% | -0.0522% | -0.0295% | +0.0509% |
| USDC/WETH 0.01% | 827,850 | 0 | 1,867,819,631 | 1,877,568,560 | +0.5219% | -0.0335% | -0.0001% | +0.0349% |

## 3. Distribution of the daily relative difference (ours - external) / external

Compared days only (see the rules at the top of `reconciliation.md`).

| Pool | Days | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 41 | -2.04% | -0.22% | +0.10% | +0.65% | +3.14% |
| wstETH/USDC 0.3% | 40 | -6.75% | -0.32% | -0.03% | +0.08% | +1.21% |
| wstETH/USDC 0.05% | 41 | -17.69% | -0.09% | -0.00% | +1.34% | +121.53% |
| USDC/WETH 0.05% | 41 | -0.15% | -0.02% | +0.08% | +0.60% | +2.63% |

By activity level: pool-days sorted by our number of swaps and cut in three groups of equal size.

| Activity | Pool-days | Swaps per day (range) | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|---|
| low | 54 | 2 to 110 | -9.01% | -0.32% | -0.02% | +0.18% | +121.53% |
| middle | 54 | 111 to 7,281 | -17.69% | -0.05% | +0.15% | +0.76% | +17.84% |
| high | 55 | 7,304 to 26,431 | -2.04% | -0.04% | +0.06% | +0.63% | +3.14% |

## 4. Partial days

The first and the last day of the window are incomplete on our side: the backfill starts and ends inside a day. The external source reports whole days.

| Pool | Date | Our swaps | Our USD | External USD | Rel diff |
|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-09-20 | 15 | 1,766 | 4,354 | -59.44% |
| wstETH/USDC 0.05% | 2026-08-09 | 14 | 67 | 474 | -85.77% |
| wstETH/USDC 0.05% | 2026-09-20 | 45 | 752 | 1,256 | -40.10% |
| USDC/WETH 0.05% | 2026-08-09 | 878 | 13,157,653 | 31,946,693 | -58.81% |
| USDC/WETH 0.05% | 2026-09-20 | 3,498 | 26,024,785 | 56,090,221 | -53.60% |
| USDC/WETH 0.01% | 2026-08-09 | 3,476 | 4,895,431 | 14,720,866 | -66.74% |
| USDC/WETH 0.01% | 2026-09-20 | 12,398 | 26,675,148 | 57,182,843 | -53.35% |

Our first swap: 2026-08-09 18:35:11 UTC. Our last swap: 2026-09-20 14:16:35 UTC.

## 5. Zero-leg swaps and filters

This pipeline filters nothing: every Swap log of the pools is kept and counted. Whether the external source filters any trades is not documented (docs/EXTERNAL_SOURCE.md).

| Pool | Swaps | With one zero leg | With both legs zero | USD volume of the zero-leg swaps |
|---|---|---|---|---|
| wstETH/USDC 0.3% | 673 | 1 | 0 | 0.000000 |
| wstETH/USDC 0.05% | 5,672 | 0 | 0 | 0.000000 |
| USDC/WETH 0.05% | 276,475 | 25 | 0 | 0.000016 |
| USDC/WETH 0.01% | 827,856 | 6 | 0 | 0.000000 |

Pool-days present on one side only: 1.
- wstETH/USDC 0.3% 2026-08-09: only_external

## 6. Pools of the same pair, added up

For every compared day: ours and the external figure summed over the pools that trade the same two tokens. Listed: the days on which at least one pool of the pair is beyond 1% while the sum is within it.

### USDC/WETH: USDC/WETH 0.01% + USDC/WETH 0.05%

Days with every pool of the pair compared: 41.

| date | USDC/WETH 0.01% rel diff | USDC/WETH 0.05% rel diff | pair ours USD | pair external USD | pair abs diff USD | pair rel diff |
|---|---|---|---|---|---|---|
| 2026-08-11 | +1.31% | +0.15% | 75,332,097 | 74,868,337 | 463,759 | +0.62% |
| 2026-08-15 | +1.01% | -0.04% | 37,782,026 | 37,567,854 | 214,173 | +0.57% |
| 2026-08-20 | +0.03% | +1.07% | 235,681,969 | 234,372,931 | 1,309,039 | +0.56% |
| 2026-08-27 | -1.65% | +1.35% | 136,285,294 | 136,064,526 | 220,768 | +0.16% |
| 2026-08-30 | +2.03% | +0.08% | 107,870,015 | 107,117,050 | 752,966 | +0.70% |
| 2026-09-03 | +1.59% | -0.15% | 144,012,923 | 143,454,767 | 558,156 | +0.39% |
| 2026-09-07 | -2.04% | -0.03% | 95,490,154 | 96,341,279 | -851,125 | -0.88% |
| 2026-09-16 | -1.27% | +0.01% | 156,438,790 | 157,037,110 | -598,320 | -0.38% |

Pair-days beyond 1%: 4 of 41. Pair daily rel diff: min, p25, median, p75, max = -0.88% | -0.03% | +0.25% | +0.62% | +2.10%.

### wstETH/USDC: wstETH/USDC 0.3% + wstETH/USDC 0.05%

Days with every pool of the pair compared: 40.

| date | wstETH/USDC 0.3% rel diff | wstETH/USDC 0.05% rel diff | pair ours USD | pair external USD | pair abs diff USD | pair rel diff |
|---|---|---|---|---|---|---|
| 2026-08-19 | +1.21% | -0.09% | 4,858 | 4,861 | -3 | -0.06% |

Pair-days beyond 1%: 18 of 40. Pair daily rel diff: min, p25, median, p75, max = -17.67% | -0.11% | +0.02% | +1.34% | +120.32%.


## 7. The same day across the pools

Compared days. Volume vs median: our USD volume of the day, all pools, over the median of that figure. Marked `<<`: three or more pools beyond 1% with the same sign.

| date | weekday | volume vs median | USDC/WETH 0.01% | wstETH/USDC 0.3% | wstETH/USDC 0.05% | USDC/WETH 0.05% | |
|---|---|---|---|---|---|---|---|
| 2026-08-10 | Mon | 1.03x | -0.08% | +0.42% | +9.64% | +0.36% |  |
| 2026-08-11 | Tue | 0.68x | +1.31% | -0.02% | -9.01% | +0.15% |  |
| 2026-08-12 | Wed | 0.99x | +0.29% | -0.02% | +1.57% | +0.13% |  |
| 2026-08-13 | Thu | 0.82x | +0.49% | -0.21% | -0.02% | +0.76% |  |
| 2026-08-14 | Fri | 0.75x | +2.82% | +0.12% | -1.34% | +0.03% |  |
| 2026-08-15 | Sat | 0.34x | +1.01% |  | -0.00% | -0.04% |  |
| 2026-08-16 | Sun | 0.34x | +0.80% | -0.44% | -0.09% | -0.03% |  |
| 2026-08-17 | Mon | 1.05x | +0.18% | -0.32% | +121.53% | +0.79% |  |
| 2026-08-18 | Tue | 0.85x | +0.66% | +0.19% | -0.01% | +0.44% |  |
| 2026-08-19 | Wed | 3.50x | +0.27% | +1.21% | -0.09% | +2.63% |  |
| 2026-08-20 | Thu | 2.12x | +0.03% | -0.43% | +0.69% | +1.07% |  |
| 2026-08-21 | Fri | 2.70x | +0.47% | -0.81% | +2.10% | +0.12% |  |
| 2026-08-22 | Sat | 1.64x | +0.06% | +0.86% | -0.18% | +0.08% |  |
| 2026-08-23 | Sun | 1.42x | +0.01% | +0.01% | -7.82% | +0.40% |  |
| 2026-08-24 | Mon | 1.57x | +0.92% | -0.29% | +2.04% | +0.60% |  |
| 2026-08-25 | Tue | 1.31x | +0.25% | -0.03% | -2.44% | +0.93% |  |
| 2026-08-26 | Wed | 0.98x | -0.60% | -0.32% | +1.60% | +0.19% |  |
| 2026-08-27 | Thu | 1.23x | -1.65% | -0.31% | -0.06% | +1.35% |  |
| 2026-08-28 | Fri | 1.16x | -0.65% | +0.94% | -0.14% | +0.93% |  |
| 2026-08-29 | Sat | 0.45x | +1.80% | -0.12% | +1.34% | +1.44% | << |
| 2026-08-30 | Sun | 0.97x | +2.03% | +0.07% | +1.05% | +0.08% |  |
| 2026-08-31 | Mon | 0.93x | +0.65% | -6.75% | +1.71% | +0.63% |  |
| 2026-09-01 | Tue | 0.99x | +0.62% | +0.19% | -0.08% | +0.64% |  |
| 2026-09-02 | Wed | 1.00x | +0.20% | +0.18% | +0.55% | +0.33% |  |
| 2026-09-03 | Thu | 1.30x | +1.59% | -0.81% | -17.69% | -0.15% |  |
| 2026-09-04 | Fri | 1.24x | -0.01% | +0.73% | +2.55% | -0.02% |  |
| 2026-09-05 | Sat | 0.43x | -0.32% | -0.31% | +0.33% | +0.02% |  |
| 2026-09-06 | Sun | 0.82x | -0.55% | +0.00% | +6.85% | -0.01% |  |
| 2026-09-07 | Mon | 0.86x | -2.04% | +0.36% | +0.02% | -0.03% |  |
| 2026-09-08 | Tue | 0.84x | -0.05% | +0.08% | -0.07% | -0.04% |  |
| 2026-09-09 | Wed | 1.11x | +0.10% | -0.14% | +0.51% | -0.07% |  |
| 2026-09-10 | Thu | 0.91x | -0.02% | -0.30% | -0.00% | -0.03% |  |
| 2026-09-11 | Fri | 2.11x | +3.14% | -0.76% | -0.11% | +0.36% |  |
| 2026-09-12 | Sat | 0.39x | -0.31% | -1.81% | -5.05% | +0.04% |  |
| 2026-09-13 | Sun | 0.55x | -0.04% | -0.34% | -0.17% | -0.03% |  |
| 2026-09-14 | Mon | 1.25x | +0.01% | -0.58% | +0.40% | -0.05% |  |
| 2026-09-15 | Tue | 1.43x | -0.22% | -0.09% | -0.06% | -0.05% |  |
| 2026-09-16 | Wed | 1.41x | -1.27% | +0.02% | +0.48% | +0.01% |  |
| 2026-09-17 | Thu | 1.04x | -0.79% | -0.01% | -0.02% | +0.01% |  |
| 2026-09-18 | Fri | 1.51x | +0.14% | +0.06% | +0.01% | +0.02% |  |
| 2026-09-19 | Sat | 0.98x | -0.55% | -0.82% | +17.84% | -0.01% |  |

Days marked: 2026-08-29.

## 8. One swap the size of the difference

For each compared pool-day beyond 1%: our swaps of that pool whose USD value is within 5% of the absolute difference, looking at the UTC day plus 10 minutes before its first midnight and after its last. The day's median tick and liquidity are given to compare each swap with; nothing is called anomalous here.

| pool | date | rel diff | abs diff USD | swaps that size | of them, within 10 min of a midnight |
|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-08-19 | +1.21% | 2 | 0 | 0 |
| wstETH/USDC 0.3% | 2026-08-31 | -6.75% | -9 | 0 | 0 |
| wstETH/USDC 0.3% | 2026-09-12 | -1.81% | -62 | 1 | 0 |
| wstETH/USDC 0.05% | 2026-08-10 | +9.64% | 368 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-08-11 | -9.01% | -372 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-08-12 | +1.57% | 12 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-08-14 | -1.34% | -18 | 2 | 0 |
| wstETH/USDC 0.05% | 2026-08-17 | +121.53% | 812 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-08-21 | +2.10% | 225 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-08-23 | -7.82% | -1,602 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-08-24 | +2.04% | 49 | 3 | 0 |
| wstETH/USDC 0.05% | 2026-08-25 | -2.44% | -313 | 2 | 0 |
| wstETH/USDC 0.05% | 2026-08-26 | +1.60% | 53 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-08-29 | +1.34% | 18 | 2 | 0 |
| wstETH/USDC 0.05% | 2026-08-30 | +1.05% | 77 | 2 | 0 |
| wstETH/USDC 0.05% | 2026-08-31 | +1.71% | 136 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-09-03 | -17.69% | -2,379 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-09-04 | +2.55% | 87 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-09-06 | +6.85% | 326 | 2 | 0 |
| wstETH/USDC 0.05% | 2026-09-12 | -5.05% | -743 | 0 | 0 |
| wstETH/USDC 0.05% | 2026-09-19 | +17.84% | 1,415 | 0 | 0 |
| USDC/WETH 0.05% | 2026-08-19 | +2.63% | 7,766,114 | 0 | 0 |
| USDC/WETH 0.05% | 2026-08-20 | +1.07% | 1,273,956 | 0 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | +1.35% | 1,112,611 | 1 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | +1.44% | 368,871 | 0 | 0 |
| USDC/WETH 0.01% | 2026-08-11 | +1.31% | 396,150 | 6 | 0 |
| USDC/WETH 0.01% | 2026-08-14 | +2.82% | 1,070,036 | 2 | 0 |
| USDC/WETH 0.01% | 2026-08-15 | +1.01% | 221,082 | 0 | 0 |
| USDC/WETH 0.01% | 2026-08-27 | -1.65% | -891,843 | 0 | 0 |
| USDC/WETH 0.01% | 2026-08-29 | +1.80% | 425,831 | 0 | 0 |
| USDC/WETH 0.01% | 2026-08-30 | +2.03% | 690,977 | 0 | 0 |
| USDC/WETH 0.01% | 2026-09-03 | +1.59% | 710,478 | 0 | 0 |
| USDC/WETH 0.01% | 2026-09-07 | -2.04% | -833,802 | 0 | 0 |
| USDC/WETH 0.01% | 2026-09-11 | +3.14% | 1,615,421 | 4 | 0 |
| USDC/WETH 0.01% | 2026-09-16 | -1.27% | -611,518 | 0 | 0 |

The swaps counted above:

| pool | date | swap time (UTC) | swap USD | swap / abs diff - 1 | where in the day | tick | day median tick | liquidity | day median liquidity | swaps that day | swap / day USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-09-12 | 2026-09-12 22:00:47 | 59.19 | -4.70% |  | -195805 | -195797 | 4.971e+15 | 4.971e+15 | 30 | 1.8% |
| wstETH/USDC 0.05% | 2026-08-14 | 2026-08-14 05:52:47 | 17.53 | -2.26% |  | -199309 | -198784 | 1.739e+14 | 1.739e+14 | 68 | 1.3% |
| wstETH/USDC 0.05% | 2026-08-14 | 2026-08-14 15:45:47 | 17.44 | -2.78% |  | -198811 | -198784 | 1.739e+14 | 1.739e+14 | 68 | 1.3% |
| wstETH/USDC 0.05% | 2026-08-24 | 2026-08-24 07:12:35 | 48.23 | -1.54% |  | -196028 | -196027 | 2.856e+14 | 2.856e+14 | 162 | 2.0% |
| wstETH/USDC 0.05% | 2026-08-24 | 2026-08-24 11:37:11 | 49.88 | +1.82% |  | -195957 | -196027 | 2.856e+14 | 2.856e+14 | 162 | 2.0% |
| wstETH/USDC 0.05% | 2026-08-24 | 2026-08-24 18:35:23 | 50.35 | +2.79% |  | -196062 | -196027 | 2.856e+14 | 2.856e+14 | 162 | 2.1% |
| wstETH/USDC 0.05% | 2026-08-25 | 2026-08-25 07:53:11 | 306.71 | -1.97% |  | -196222 | -195988 | 2.611e+16 | 2.856e+14 | 172 | 2.5% |
| wstETH/USDC 0.05% | 2026-08-25 | 2026-08-25 13:36:47 | 300.15 | -4.07% |  | -196024 | -195988 | 2.856e+14 | 2.856e+14 | 172 | 2.4% |
| wstETH/USDC 0.05% | 2026-08-29 | 2026-08-29 17:26:23 | 18.59 | +3.04% |  | -196133 | -196130 | 2.856e+14 | 2.856e+14 | 77 | 1.4% |
| wstETH/USDC 0.05% | 2026-08-29 | 2026-08-29 19:16:23 | 18.17 | +0.69% |  | -196084 | -196130 | 2.856e+14 | 2.856e+14 | 77 | 1.3% |
| wstETH/USDC 0.05% | 2026-08-30 | 2026-08-30 21:02:47 | 79.37 | +3.02% |  | -196070 | -196049 | 2.856e+14 | 2.856e+14 | 164 | 1.1% |
| wstETH/USDC 0.05% | 2026-08-30 | 2026-08-30 21:02:47 | 79.37 | +3.02% |  | -196020 | -196049 | 2.856e+14 | 2.856e+14 | 164 | 1.1% |
| wstETH/USDC 0.05% | 2026-09-06 | 2026-09-06 14:43:23 | 336.41 | +3.21% |  | -195567 | -195908 | 1.766e+14 | 2.856e+14 | 119 | 6.6% |
| wstETH/USDC 0.05% | 2026-09-06 | 2026-09-06 14:43:23 | 336.94 | +3.38% |  | -195979 | -195908 | 2.856e+14 | 2.856e+14 | 119 | 6.6% |
| USDC/WETH 0.05% | 2026-08-27 | 2026-08-27 10:26:35 | 1,120,223.90 | +0.68% |  | 198120 | 198062 | 4.367e+18 | 4.401e+18 | 7,615 | 1.3% |
| USDC/WETH 0.01% | 2026-08-11 | 2026-08-11 07:43:23 | 409,272.38 | +3.31% |  | 201284 | 200948 | 5.407e+17 | 7.536e+17 | 16,372 | 1.3% |
| USDC/WETH 0.01% | 2026-08-11 | 2026-08-11 07:43:23 | 409,272.38 | +3.31% |  | 200954 | 200948 | 7.476e+17 | 7.536e+17 | 16,372 | 1.3% |
| USDC/WETH 0.01% | 2026-08-11 | 2026-08-11 17:55:59 | 394,670.02 | -0.37% |  | 201314 | 200948 | 5.859e+17 | 7.536e+17 | 16,372 | 1.3% |
| USDC/WETH 0.01% | 2026-08-11 | 2026-08-11 17:55:59 | 391,919.67 | -1.07% |  | 201011 | 200948 | 7.62e+17 | 7.536e+17 | 16,372 | 1.3% |
| USDC/WETH 0.01% | 2026-08-11 | 2026-08-11 18:44:59 | 391,582.14 | -1.15% |  | 201330 | 200948 | 5.898e+17 | 7.536e+17 | 16,372 | 1.3% |
| USDC/WETH 0.01% | 2026-08-11 | 2026-08-11 18:44:59 | 391,582.14 | -1.15% |  | 201028 | 200948 | 6.302e+17 | 7.536e+17 | 16,372 | 1.3% |
| USDC/WETH 0.01% | 2026-08-14 | 2026-08-14 14:24:23 | 1,086,930.03 | +1.58% |  | 202190 | 200945 | 2.454e+17 | 8.243e+17 | 15,704 | 2.8% |
| USDC/WETH 0.01% | 2026-08-14 | 2026-08-14 14:24:23 | 1,086,930.03 | +1.58% |  | 201014 | 200945 | 6.888e+17 | 8.243e+17 | 15,704 | 2.8% |
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 04:46:59 | 1,591,689.34 | -1.47% |  | 193939 | 198049 | 5.77e+16 | 4.912e+17 | 19,854 | 3.0% |
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 04:46:59 | 1,592,261.16 | -1.43% |  | 198253 | 198049 | 5.216e+17 | 4.912e+17 | 19,854 | 3.0% |
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 16:32:23 | 1,569,141.11 | -2.86% |  | 190929 | 198049 | 1.144e+16 | 4.912e+17 | 19,854 | 3.0% |
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 16:32:23 | 1,570,088.61 | -2.81% |  | 197831 | 198049 | 4.259e+17 | 4.912e+17 | 19,854 | 3.0% |

## 9. Swaps executed away from the pool's own recent price

Two readings of the same suspicion are put to the test, neither taken as true: (H1) the external source leaves such swaps out and this pipeline counts every log; (H2) the source counts them but values them at a going price, while this pipeline values every swap by its stablecoin leg.

**Definition.** Reference tick = median tick of the pool over the 21 consecutive swaps centred on the swap. Displacement = the larger of |tick before the swap - reference| and |tick after it - reference|. A swap is *displaced* beyond N when its displacement is more than N ticks (1 tick = 0.01% in price). N = 100 here, and the table says why.

| Pool | Swaps | p50 | p90 | p99 | p99.9 | p99.99 | max | >25 | >50 | >100 | >200 | >500 | >1000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 827,856 | 1 | 5 | 16 | 186 | 1,214 | 16,028 | 5,066 | 2,794 | 1,702 | 743 | 254 | 120 |
| USDC/WETH 0.05% | 276,475 | 0 | 5 | 16 | 40 | 90 | 258 | 898 | 147 | 18 | 3 | 0 | 0 |
| wstETH/USDC 0.05% | 5,672 | 21 | 72 | 780 | 6,873 | 6,938 | 6,938 | 2,342 | 958 | 361 | 198 | 87 | 50 |
| wstETH/USDC 0.3% | 673 | 41 | 220 | 16,052 | 1,082,989 | 1,082,989 | 1,082,989 | 450 | 277 | 156 | 77 | 40 | 27 |

Why 100: the deepest pool trades the same asset at the same time as its sibling and hardly ever goes beyond it, so beyond it a swap is about that pool's liquidity at that moment and not about the market. In the two quiet pools 21 swaps span hours, real price drift enters the displacement, and the definition separates less; their figures below are given with that caveat.

### The 17 flagged pool-days

Displaced = beyond 100 ticks. *Without them* is H1; *valued at the reference* is H2 (every swap of the day, the non-stable leg at the reference tick).

| pool | date | rel diff | abs diff USD | displaced swaps | displaced USD | rel diff without them (H1) | rel diff valued at the reference (H2) |
|---|---|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-08-23 | -7.82% | -1,602 | 11 | 9,512 | -54.26% | -0.05% |
| wstETH/USDC 0.05% | 2026-09-03 | -17.69% | -2,379 | 7 | 6,836 | -68.52% | +0.13% |
| wstETH/USDC 0.05% | 2026-09-19 | +17.84% | 1,415 | 21 | 8,196 | -85.47% | +0.03% |
| USDC/WETH 0.05% | 2026-08-19 | +2.63% | 7,766,114 | 7 | 20,327,438 | -4.26% | +2.65% |
| USDC/WETH 0.05% | 2026-08-20 | +1.07% | 1,273,956 | 0 | 0 | +1.07% | +1.08% |
| USDC/WETH 0.05% | 2026-08-27 | +1.35% | 1,112,611 | 0 | 0 | +1.35% | +1.37% |
| USDC/WETH 0.05% | 2026-08-29 | +1.44% | 368,871 | 0 | 0 | +1.44% | +1.46% |
| USDC/WETH 0.01% | 2026-08-11 | +1.31% | 396,150 | 25 | 6,664,468 | -20.66% | +1.93% |
| USDC/WETH 0.01% | 2026-08-14 | +2.82% | 1,070,036 | 18 | 16,268,794 | -39.98% | +0.14% |
| USDC/WETH 0.01% | 2026-08-15 | +1.01% | 221,082 | 24 | 10,001,651 | -44.83% | +0.10% |
| USDC/WETH 0.01% | 2026-08-27 | -1.65% | -891,843 | 59 | 17,743,704 | -34.54% | +0.50% |
| USDC/WETH 0.01% | 2026-08-29 | +1.80% | 425,831 | 45 | 9,705,143 | -39.21% | +0.83% |
| USDC/WETH 0.01% | 2026-08-30 | +2.03% | 690,977 | 29 | 6,868,442 | -18.13% | +0.07% |
| USDC/WETH 0.01% | 2026-09-03 | +1.59% | 710,478 | 33 | 5,265,880 | -10.19% | +1.62% |
| USDC/WETH 0.01% | 2026-09-07 | -2.04% | -833,802 | 56 | 13,055,338 | -34.04% | +0.02% |
| USDC/WETH 0.01% | 2026-09-11 | +3.14% | 1,615,421 | 43 | 12,338,144 | -20.87% | +1.35% |
| USDC/WETH 0.01% | 2026-09-16 | -1.27% | -611,518 | 33 | 8,213,804 | -18.32% | -0.02% |

### All 163 compared pool-days

Pearson correlation of the daily difference (ours - external, USD) with:

- the USD of displaced swaps (H1): +0.233
- ours minus ours valued at the reference (H2): +0.243

Per pool (the two liquid pools dominate any correlation in USD):

| Pool | Pool-days | r with displaced USD (H1) | r with the revaluation (H2) |
|---|---|---|---|
| USDC/WETH 0.01% | 41 | -0.062 | +0.786 |
| wstETH/USDC 0.3% | 40 | -0.819 | +0.926 |
| wstETH/USDC 0.05% | 41 | -0.404 | -0.883 |
| USDC/WETH 0.05% | 41 | +0.886 | -0.351 |

### Would it make the days reconcile? Both directions

Pool-days beyond 1% today that come inside it, and pool-days inside it today that would leave it. A hypothesis that fixes days by breaking as many explains nothing.

| Adjustment | Positive days beyond, fixed | Negative days beyond, fixed | Days inside today, broken |
|---|---|---|---|
| H1: leave out swaps displaced beyond 25 ticks | 0 of 24 | 0 of 11 | 122 of 128 |
| H1: leave out swaps displaced beyond 50 ticks | 1 of 24 | 0 of 11 | 103 of 128 |
| H1: leave out swaps displaced beyond 100 ticks | 0 of 24 | 0 of 11 | 83 of 128 |
| H1: leave out swaps displaced beyond 200 ticks | 0 of 24 | 0 of 11 | 59 of 128 |
| H1: leave out swaps displaced beyond 500 ticks | 1 of 24 | 0 of 11 | 37 of 128 |
| H1: leave out swaps displaced beyond 1000 ticks | 0 of 24 | 0 of 11 | 23 of 128 |
| H2: value every swap at the reference tick | 12 of 24 | 9 of 11 | 10 of 128 |

## 10. Round trips inside one block

For each flagged pool-day: pairs of swaps of the same pool, in the same block, by the same sender, in opposite directions, the second undoing at least 90% of the first. Up to 10 per pool-day, largest first. Addresses and block numbers are public chain data.

| pool | date | time (UTC) | block | log indexes | same tx | sender | sender = recipient | first USD | second USD | net stable paid to pool | tick before > between > after | liquidity before > between > after | swaps of others between |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-08-23 | 01:56:59 | 25814711 | 11, 94 | no | 0xa462d9ac… | yes | 3,565 | 3,565 | +0 | -196217 > -201654 > -196221 | 2.91e+14 > 1.74e+14 > 2.61e+16 | 1 |
| wstETH/USDC 0.05% | 2026-09-03 | 00:29:35 | 25893199 | 189, 209 | no | 0x76f30e3f… | yes | 3,307 | 3,307 | -0 | -196369 > -203291 > -196378 | 2.91e+14 > 1.74e+14 > 2.91e+14 | 1 |
| wstETH/USDC 0.05% | 2026-09-03 | 01:51:35 | 25893608 | 311, 321 | no | 0x9205a569… | yes | 80 | 80 | -0 | -196353 > -196454 > -196377 | 2.91e+14 > 2.91e+14 > 2.91e+14 | 1 |
| wstETH/USDC 0.05% | 2026-09-03 | 06:36:23 | 25895027 | 721, 743 | no | 0x140022b7… | yes | 40 | 40 | -0 | -196305 > -196254 > -196284 | 2.91e+14 > 2.91e+14 > 2.91e+14 | 1 |
| wstETH/USDC 0.05% | 2026-09-19 | 14:19:11 | 26012113 | 141, 168 | no | 0x140022b7… | yes | 3,063 | 3,066 | -3 | -195375 > -190099 > -195358 | 2e+14 > 1.75e+14 > 2e+14 | 1 |
| wstETH/USDC 0.05% | 2026-09-19 | 03:06:35 | 26008765 | 199, 221 | no | 0x009a8dba… | yes | 303 | 304 | -0 | -195428 > -194915 > -195407 | 2.3e+14 > 1.99e+14 > 2.3e+14 | 1 |
| wstETH/USDC 0.05% | 2026-09-19 | 02:36:11 | 26008613 | 276, 302 | no | 0x1f2f10d1… | yes | 129 | 129 | -0 | -195467 > -195260 > -195445 | 2.3e+14 > 1.99e+14 > 2.3e+14 | 1 |
| wstETH/USDC 0.05% | 2026-09-19 | 21:13:35 | 26014171 | 463, 485 | no | 0x140022b7… | yes | 107 | 107 | +0 | -195370 > -195557 > -195395 | 2e+14 > 2e+14 > 2e+14 | 1 |
| USDC/WETH 0.05% | 2026-08-19 | 16:09:11 | 25790255 | 71, 112 | no | 0x5aae4d2f… | yes | 3,967,441 | 3,967,589 | -148 | 199852 > 199701 > 199831 | 1.15e+19 > 1.14e+19 > 1.33e+19 | 0 |
| USDC/WETH 0.05% | 2026-08-19 | 22:17:47 | 25792090 | 14, 22 | no | 0xa462d9ac… | yes | 292,742 | 292,889 | -147 | 199049 > 198983 > 199019 | 1.86e+18 > 1.87e+18 > 3.45e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-19 | 15:10:23 | 25789962 | 318, 795 | no | 0xbdb3ba9f… | yes | 75,335 | 75,813 | -478 | 200245 > 200242 > 200245 | 1.44e+19 > 1.44e+19 > 1.44e+19 | 0 |
| USDC/WETH 0.05% | 2026-08-19 | 21:04:59 | 25791726 | 571, 620 | no | 0xc7428156… | yes | 13,362 | 14,602 | -1,240 | 199149 > 199147 > 199144 | 3.68e+18 > 3.68e+18 > 3.68e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-20 | 09:55:47 | 25795572 | 25, 134 | no | 0xd121f170… | no | 40,441 | 42,757 | -2,316 | 199017 > 199013 > 199022 | 3.5e+18 > 3.5e+18 > 3.5e+18 | 1 |
| USDC/WETH 0.05% | 2026-08-20 | 05:00:11 | 25794100 | 751, 771 | no | 0x672061b7… | yes | 14,682 | 14,681 | -1 | 199135 > 199136 > 199135 | 3.51e+18 > 3.51e+18 > 3.51e+18 | 1 |
| USDC/WETH 0.05% | 2026-08-20 | 13:34:47 | 25796660 | 271, 814 | no | 0xace0fabe… | yes | 1,012 | 913 | +99 | 199040 > 199040 > 199041 | 3.56e+18 > 3.56e+18 > 3.56e+18 | 3 |
| USDC/WETH 0.05% | 2026-08-20 | 18:56:23 | 25798266 | 927, 944 | yes | 0xe592427a… | no | 292 | 264 | +28 | 198830 > 198830 > 198830 | 3.7e+18 > 3.7e+18 > 3.7e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | 10:27:23 | 25845956 | 1478, 1485 | yes | 0x00000000… | no | 425 | 420 | -5 | 198081 > 198081 > 198081 | 4.37e+18 > 4.37e+18 > 4.37e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | 00:00:35 | 25842832 | 12, 16 | yes | 0x0a8accba… | yes | 183 | 179 | +4 | 198057 > 198057 > 198057 | 1.31e+19 > 1.31e+19 > 1.31e+19 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | 21:52:35 | 25849375 | 554, 571 | yes | 0xe592427a… | no | 167 | 151 | +16 | 198072 > 198072 > 198072 | 4.42e+18 > 4.42e+18 > 4.42e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | 19:16:59 | 25848598 | 750, 770 | yes | 0xe592427a… | no | 137 | 124 | +13 | 198046 > 198046 > 198046 | 4.41e+18 > 4.41e+18 > 4.41e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | 18:59:23 | 25862857 | 3, 88 | no | 0xbdfa9c5f… | yes | 232,187 | 234,957 | +2,771 | 198275 > 198296 > 198292 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 1 |
| USDC/WETH 0.05% | 2026-08-29 | 17:28:47 | 25862406 | 530, 547 | yes | 0xe592427a… | no | 90 | 81 | +9 | 198282 > 198282 > 198282 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | 07:11:11 | 25859331 | 607, 624 | yes | 0xe592427a… | no | 83 | 75 | +8 | 198342 > 198342 > 198342 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | 22:33:47 | 25863927 | 584, 601 | yes | 0xe592427a… | no | 82 | 75 | +8 | 198279 > 198279 > 198279 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 0 |
| USDC/WETH 0.01% | 2026-08-11 | 01:09:11 | 25728382 | 3, 58 | no | 0x5aae4d2f… | yes | 1,128,480 | 1,126,496 | -1,984 | 200969 > 202365 > 200970 | 7.54e+17 > 2.11e+17 > 7.54e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-11 | 07:43:23 | 25730341 | 6, 52 | no | 0x1f2f10d1… | yes | 409,272 | 409,272 | -0 | 200952 > 201284 > 200954 | 7.48e+17 > 5.41e+17 > 7.48e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-11 | 17:55:59 | 25733384 | 3, 40 | no | 0x5aae4d2f… | yes | 394,670 | 391,920 | -2,750 | 201008 > 201314 > 201011 | 7.62e+17 > 5.86e+17 > 7.62e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-11 | 18:44:59 | 25733628 | 10, 36 | no | 0x76f30e3f… | yes | 391,582 | 391,582 | -0 | 201026 > 201330 > 201028 | 6.3e+17 > 5.9e+17 > 6.3e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-14 | 08:31:11 | 25752091 | 39, 109 | no | 0x5aae4d2f… | yes | 3,941,956 | 3,941,021 | +935 | 200982 > 184984 > 200982 | 8.24e+17 > 5.09e+14 > 8.24e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-14 | 21:35:23 | 25756001 | 3, 81 | no | 0x5aae4d2f… | yes | 1,710,815 | 1,707,146 | -3,670 | 200942 > 212412 > 200944 | 8.26e+17 > 5.1e+14 > 8.28e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-14 | 14:24:23 | 25753853 | 3, 24 | no | 0x76f30e3f… | yes | 1,086,930 | 1,086,930 | -0 | 201012 > 202190 > 201014 | 8.24e+17 > 2.45e+17 > 6.89e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-14 | 07:28:11 | 25751779 | 3, 75 | no | 0x76f30e3f… | yes | 919,170 | 905,527 | -13,643 | 200951 > 201716 > 200959 | 8.11e+17 > 2.65e+17 > 8.11e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-15 | 20:53:35 | 25762960 | 39, 140 | no | 0x76f30e3f… | yes | 2,079,801 | 2,077,076 | +2,724 | 200922 > 199244 > 200920 | 9.16e+17 > 5.94e+17 > 9.16e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-15 | 16:18:11 | 25761591 | 3, 22 | no | 0x5aae4d2f… | yes | 805,192 | 805,192 | +0 | 200917 > 201430 > 200920 | 9.05e+17 > 5.57e+17 > 9.05e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-15 | 20:37:23 | 25762880 | 2, 27 | no | 0x9205a569… | yes | 519,456 | 515,227 | -4,228 | 200924 > 201229 > 200926 | 9.16e+17 > 7.15e+17 > 9.16e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-15 | 09:00:11 | 25759413 | 2, 36 | no | 0x9205a569… | yes | 416,406 | 416,406 | -0 | 200953 > 201205 > 200962 | 8.92e+17 > 7.06e+17 > 8.92e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-27 | 21:52:59 | 25849377 | 18, 84 | no | 0x5aae4d2f… | yes | 2,391,253 | 2,390,667 | -585 | 198073 > 206574 > 198074 | 4.64e+17 > 6.68e+15 > 4.64e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-27 | 05:03:23 | 25844344 | 3, 40 | no | 0x76f30e3f… | yes | 1,325,370 | 1,322,454 | -2,916 | 198131 > 199453 > 198134 | 4.64e+17 > 1.82e+17 > 4.64e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-27 | 23:54:59 | 25849984 | 3, 34 | no | 0x76f30e3f… | yes | 1,151,582 | 1,146,452 | -5,131 | 198030 > 199088 > 198036 | 4.67e+17 > 4.28e+17 > 4.67e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-27 | 18:48:35 | 25848457 | 20, 71 | no | 0x76f30e3f… | yes | 459,559 | 452,252 | +7,307 | 198083 > 197483 > 198077 | 4.66e+17 > 8.66e+16 > 4.62e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-29 | 21:09:11 | 25863505 | 31, 97 | no | 0x76f30e3f… | yes | 1,480,144 | 1,480,554 | -410 | 198272 > 194252 > 198271 | 4.93e+17 > 5.97e+16 > 4.93e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-29 | 01:32:23 | 25857639 | 3, 33 | no | 0x5aae4d2f… | yes | 769,095 | 762,470 | -6,625 | 198307 > 199090 > 198313 | 4.95e+17 > 3.54e+17 > 4.95e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-29 | 01:25:47 | 25857606 | 18, 44 | no | 0x45e9b049… | yes | 315,655 | 315,655 | +0 | 198309 > 198608 > 198311 | 4.95e+17 > 3.98e+17 > 4.95e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-29 | 02:41:47 | 25857986 | 15, 35 | no | 0x9205a569… | yes | 269,173 | 269,207 | -34 | 198325 > 198104 > 198322 | 4.96e+17 > 4.86e+17 > 4.93e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-30 | 13:04:23 | 25868266 | 13, 120 | no | 0x76f30e3f… | yes | 1,850,185 | 1,849,224 | +961 | 198201 > 191200 > 198201 | 4.92e+17 > 2.14e+16 > 4.92e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-30 | 13:00:35 | 25868247 | 2, 21 | no | 0x9205a569… | yes | 256,835 | 256,835 | -0 | 198212 > 198430 > 198215 | 4.92e+17 > 4.57e+17 > 4.92e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-30 | 09:05:59 | 25867079 | 29, 65 | no | 0x76f30e3f… | yes | 227,723 | 227,739 | -16 | 198251 > 198064 > 198248 | 4.94e+17 > 4.85e+17 > 4.95e+17 | 1 |
| USDC/WETH 0.01% | 2026-08-30 | 13:30:23 | 25868396 | 3, 26 | no | 0x76f30e3f… | yes | 214,645 | 211,582 | -3,064 | 198214 > 198395 > 198218 | 4.92e+17 > 4.51e+17 > 4.92e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-03 | 22:57:59 | 25899918 | 30, 53 | no | 0x9205a569… | yes | 422,860 | 420,411 | +2,449 | 198086 > 197678 > 198083 | 4.72e+17 > 3.6e+17 > 4.72e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-03 | 12:41:11 | 25896843 | 6, 35 | no | 0x76f30e3f… | yes | 347,172 | 347,172 | -0 | 198419 > 198723 > 198421 | 4.72e+17 > 4.48e+17 > 4.72e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-03 | 20:07:47 | 25899069 | 15, 41 | no | 0x76f30e3f… | yes | 295,435 | 293,901 | +1,535 | 198024 > 197724 > 198022 | 4.51e+17 > 3.54e+17 > 4.51e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-03 | 14:26:11 | 25897368 | 2, 35 | no | 0x1f2f10d1… | yes | 286,134 | 275,871 | -10,263 | 198292 > 198540 > 198305 | 4.76e+17 > 4.75e+17 > 4.76e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-07 | 08:58:35 | 25924435 | 3, 106 | no | 0x5aae4d2f… | yes | 1,840,819 | 1,836,548 | -4,271 | 198110 > 206583 > 198114 | 5.08e+17 > 6.61e+15 > 5.08e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-07 | 11:26:23 | 25925170 | 2, 59 | no | 0x1f2f10d1… | yes | 634,056 | 602,964 | -31,093 | 198113 > 198643 > 198138 | 5.07e+17 > 4.55e+17 > 5.07e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-07 | 08:30:23 | 25924294 | 2, 46 | no | 0x45e9b049… | yes | 488,300 | 488,300 | -0 | 198118 > 198518 > 198120 | 5.07e+17 > 4.57e+17 > 5.07e+17 | 2 |
| USDC/WETH 0.01% | 2026-09-07 | 02:22:23 | 25922464 | 3, 21 | no | 0x76f30e3f… | yes | 380,784 | 380,784 | -0 | 198055 > 198359 > 198059 | 4.74e+17 > 4.77e+17 > 4.74e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-11 | 04:46:59 | 25951860 | 30, 81 | no | 0x76f30e3f… | yes | 1,591,689 | 1,592,261 | -572 | 198254 > 193939 > 198253 | 5.22e+17 > 5.77e+16 > 5.22e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-11 | 16:32:23 | 25955376 | 28, 91 | no | 0x9205a569… | yes | 1,569,141 | 1,570,089 | -948 | 197833 > 190929 > 197831 | 4.26e+17 > 1.14e+16 > 4.26e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-11 | 06:19:47 | 25952322 | 11, 71 | no | 0x1f2f10d1… | yes | 576,469 | 576,469 | -0 | 198208 > 198684 > 198211 | 5.22e+17 > 4.35e+17 > 5.22e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-11 | 14:15:35 | 25954696 | 76, 88 | no | 0x5aae4d2f… | yes | 328,029 | 328,029 | +0 | 197629 > 197937 > 197635 | 3.93e+17 > 4.62e+17 > 3.93e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-16 | 02:33:47 | 25987074 | 2, 55 | no | 0x45e9b049… | yes | 1,258,231 | 1,258,231 | +0 | 198475 > 211745 > 198476 | 4.86e+17 > 5.07e+14 > 4.86e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-16 | 13:12:11 | 25990256 | 2, 45 | no | 0x45e9b049… | yes | 433,339 | 433,339 | +0 | 198506 > 199104 > 198510 | 4.61e+17 > 1.53e+17 > 4.59e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-16 | 22:54:23 | 25993155 | 2, 30 | no | 0x1f2f10d1… | yes | 383,320 | 379,460 | -3,860 | 198528 > 199035 > 198532 | 4.59e+17 > 1.53e+17 > 4.6e+17 | 1 |
| USDC/WETH 0.01% | 2026-09-16 | 13:49:35 | 25990441 | 2, 97 | no | 0x1f2f10d1… | yes | 375,035 | 375,035 | -0 | 198502 > 198938 > 198507 | 4.61e+17 > 1.9e+17 > 4.61e+17 | 1 |

| pool | date | abs diff USD | round trips found (max 10) | their USD, both legs |
|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-08-23 | -1,602 | 1 | 7,129 |
| wstETH/USDC 0.05% | 2026-09-03 | -2,379 | 3 | 6,853 |
| wstETH/USDC 0.05% | 2026-09-19 | 1,415 | 5 | 7,342 |
| USDC/WETH 0.05% | 2026-08-19 | 7,766,114 | 10 | 8,705,439 |
| USDC/WETH 0.05% | 2026-08-20 | 1,273,956 | 10 | 116,279 |
| USDC/WETH 0.05% | 2026-08-27 | 1,112,611 | 10 | 2,719 |
| USDC/WETH 0.05% | 2026-08-29 | 368,871 | 10 | 468,241 |
| USDC/WETH 0.01% | 2026-08-11 | 396,150 | 10 | 7,203,880 |
| USDC/WETH 0.01% | 2026-08-14 | 1,070,036 | 10 | 16,626,023 |
| USDC/WETH 0.01% | 2026-08-15 | 221,082 | 10 | 10,375,651 |
| USDC/WETH 0.01% | 2026-08-27 | -891,843 | 10 | 14,433,892 |
| USDC/WETH 0.01% | 2026-08-29 | 425,831 | 10 | 8,244,802 |
| USDC/WETH 0.01% | 2026-08-30 | 690,977 | 10 | 6,940,429 |
| USDC/WETH 0.01% | 2026-09-03 | 710,478 | 10 | 4,630,727 |
| USDC/WETH 0.01% | 2026-09-07 | -833,802 | 10 | 10,143,778 |
| USDC/WETH 0.01% | 2026-09-11 | 1,615,421 | 10 | 11,029,300 |
| USDC/WETH 0.01% | 2026-09-16 | -611,518 | 10 | 7,794,721 |

## 11. The flagged pool-days, hour by hour

Ours against the external HOURLY candles (`make fetch-external-hourly`; the source serves the last 1,000 hours). For each flagged pool-day: how the day's difference is spread over its hours. Hours the source omits count as 0 on its side.

| pool | date | day diff USD (daily candle) | sum of hourly diffs | hours beyond 1% | largest three hourly diffs (hour: USD) | share of the day diff in those three |
|---|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-08-23 | -1,602 | -1,602 | 1 of 24 | 01h: -1,591, 00h: -7, 14h: -5 | +100.11% |
| wstETH/USDC 0.05% | 2026-09-03 | -2,379 | -2,379 | 1 of 24 | 00h: -2,381, 13h: +1, 21h: +1 | +100.02% |
| wstETH/USDC 0.05% | 2026-09-19 | 1,415 | 1,415 | 3 of 23 | 14h: +1,410, 03h: +14, 16h: -8 | +100.05% |
| USDC/WETH 0.05% | 2026-08-19 | 7,766,114 | 7,766,114 | 4 of 24 | 15h: +6,361,336, 14h: +685,134, 20h: +288,739 | +94.45% |
| USDC/WETH 0.05% | 2026-08-20 | 1,273,956 | 1,273,956 | 3 of 24 | 00h: +767,319, 09h: +333,494, 08h: +97,824 | +94.09% |
| USDC/WETH 0.05% | 2026-08-27 | 1,112,611 | 1,112,611 | 4 of 24 | 00h: +1,105,947, 07h: -24,807, 05h: +21,619 | +99.11% |
| USDC/WETH 0.05% | 2026-08-29 | 368,871 | 368,871 | 3 of 24 | 14h: +232,423, 15h: +103,959, 02h: +38,701 | +101.68% |
| USDC/WETH 0.01% | 2026-08-11 | 396,150 | 396,150 | 4 of 24 | 14h: +547,402, 01h: -120,358, 07h: -13,531 | +104.38% |
| USDC/WETH 0.01% | 2026-08-14 | 1,070,036 | 1,070,036 | 6 of 24 | 08h: +1,607,300, 21h: -403,737, 14h: -102,986 | +102.85% |
| USDC/WETH 0.01% | 2026-08-15 | 221,082 | 221,082 | 3 of 24 | 20h: +272,201, 16h: -45,195, 00h: +15,586 | +109.73% |
| USDC/WETH 0.01% | 2026-08-27 | -891,843 | -891,843 | 6 of 24 | 21h: -892,887, 00h: +197,890, 05h: -146,947 | +94.40% |
| USDC/WETH 0.01% | 2026-08-29 | 425,831 | 425,831 | 5 of 24 | 21h: +328,227, 02h: +68,482, 15h: +63,582 | +108.09% |
| USDC/WETH 0.01% | 2026-08-30 | 690,977 | 690,977 | 3 of 24 | 13h: +673,964, 01h: +8,588, 00h: +8,124 | +99.96% |
| USDC/WETH 0.01% | 2026-09-03 | 710,478 | 710,478 | 3 of 24 | 17h: +631,096, 05h: +38,249, 08h: +28,347 | +98.20% |
| USDC/WETH 0.01% | 2026-09-07 | -833,802 | -833,802 | 2 of 24 | 08h: -717,047, 11h: -72,865, 02h: -10,616 | +96.01% |
| USDC/WETH 0.01% | 2026-09-11 | 1,615,421 | 1,615,421 | 4 of 24 | 14h: +643,407, 16h: +602,740, 04h: +379,704 | +100.65% |
| USDC/WETH 0.01% | 2026-09-16 | -611,518 | -611,518 | 2 of 24 | 02h: -517,498, 13h: -40,249, 22h: -16,343 | +93.88% |

## 12. Flagged days on which the source has MORE than the chain

Leaving swaps out (H1) can only lower our figure, so it cannot account for these. What can be measured is put side by side; whatever a row does not account for stays unexplained.

| pool | date | rel diff | abs diff USD | displaced swaps | displaced USD | rel diff valued at the reference (H2) | largest hourly diff | sibling pool, same day |
|---|---|---|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-08-23 | -7.82% | -1,602 | 11 | 9,512 | -0.05% | 01h: -1,591 | +0.01% |
| wstETH/USDC 0.05% | 2026-09-03 | -17.69% | -2,379 | 7 | 6,836 | +0.13% | 00h: -2,381 | -0.81% |
| USDC/WETH 0.01% | 2026-08-27 | -1.65% | -891,843 | 59 | 17,743,704 | +0.50% | 21h: -892,887 | +1.35% |
| USDC/WETH 0.01% | 2026-09-07 | -2.04% | -833,802 | 56 | 13,055,338 | +0.02% | 08h: -717,047 | -0.03% |
| USDC/WETH 0.01% | 2026-09-16 | -1.27% | -611,518 | 33 | 8,213,804 | -0.02% | 02h: -517,498 | +0.01% |
