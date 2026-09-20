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

Our volume recomputed with the day cut moved from -12 h to +12 h in steps of 1 h, against the external days, over 2026-08-21 to 2026-09-19 (days complete on our side under every shift). A positive shift moves swaps from late in the day into the next day. Cell: sum of |our day - external day| divided by the external total.

| Shift (h) | wstETH/USDC 0.3% | wstETH/USDC 0.05% | USDC/WETH 0.05% | USDC/WETH 0.01% |
|---|---|---|---|---|
| -12 | 12.45% | 1.15% | 14.55% | 11.73% |
| -11 | 14.17% | 1.14% | 13.13% | 10.78% |
| -10 | 12.71% | 1.14% | 11.97% | 10.21% |
| -9 | 12.52% | 0.94% | 10.35% | 9.87% |
| -8 | 16.56% | 0.40% | 10.13% | 8.76% |
| -7 | 12.48% | 0.39% | 9.30% | 7.97% |
| -6 | 10.67% | 0.39% | 8.48% | 7.45% |
| -5 | 9.68% | 0.38% | 7.24% | 5.55% |
| -4 | 9.64% | 0.38% | 6.77% | 5.05% |
| -3 | 11.87% | 0.38% | 5.64% | 3.87% |
| -2 | 6.46% | 0.34% | 3.95% | 2.72% |
| -1 | 2.05% | 0.23% | 2.57% | 1.88% |
| +0 | 0.42% | 0.13% | 0.28% | 0.69% |
| +1 | 13.02% | 0.18% | 2.69% | 1.81% |
| +2 | 13.90% | 0.19% | 5.90% | 3.44% |
| +3 | 16.35% | 0.28% | 8.75% | 6.29% |
| +4 | 19.94% | 0.29% | 11.35% | 7.53% |
| +5 | 21.42% | 0.30% | 12.69% | 7.93% |
| +6 | 27.30% | 0.35% | 15.32% | 9.49% |
| +7 | 26.58% | 0.36% | 16.25% | 9.84% |
| +8 | 27.64% | 0.40% | 19.96% | 11.38% |
| +9 | 30.23% | 102.78% | 21.85% | 12.19% |
| +10 | 32.39% | 197.85% | 26.82% | 14.83% |
| +11 | 35.65% | 197.87% | 31.30% | 17.48% |
| +12 | 41.39% | 197.89% | 33.78% | 18.79% |

| Pool | Shift with the smallest value | Value there | Value at shift 0 |
|---|---|---|---|
| wstETH/USDC 0.3% | +0 h | 0.42% | 0.42% |
| wstETH/USDC 0.05% | +0 h | 0.13% | 0.13% |
| USDC/WETH 0.05% | +0 h | 0.28% | 0.28% |
| USDC/WETH 0.01% | +0 h | 0.69% | 0.69% |

## 2. The stablecoin leg against the other leg at the pool's own price

Same swaps valued two ways: the stablecoin leg at 1 USD, and the other leg converted at the pool price right after each swap (`sqrt_price_x96`). Swaps with a zero leg are left out of this table, and so are swaps that left the pool at the price limit (|tick| > 800,000), which are counted in their own column.

| Pool | Swaps valued | Swaps at the price limit | Stable leg USD | Other leg USD | Other / stable - 1 | Per swap: p1 | median | p99 |
|---|---|---|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 621 | 3 | 58,312 | 57,902 | -0.7045% | -8.0947% | -0.0079% | +3.2932% |
| wstETH/USDC 0.05% | 4,800 | 0 | 26,357,758 | 26,353,869 | -0.0148% | -1.2128% | -0.0010% | +1.3024% |
| USDC/WETH 0.05% | 236,169 | 0 | 2,557,393,935 | 2,557,297,269 | -0.0038% | -0.0521% | -0.0298% | +0.0510% |
| USDC/WETH 0.01% | 656,794 | 0 | 1,469,495,354 | 1,469,793,644 | +0.0203% | -0.0351% | -0.0003% | +0.0362% |

## 3. Distribution of the daily relative difference (ours - external) / external

Compared days only (see the rules at the top of `reconciliation.md`).

| Pool | Days | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 30 | -2.04% | -0.55% | +0.01% | +0.47% | +3.14% |
| wstETH/USDC 0.3% | 30 | -6.75% | -0.34% | -0.09% | +0.07% | +0.94% |
| wstETH/USDC 0.05% | 30 | -17.69% | -0.11% | +0.02% | +1.34% | +17.84% |
| USDC/WETH 0.05% | 30 | -0.15% | -0.03% | +0.04% | +0.40% | +1.44% |

