# Reconciliation report

Database `onchain`, generated 2026-09-20 15:48 UTC by `make reconcile`. Compared: only days complete on our side whose external candle was closed when downloaded. Flagged: beyond **1%** (`--threshold`) AND beyond **1,000 USD** (`--abs-threshold`).

## Summary

- **A, internal** (recomputation from `raw_swaps` vs `swaps_daily`, raw units): **exact, 0 differences**.
- **B, external** (our `volume_usd` vs geckoterminal): 128 pool-days present on both sides, 120 compared, **12 beyond both thresholds**, 12 beyond the relative threshold only, 8 excluded (listed below with the reason), 0 present on one side only.
- The exit code reflects A only. What the differences in B mean is not decided here.

### B per pool, compared days

| Pool | Days | Ours USD | External USD | Total diff | Median daily diff | Largest daily diff (absolute) | Days beyond the relative threshold | Days beyond both |
|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 30 | 1,368,378,340 | 1,367,066,941 | +0.10% | -0.00% | 3.14% | 7 | 7 |
| wstETH/USDC 0.3% | 30 | 57,219 | 57,452 | -0.41% | -0.10% | 6.75% | 2 | 0 |
| wstETH/USDC 0.05% | 30 | 26,352,526 | 26,382,122 | -0.11% | +0.02% | 17.84% | 13 | 3 |
| USDC/WETH 0.05% | 30 | 2,438,587,799 | 2,432,722,484 | +0.24% | +0.03% | 1.44% | 2 | 2 |

### B per pool, every day present on both sides, for reference

| Pool | Days | Ours USD | External USD | Total diff | Median daily diff | Largest daily diff (absolute) | Days beyond the relative threshold | Days beyond both |
|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 32 | 1,469,495,354 | 1,508,949,158 | -2.61% | -0.01% | 35.16% | 9 |  |
| wstETH/USDC 0.3% | 32 | 59,006 | 59,245 | -0.40% | -0.13% | 7.60% | 3 |  |
| wstETH/USDC 0.05% | 32 | 26,357,758 | 26,388,768 | -0.12% | +0.00% | 23.84% | 15 |  |
| USDC/WETH 0.05% | 32 | 2,557,393,935 | 2,578,607,272 | -0.82% | +0.02% | 22.40% | 4 |  |

## A: differences (expected: none)

None.

## B: days present on one side only

None.

## B: pool-days beyond 1% and 1,000 USD

| pool | date | our USD | external USD | abs diff USD | rel diff |
|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-09-19 | 9,349 | 7,934 | 1,415 | +17.84% |
| wstETH/USDC 0.05% | 2026-09-03 | 11,069 | 13,448 | -2,379 | -17.69% |
| wstETH/USDC 0.05% | 2026-08-23 | 18,880 | 20,482 | -1,602 | -7.82% |
| USDC/WETH 0.01% | 2026-09-11 | 53,003,066 | 51,387,646 | 1,615,421 | +3.14% |
| USDC/WETH 0.01% | 2026-09-07 | 39,974,422 | 40,808,224 | -833,802 | -2.04% |
| USDC/WETH 0.01% | 2026-08-30 | 34,771,776 | 34,080,798 | 690,977 | +2.03% |
| USDC/WETH 0.01% | 2026-08-29 | 24,094,473 | 23,668,642 | 425,831 | +1.80% |
| USDC/WETH 0.01% | 2026-08-27 | 53,058,152 | 53,949,995 | -891,843 | -1.65% |
| USDC/WETH 0.01% | 2026-09-03 | 45,428,762 | 44,718,283 | 710,478 | +1.59% |
| USDC/WETH 0.05% | 2026-08-29 | 25,955,000 | 25,586,129 | 368,871 | +1.44% |
| USDC/WETH 0.05% | 2026-08-27 | 83,227,142 | 82,114,531 | 1,112,611 | +1.35% |
| USDC/WETH 0.01% | 2026-09-16 | 47,554,508 | 48,166,026 | -611,518 | -1.27% |

## B: beyond 1%, but below the absolute threshold of 1,000 USD

Listed, not flagged.

| pool | date | our USD | external USD | abs diff USD | rel diff |
|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-09-06 | 5,085 | 4,759 | 326 | +6.85% |
| wstETH/USDC 0.3% | 2026-08-31 | 123 | 132 | -9 | -6.75% |
| wstETH/USDC 0.05% | 2026-09-12 | 13,973 | 14,717 | -743 | -5.05% |
| wstETH/USDC 0.05% | 2026-09-04 | 3,480 | 3,393 | 87 | +2.55% |
| wstETH/USDC 0.05% | 2026-08-25 | 12,492 | 12,805 | -313 | -2.44% |
| wstETH/USDC 0.05% | 2026-08-21 | 10,937 | 10,712 | 225 | +2.10% |
| wstETH/USDC 0.05% | 2026-08-24 | 2,455 | 2,406 | 49 | +2.04% |
| wstETH/USDC 0.3% | 2026-09-12 | 3,371 | 3,433 | -62 | -1.81% |
| wstETH/USDC 0.05% | 2026-08-31 | 8,117 | 7,981 | 136 | +1.71% |
| wstETH/USDC 0.05% | 2026-08-26 | 3,345 | 3,293 | 53 | +1.60% |
| wstETH/USDC 0.05% | 2026-08-29 | 1,367 | 1,349 | 18 | +1.34% |
| wstETH/USDC 0.05% | 2026-08-30 | 7,436 | 7,359 | 77 | +1.05% |

## B: pool-days excluded from the comparison

Present on both sides, shown with both values, and not compared.

| pool | date | our USD | external USD | abs diff USD | rel diff | why |
|---|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-08-20 | 21 | 22 | -2 | -7.60% | partial on our side (first or last day of our window) |
| wstETH/USDC 0.3% | 2026-09-20 | 1,766 | 1,770 | -4 | -0.24% | partial on our side (first or last day of our window); external candle still open when it was downloaded |
| wstETH/USDC 0.05% | 2026-08-20 | 4,479 | 5,881 | -1,402 | -23.84% | partial on our side (first or last day of our window) |
| wstETH/USDC 0.05% | 2026-09-20 | 752 | 765 | -13 | -1.72% | partial on our side (first or last day of our window); external candle still open when it was downloaded |
| USDC/WETH 0.05% | 2026-08-20 | 92,781,350 | 119,562,198 | -26,780,848 | -22.40% | partial on our side (first or last day of our window) |
| USDC/WETH 0.05% | 2026-09-20 | 26,024,785 | 26,322,590 | -297,804 | -1.13% | partial on our side (first or last day of our window); external candle still open when it was downloaded |
| USDC/WETH 0.01% | 2026-08-20 | 74,441,867 | 114,810,733 | -40,368,866 | -35.16% | partial on our side (first or last day of our window) |
| USDC/WETH 0.01% | 2026-09-20 | 26,675,148 | 27,071,485 | -396,337 | -1.46% | partial on our side (first or last day of our window); external candle still open when it was downloaded |

Every pool-day, with both values, is in `reconciliation.csv`.
