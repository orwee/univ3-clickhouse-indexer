# Reconciliation report

Database `onchain`, generated 2026-09-20 22:52 UTC by `make reconcile`. Compared: only days complete on our side whose external candle was closed when downloaded. Flagged: beyond **1%** (`--threshold`) AND beyond **1,000 USD** (`--abs-threshold`).

## Summary

- **A, internal** (recomputation from `raw_swaps` vs `swaps_daily`, raw units): **exact, 0 differences**.
- **B, external** (our `volume_usd` vs geckoterminal): 170 pool-days present on both sides, 163 compared, **17 beyond both thresholds**, 18 beyond the relative threshold only, 7 excluded (listed below with the reason), 1 present on one side only.
- The exit code reflects A only. What the differences in B mean is not decided here.

### B per pool, compared days

| Pool | Days | Ours USD | External USD | Total diff | Median daily diff | Largest daily diff (absolute) | Days beyond the relative threshold | Days beyond both |
|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 41 | 1,836,249,053 | 1,832,374,224 | +0.21% | +0.10% | 3.14% | 10 | 10 |
| wstETH/USDC 0.3% | 40 | 57,439 | 57,670 | -0.40% | -0.06% | 6.75% | 3 | 0 |
| wstETH/USDC 0.05% | 41 | 26,375,822 | 26,404,580 | -0.11% | -0.00% | 121.53% | 18 | 3 |
| USDC/WETH 0.05% | 41 | 3,354,537,021 | 3,337,787,276 | +0.50% | +0.08% | 2.63% | 4 | 4 |

### B per pool, every day present on both sides, for reference

| Pool | Days | Ours USD | External USD | Total diff | Median daily diff | Largest daily diff (absolute) | Days beyond the relative threshold | Days beyond both |
|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 43 | 1,867,819,631 | 1,904,277,933 | -1.91% | +0.06% | 66.74% | 12 |  |
| wstETH/USDC 0.3% | 41 | 59,205 | 62,025 | -4.55% | -0.09% | 59.44% | 4 |  |
| wstETH/USDC 0.05% | 43 | 26,376,642 | 26,406,310 | -0.11% | -0.00% | 121.53% | 20 |  |
| USDC/WETH 0.05% | 43 | 3,393,719,460 | 3,425,824,189 | -0.94% | +0.08% | 58.81% | 6 |  |

## A: differences (expected: none)

None.

## B: days present on one side only

| pool | date | present | our USD | external USD |
|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-08-09 | only_external | 0 | 1 |

## B: pool-days beyond 1% and 1,000 USD

| pool | date | our USD | external USD | abs diff USD | rel diff |
|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-09-19 | 9,349 | 7,934 | 1,415 | +17.84% |
| wstETH/USDC 0.05% | 2026-09-03 | 11,069 | 13,448 | -2,379 | -17.69% |
| wstETH/USDC 0.05% | 2026-08-23 | 18,880 | 20,482 | -1,602 | -7.82% |
| USDC/WETH 0.01% | 2026-09-11 | 53,003,066 | 51,387,646 | 1,615,421 | +3.14% |
| USDC/WETH 0.01% | 2026-08-14 | 39,081,720 | 38,011,684 | 1,070,036 | +2.82% |
| USDC/WETH 0.05% | 2026-08-19 | 302,904,833 | 295,138,719 | 7,766,114 | +2.63% |
| USDC/WETH 0.01% | 2026-09-07 | 39,974,422 | 40,808,224 | -833,802 | -2.04% |
| USDC/WETH 0.01% | 2026-08-30 | 34,771,776 | 34,080,798 | 690,977 | +2.03% |
| USDC/WETH 0.01% | 2026-08-29 | 24,094,473 | 23,668,642 | 425,831 | +1.80% |
| USDC/WETH 0.01% | 2026-08-27 | 53,058,152 | 53,949,995 | -891,843 | -1.65% |
| USDC/WETH 0.01% | 2026-09-03 | 45,428,762 | 44,718,283 | 710,478 | +1.59% |
| USDC/WETH 0.05% | 2026-08-29 | 25,955,000 | 25,586,129 | 368,871 | +1.44% |
| USDC/WETH 0.05% | 2026-08-27 | 83,227,142 | 82,114,531 | 1,112,611 | +1.35% |
| USDC/WETH 0.01% | 2026-08-11 | 30,734,327 | 30,338,177 | 396,150 | +1.31% |
| USDC/WETH 0.01% | 2026-09-16 | 47,554,508 | 48,166,026 | -611,518 | -1.27% |
| USDC/WETH 0.05% | 2026-08-20 | 120,836,153 | 119,562,198 | 1,273,956 | +1.07% |
| USDC/WETH 0.01% | 2026-08-15 | 22,037,422 | 21,816,339 | 221,082 | +1.01% |

## B: beyond 1%, but below the absolute threshold of 1,000 USD

Listed, not flagged.

| pool | date | our USD | external USD | abs diff USD | rel diff |
|---|---|---|---|---|---|
| wstETH/USDC 0.05% | 2026-08-17 | 1,480 | 668 | 812 | +121.53% |
| wstETH/USDC 0.05% | 2026-08-10 | 4,182 | 3,815 | 368 | +9.64% |
| wstETH/USDC 0.05% | 2026-08-11 | 3,756 | 4,129 | -372 | -9.01% |
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
| wstETH/USDC 0.05% | 2026-08-12 | 792 | 780 | 12 | +1.57% |
| wstETH/USDC 0.05% | 2026-08-14 | 1,318 | 1,336 | -18 | -1.34% |
| wstETH/USDC 0.05% | 2026-08-29 | 1,367 | 1,349 | 18 | +1.34% |
| wstETH/USDC 0.3% | 2026-08-19 | 145 | 143 | 2 | +1.21% |
| wstETH/USDC 0.05% | 2026-08-30 | 7,436 | 7,359 | 77 | +1.05% |

## B: pool-days excluded from the comparison

Present on both sides, shown with both values, and not compared.

| pool | date | our USD | external USD | abs diff USD | rel diff | why |
|---|---|---|---|---|---|---|
| wstETH/USDC 0.3% | 2026-09-20 | 1,766 | 4,354 | -2,588 | -59.44% | partial on our side (first or last day of our window); external candle still open when it was downloaded |
| wstETH/USDC 0.05% | 2026-08-09 | 67 | 474 | -407 | -85.77% | partial on our side (first or last day of our window) |
| wstETH/USDC 0.05% | 2026-09-20 | 752 | 1,256 | -504 | -40.10% | partial on our side (first or last day of our window); external candle still open when it was downloaded |
| USDC/WETH 0.05% | 2026-08-09 | 13,157,653 | 31,946,693 | -18,789,040 | -58.81% | partial on our side (first or last day of our window) |
| USDC/WETH 0.05% | 2026-09-20 | 26,024,785 | 56,090,221 | -30,065,435 | -53.60% | partial on our side (first or last day of our window); external candle still open when it was downloaded |
| USDC/WETH 0.01% | 2026-08-09 | 4,895,431 | 14,720,866 | -9,825,436 | -66.74% | partial on our side (first or last day of our window) |
| USDC/WETH 0.01% | 2026-09-20 | 26,675,148 | 57,182,843 | -30,507,695 | -53.35% | partial on our side (first or last day of our window); external candle still open when it was downloaded |

Every pool-day, with both values, is in `reconciliation.csv`.