By activity level: pool-days sorted by our number of swaps and cut in three groups of equal size.

| Activity | Pool-days | Swaps per day (range) | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|---|
| low | 40 | 2 to 118 | -6.75% | -0.31% | -0.03% | +0.08% | +2.55% |
| middle | 40 | 119 to 7,615 | -17.69% | -0.05% | +0.19% | +0.64% | +17.84% |
| high | 40 | 7,879 to 26,431 | -2.04% | -0.22% | +0.01% | +0.20% | +3.14% |

## 4. Partial days

The first and the last day of the window are incomplete on our side: the backfill starts and ends inside a day. The external source reports whole days.

| Pool | Date | Our swaps | Our USD | External USD | Rel diff |
|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-08-20 | 8 | 21 | 22 | -7.60% |
| wstETH/USDC 0.3% | 2026-09-20 | 15 | 1,766 | 1,770 | -0.24% |
| wstETH/USDC 0.05% | 2026-08-20 | 161 | 4,479 | 5,881 | -23.84% |
| wstETH/USDC 0.05% | 2026-09-20 | 45 | 752 | 765 | -1.72% |
| USDC/WETH 0.05% | 2026-08-20 | 5,119 | 92,781,350 | 119,562,198 | -22.40% |
| USDC/WETH 0.05% | 2026-09-20 | 3,498 | 26,024,785 | 26,322,590 | -1.13% |
| USDC/WETH 0.01% | 2026-08-20 | 17,469 | 74,441,867 | 114,810,733 | -35.16% |
| USDC/WETH 0.01% | 2026-09-20 | 12,398 | 26,675,148 | 27,071,485 | -1.46% |

Our first swap: 2026-08-20 07:10:59 UTC. Our last swap: 2026-09-20 14:16:35 UTC.

## 5. Zero-leg swaps and filters

This pipeline filters nothing: every Swap log of the pools is kept and counted. Whether the external source filters any trades is not documented (docs/EXTERNAL_SOURCE.md).

| Pool | Swaps | With one zero leg | With both legs zero | USD volume of the zero-leg swaps |
|---|---|---|---|---|
| wstETH/USDC 0.3% | 625 | 1 | 0 | 0.000000 |
| wstETH/USDC 0.05% | 4,800 | 0 | 0 | 0.000000 |
| USDC/WETH 0.05% | 236,179 | 10 | 0 | 0.000005 |
| USDC/WETH 0.01% | 656,800 | 6 | 0 | 0.000000 |

Pool-days present on one side only: 0.

## 6. Pools of the same pair, added up

For every compared day: ours and the external figure summed over the pools that trade the same two tokens. Listed: the days on which at least one pool of the pair is beyond 1% while the sum is within it.

### USDC/WETH: USDC/WETH 0.01% + USDC/WETH 0.05%

Days with every pool of the pair compared: 30.

| date | USDC/WETH 0.01% rel diff | USDC/WETH 0.05% rel diff | pair ours USD | pair external USD | pair abs diff USD | pair rel diff |
|---|---|---|---|---|---|---|
| 2026-08-27 | -1.65% | +1.35% | 136,285,294 | 136,064,526 | 220,768 | +0.16% |
| 2026-08-30 | +2.03% | +0.08% | 107,870,015 | 107,117,050 | 752,966 | +0.70% |
| 2026-09-03 | +1.59% | -0.15% | 144,012,923 | 143,454,767 | 558,156 | +0.39% |
| 2026-09-07 | -2.04% | -0.03% | 95,490,154 | 96,341,279 | -851,125 | -0.88% |
| 2026-09-16 | -1.27% | +0.01% | 156,438,790 | 157,037,110 | -598,320 | -0.38% |

Pair-days beyond 1%: 2 of 30. Pair daily rel diff: min, p25, median, p75, max = -0.88% | -0.12% | +0.06% | +0.39% | +1.61%.

### wstETH/USDC: wstETH/USDC 0.3% + wstETH/USDC 0.05%

Days with every pool of the pair compared: 30.

| date | wstETH/USDC 0.3% rel diff | wstETH/USDC 0.05% rel diff | pair ours USD | pair external USD | pair abs diff USD | pair rel diff |
|---|---|---|---|---|---|---|
| none |  |  |  |  |  |  | 

Pair-days beyond 1%: 13 of 30. Pair daily rel diff: min, p25, median, p75, max = -17.67% | -0.14% | +0.03% | +1.34% | +15.00%.


## 7. The same day across the pools

Compared days. Volume vs median: our USD volume of the day, all pools, over the median of that figure. Marked `<<`: three or more pools beyond 1% with the same sign.

| date | weekday | volume vs median | USDC/WETH 0.01% | wstETH/USDC 0.3% | wstETH/USDC 0.05% | USDC/WETH 0.05% | |
|---|---|---|---|---|---|---|---|
| 2026-08-21 | Fri | 2.51x | +0.47% | -0.81% | +2.10% | +0.12% |  |
| 2026-08-22 | Sat | 1.53x | +0.06% | +0.86% | -0.18% | +0.08% |  |
| 2026-08-23 | Sun | 1.32x | +0.01% | +0.01% | -7.82% | +0.40% |  |
| 2026-08-24 | Mon | 1.46x | +0.92% | -0.29% | +2.04% | +0.60% |  |
| 2026-08-25 | Tue | 1.22x | +0.25% | -0.03% | -2.44% | +0.93% |  |
| 2026-08-26 | Wed | 0.92x | -0.60% | -0.32% | +1.60% | +0.19% |  |
| 2026-08-27 | Thu | 1.14x | -1.65% | -0.31% | -0.06% | +1.35% |  |
| 2026-08-28 | Fri | 1.08x | -0.65% | +0.94% | -0.14% | +0.93% |  |
| 2026-08-29 | Sat | 0.42x | +1.80% | -0.12% | +1.34% | +1.44% | << |
| 2026-08-30 | Sun | 0.90x | +2.03% | +0.07% | +1.05% | +0.08% |  |
| 2026-08-31 | Mon | 0.87x | +0.65% | -6.75% | +1.71% | +0.63% |  |
| 2026-09-01 | Tue | 0.92x | +0.62% | +0.19% | -0.08% | +0.64% |  |
| 2026-09-02 | Wed | 0.93x | +0.20% | +0.18% | +0.55% | +0.33% |  |
| 2026-09-03 | Thu | 1.21x | +1.59% | -0.81% | -17.69% | -0.15% |  |
| 2026-09-04 | Fri | 1.15x | -0.01% | +0.73% | +2.55% | -0.02% |  |
| 2026-09-05 | Sat | 0.40x | -0.32% | -0.31% | +0.33% | +0.02% |  |
| 2026-09-06 | Sun | 0.76x | -0.55% | +0.00% | +6.85% | -0.01% |  |
| 2026-09-07 | Mon | 0.80x | -2.04% | +0.36% | +0.02% | -0.03% |  |
| 2026-09-08 | Tue | 0.78x | -0.05% | +0.08% | -0.07% | -0.04% |  |
| 2026-09-09 | Wed | 1.03x | +0.10% | -0.14% | +0.51% | -0.07% |  |
| 2026-09-10 | Thu | 0.85x | -0.02% | -0.30% | -0.00% | -0.03% |  |
| 2026-09-11 | Fri | 1.96x | +3.14% | -0.76% | -0.11% | +0.36% |  |
| 2026-09-12 | Sat | 0.36x | -0.31% | -1.81% | -5.05% | +0.04% |  |
| 2026-09-13 | Sun | 0.52x | -0.04% | -0.34% | -0.17% | -0.03% |  |
| 2026-09-14 | Mon | 1.16x | +0.01% | -0.58% | +0.40% | -0.05% |  |
| 2026-09-15 | Tue | 1.33x | -0.22% | -0.09% | -0.06% | -0.05% |  |
| 2026-09-16 | Wed | 1.31x | -1.27% | +0.02% | +0.48% | +0.01% |  |
| 2026-09-17 | Thu | 0.97x | -0.79% | -0.01% | -0.02% | +0.01% |  |
| 2026-09-18 | Fri | 1.41x | +0.14% | +0.06% | +0.01% | +0.02% |  |
| 2026-09-19 | Sat | 0.91x | -0.55% | -0.82% | +17.84% | -0.01% |  |

Days marked: 2026-08-29.

## 8. One swap the size of the difference

For each compared pool-day beyond 1%: our swaps of that pool whose USD value is within 5% of the absolute difference, looking at the UTC day plus 10 minutes before its first midnight and after its last. The day's median tick and liquidity are given to compare each swap with; nothing is called anomalous here.

| pool | date | rel diff | abs diff USD | swaps that size | of them, within 10 min of a midnight |
|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-08-31 | -6.75% | -9 | 0 | 0 |
| wstETH/USDC 0.3% | 2026-09-12 | -1.81% | -62 | 1 | 0 |
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
| USDC/WETH 0.05% | 2026-08-27 | +1.35% | 1,112,611 | 1 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | +1.44% | 368,871 | 0 | 0 |
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
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 04:46:59 | 1,591,689.34 | -1.47% |  | 193939 | 198049 | 5.77e+16 | 4.912e+17 | 19,854 | 3.0% |
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 04:46:59 | 1,592,261.16 | -1.43% |  | 198253 | 198049 | 5.216e+17 | 4.912e+17 | 19,854 | 3.0% |
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 16:32:23 | 1,569,141.11 | -2.86% |  | 190929 | 198049 | 1.144e+16 | 4.912e+17 | 19,854 | 3.0% |
| USDC/WETH 0.01% | 2026-09-11 | 2026-09-11 16:32:23 | 1,570,088.61 | -2.81% |  | 197831 | 198049 | 4.259e+17 | 4.912e+17 | 19,854 | 3.0% |

## 9. Swaps executed away from the pool's own recent price

Two readings of the same suspicion are put to the test, neither taken as true: (H1) the external source leaves such swaps out and this pipeline counts every log; (H2) the source counts them but values them at a going price, while this pipeline values every swap by its stablecoin leg.

**Definition.** Reference tick = median tick of the pool over the 21 consecutive swaps centred on the swap. Displacement = the larger of |tick before the swap - reference| and |tick after it - reference|. A swap is *displaced* beyond N when its displacement is more than N ticks (1 tick = 0.01% in price). N = 100 here, and the table says why.

| Pool | Swaps | p50 | p90 | p99 | p99.9 | p99.99 | max | >25 | >50 | >100 | >200 | >500 | >1000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 656,800 | 1 | 5 | 17 | 188 | 1,064 | 14,353 | 4,144 | 2,295 | 1,427 | 603 | 189 | 84 |
| USDC/WETH 0.05% | 236,179 | 0 | 5 | 15 | 38 | 86 | 258 | 661 | 100 | 9 | 3 | 0 | 0 |
| wstETH/USDC 0.05% | 4,800 | 21 | 72 | 780 | 6,914 | 6,938 | 6,938 | 2,028 | 814 | 301 | 152 | 70 | 42 |
| wstETH/USDC 0.3% | 625 | 39 | 219 | 16,052 | 1,082,989 | 1,082,989 | 1,082,989 | 407 | 240 | 137 | 69 | 37 | 27 |

Why 100: the deepest pool trades the same asset at the same time as its sibling and hardly ever goes beyond it, so beyond it a swap is about that pool's liquidity at that moment and not about the market. In the two quiet pools 21 swaps span hours, real price drift enters the displacement, and the definition separates less; their figures below are given with that caveat.

### The 12 flagged pool-days

Displaced = beyond 100 ticks. *Without them* is H1; *valued at the reference* is H2 (every swap of the day, the non-stable leg at the reference tick).

| pool | date | rel diff | abs diff USD | displaced swaps | displaced USD | rel diff without them (H1) | rel diff valued at the reference (H2) |
|---|---|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-08-23 | -7.82% | -1,602 | 11 | 9,512 | -54.26% | -0.05% |
| wstETH/USDC 0.05% | 2026-09-03 | -17.69% | -2,379 | 7 | 6,836 | -68.52% | +0.13% |
| wstETH/USDC 0.05% | 2026-09-19 | +17.84% | 1,415 | 21 | 8,196 | -85.47% | +0.03% |
| USDC/WETH 0.05% | 2026-08-27 | +1.35% | 1,112,611 | 0 | 0 | +1.35% | +1.37% |
| USDC/WETH 0.05% | 2026-08-29 | +1.44% | 368,871 | 0 | 0 | +1.44% | +1.46% |
| USDC/WETH 0.01% | 2026-08-27 | -1.65% | -891,843 | 59 | 17,743,704 | -34.54% | +0.50% |
| USDC/WETH 0.01% | 2026-08-29 | +1.80% | 425,831 | 45 | 9,705,143 | -39.21% | +0.83% |
| USDC/WETH 0.01% | 2026-08-30 | +2.03% | 690,977 | 29 | 6,868,442 | -18.13% | +0.07% |
| USDC/WETH 0.01% | 2026-09-03 | +1.59% | 710,478 | 33 | 5,265,880 | -10.19% | +1.62% |
| USDC/WETH 0.01% | 2026-09-07 | -2.04% | -833,802 | 56 | 13,055,338 | -34.04% | +0.02% |
| USDC/WETH 0.01% | 2026-09-11 | +3.14% | 1,615,421 | 43 | 12,338,144 | -20.87% | +1.35% |
| USDC/WETH 0.01% | 2026-09-16 | -1.27% | -611,518 | 33 | 8,213,804 | -18.32% | -0.02% |

### All 120 compared pool-days

Pearson correlation of the daily difference (ours - external, USD) with:

- the USD of displaced swaps (H1): -0.092
- ours minus ours valued at the reference (H2): +0.716

Per pool (the two liquid pools dominate any correlation in USD):

| Pool | Pool-days | r with displaced USD (H1) | r with the revaluation (H2) |
|---|---|---|---|
| USDC/WETH 0.01% | 30 | -0.184 | +0.913 |
| wstETH/USDC 0.3% | 30 | -0.810 | +0.923 |
| wstETH/USDC 0.05% | 30 | -0.394 | -0.886 |
| USDC/WETH 0.05% | 30 | -0.131 | -0.036 |

### Would it make the days reconcile? Both directions

Pool-days beyond 1% today that come inside it, and pool-days inside it today that would leave it. A hypothesis that fixes days by breaking as many explains nothing.

| Adjustment | Positive days beyond, fixed | Negative days beyond, fixed | Days inside today, broken |
|---|---|---|---|
| H1: leave out swaps displaced beyond 25 ticks | 0 of 15 | 0 of 9 | 93 of 96 |
| H1: leave out swaps displaced beyond 50 ticks | 1 of 15 | 0 of 9 | 80 of 96 |
| H1: leave out swaps displaced beyond 100 ticks | 0 of 15 | 0 of 9 | 64 of 96 |
| H1: leave out swaps displaced beyond 200 ticks | 0 of 15 | 0 of 9 | 48 of 96 |
| H1: leave out swaps displaced beyond 500 ticks | 0 of 15 | 0 of 9 | 31 of 96 |
| H1: leave out swaps displaced beyond 1000 ticks | 0 of 15 | 0 of 9 | 19 of 96 |
| H2: value every swap at the reference tick | 7 of 15 | 8 of 9 | 6 of 96 |

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
| USDC/WETH 0.05% | 2026-08-27 | 10:27:23 | 25845956 | 1478, 1485 | yes | 0x00000000… | no | 425 | 420 | -5 | 198081 > 198081 > 198081 | 4.37e+18 > 4.37e+18 > 4.37e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | 00:00:35 | 25842832 | 12, 16 | yes | 0x0a8accba… | yes | 183 | 179 | +4 | 198057 > 198057 > 198057 | 1.31e+19 > 1.31e+19 > 1.31e+19 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | 21:52:35 | 25849375 | 554, 571 | yes | 0xe592427a… | no | 167 | 151 | +16 | 198072 > 198072 > 198072 | 4.42e+18 > 4.42e+18 > 4.42e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-27 | 19:16:59 | 25848598 | 750, 770 | yes | 0xe592427a… | no | 137 | 124 | +13 | 198046 > 198046 > 198046 | 4.41e+18 > 4.41e+18 > 4.41e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | 18:59:23 | 25862857 | 3, 88 | no | 0xbdfa9c5f… | yes | 232,187 | 234,957 | +2,771 | 198275 > 198296 > 198292 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 1 |
| USDC/WETH 0.05% | 2026-08-29 | 17:28:47 | 25862406 | 530, 547 | yes | 0xe592427a… | no | 90 | 81 | +9 | 198282 > 198282 > 198282 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | 07:11:11 | 25859331 | 607, 624 | yes | 0xe592427a… | no | 83 | 75 | +8 | 198342 > 198342 > 198342 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 0 |
| USDC/WETH 0.05% | 2026-08-29 | 22:33:47 | 25863927 | 584, 601 | yes | 0xe592427a… | no | 82 | 75 | +8 | 198279 > 198279 > 198279 | 4.51e+18 > 4.51e+18 > 4.51e+18 | 0 |
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
| USDC/WETH 0.05% | 2026-08-27 | 1,112,611 | 10 | 2,719 |
| USDC/WETH 0.05% | 2026-08-29 | 368,871 | 10 | 468,241 |
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
| USDC/WETH 0.05% | 2026-08-27 | 1,112,611 | 1,112,611 | 4 of 24 | 00h: +1,105,947, 07h: -24,807, 05h: +21,619 | +99.11% |
| USDC/WETH 0.05% | 2026-08-29 | 368,871 | 368,871 | 3 of 24 | 14h: +232,423, 15h: +103,959, 02h: +38,701 | +101.68% |
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
