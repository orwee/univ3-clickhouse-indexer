# Reconciliation findings

> Drafted with AI assistance from the measurements in this repo and checked by an independent review pass. Design decisions were proposed with AI assistance, tested by measurement and approved by Roberto.

The figures below are those of the run of 2026-09-20 (898,404 swaps, 4 pools,
2026-08-20 to 2026-09-20; 128 pool-days on both sides, 120 compared), the run on which each
finding was made. Every figure below is in
the snapshot of that run: the [report](evidence/2026-09-20/reconciliation.md), the [evidence](evidence/2026-09-20/reconciliation_evidence.md) and the
[per-day CSV](evidence/2026-09-20/reconciliation.csv). `make reconcile` regenerates all three
under `reports/`.

On 2026-09-21 ten earlier days were added (1,110,676 swaps, 2026-08-09 to 2026-09-20; 163
pool-days compared, 17 flagged) for one purpose: to test finding 7 on days it had not been
fitted on. That run is in its own [snapshot](evidence/2026-09-21/README.md). Everything else
below still quotes the run of 2026-09-20, on which it was found.

Each finding carries one of three states. **EXPLAINED**: the cause was measured and the
difference goes away when it is removed. **PARTLY EXPLAINED**: a cause fits the numbers but
either does not cover all of the difference or rests on something the source does not
publish. **UNEXPLAINED**: measured, located, and not accounted for. The external source
(GeckoTerminal) publishes no methodology ([EXTERNAL_SOURCE.md](EXTERNAL_SOURCE.md)), so
nothing about what it does can be more than PARTLY EXPLAINED.

## Findings

### 1. The pipeline agrees with itself exactly — EXPLAINED

Daily swaps and raw token volume recomputed from `raw_swaps` equal the `swaps_daily`
materialized view on all 128 pool-days, in raw integer units: 0 differences
([report, A](evidence/2026-09-20/reconciliation.md#a-differences-expected-none)). Still 0 on
the 170 pool-days of the current window. Whatever differs below is between this
pipeline and the outside, not inside it.

### 2. Partial days and open candles — EXPLAINED

The backfill starts at 07:10:59 UTC on 2026-08-20, and that day reads -35.16%, -23.84%,
-22.40% and -7.60% against a source that reports the whole day ([evidence §4](evidence/2026-09-20/reconciliation_evidence.md#4-partial-days)). The first
comparison of 2026-09-19 ran at 23:12 UTC of that day, against a candle still open:
USDC/WETH 0.01% read -2.14%; with the day closed on both sides it reads -0.55%
([DECISIONS.md #15](../DECISIONS.md#15-the-external-comparison-only-looks-at-days-that-are-whole-on-both-sides)).
Resolution: only days complete on our side and closed on theirs are compared; the excluded
pool-days are listed with their reason, not dropped (8 in that run, 7 in the current one)
([report, excluded](evidence/2026-09-20/reconciliation.md#b-pool-days-excluded-from-the-comparison)).

### 3. The day boundary is not the cause — EXPLAINED (a negative result)

Recomputing our days with the cut moved from -12 h to +12 h, the distance to the source is
smallest at 0 h in all four pools (0.42%, 0.13%, 0.28%, 0.69%). The test has power where it
matters: one hour either way already gives 1.8% to 13% in three pools. In wstETH/USDC 0.05% a
one-hour shift only moves 0.13% to 0.18-0.23%, so for that pool the test says less
([evidence §1](evidence/2026-09-20/reconciliation_evidence.md#1-day-boundary)). The source's candles start at 00:00:00 UTC, observed, not documented.

### 4. Which leg is valued does not matter in the liquid pools — EXPLAINED

Valuing every swap by its stablecoin leg at 1 USD, or by the other leg at the pool's own
price, differs by -0.0038% (USDC/WETH 0.05%) and +0.0203% (USDC/WETH 0.01%) over the window;
-0.0148% and -0.70% in the two thin pools ([evidence §2](evidence/2026-09-20/reconciliation_evidence.md#2-the-stablecoin-leg-against-the-other-leg-at-the-pools-own-price)). This does **not** measure whether USDC
was worth 1 USD: both valuations end up in USDC. An outside USDC price does exist in the
data and is not used: for USDC/WETH 0.01% the source's daily close is the price of USDC, and
it stayed between 0.9990 and 1.0008, both over the 30 days compared then and over the 41
compared today (`close_usd` in `external_daily_volume`).

### 5. In the liquid pools the 30-day totals agree and the daily noise is centred — EXPLAINED

Over the 30 compared days: USDC/WETH 0.01% +0.10% (1,368,378,340 vs 1,367,066,941 USD) and
USDC/WETH 0.05% +0.24% ([report, per pool](evidence/2026-09-20/reconciliation.md#b-per-pool-compared-days)). Daily differences
in the 0.01% pool: 15 days above, 15 below, median -0.000%. In the 0.05% pool they are less
symmetric: 19 above, 11 below, median +0.03% ([evidence §3](evidence/2026-09-20/reconciliation_evidence.md#3-distribution-of-the-daily-relative-difference-ours---external--external)).

### 6. 2026-08-27: two pools of the same pair off in opposite directions — PARTLY EXPLAINED

USDC/WETH 0.01% -1.65% (-891,843 USD) and USDC/WETH 0.05% +1.35% (+1,112,611 USD); added up,
the pair is at +0.16% ([evidence §6](evidence/2026-09-20/reconciliation_evidence.md#6-pools-of-the-same-pair-added-up)). The evidence does **not** support reading this as volume
attributed to the wrong pool: the two differences sit in different hours. The 0.01% one is at
21h (-892,887 USD), the hour of a 2.39 million USD round trip inside one block, and comes to
+0.50% when swaps are valued at the going price (finding 7). The 0.05% one is a single hour,
00h (+1,105,947 USD), with no displaced swap in the whole day and every neighbouring hour
within 0.1% ([evidence §11](evidence/2026-09-20/reconciliation_evidence.md#11-the-flagged-pool-days-hour-by-hour), [evidence §12](evidence/2026-09-20/reconciliation_evidence.md#12-flagged-days-on-which-the-source-has-more-than-the-chain)). That hour is UNEXPLAINED.

### 7. Round trips inside one block, valued differently — PARTLY EXPLAINED

On the flagged days of USDC/WETH 0.01% the large swaps are same-block round trips consistent
with a sandwich pattern. They come in pairs: same block, same sender
(which is also the recipient), opposite directions, different transactions, one swap of
somebody else between them, the tick leaving and coming back (by thousands of ticks on the
largest ones), the liquidity in range falling by 9 to 1,000 times between the two legs of
those ([evidence §10](evidence/2026-09-20/reconciliation_evidence.md#10-round-trips-inside-one-block)). On 2026-09-11 (+3.14%,
+1,615,421 USD) two such pairs of about 1.59 million USD each moved the tick from 198,254 to
193,939 and from 197,833 to 190,929.

Two readings were tested so that either could fail ([evidence §9](evidence/2026-09-20/reconciliation_evidence.md#9-swaps-executed-away-from-the-pools-own-recent-price)):

- *The source leaves such swaps out* (what was suspected first): **refuted as an explanation
  of these differences**. Whether it filters anything cannot be observed from outside; what
  can be measured is what its consequence would do to the numbers, and it does not fit. Leaving out
  swaps displaced more than 100 ticks brings 0 of 24 pool-days inside 1% and pushes 64 of the
  96 that reconciled in that run outside it; across thresholds from 25 to 1,000 ticks it fixes 0 or 1
  and breaks 19 to 93. Correlation with the daily difference: -0.09.
- *The source counts them but values them at a going price, while this pipeline values every
  swap by its stablecoin leg* (a reading, not a documented behaviour: the source publishes no
  methodology, so what follows is what the numbers would look like IF that were how it works):
  brings **15 of 24** inside 1% (7 of 15 where we are higher,
  8 of 9 where the source is higher) and breaks 6 of 96. Correlation +0.72 overall, +0.91 in
  USDC/WETH 0.01%. In wstETH/USDC 0.05% the three flagged days go from -7.82%, -17.69% and
  +17.84% to -0.05%, +0.13% and +0.03%.

It stays PARTLY EXPLAINED for two reasons: the source does not say how it values a swap, and
2026-09-11 only comes down to +1.35%, 2026-09-03 not at all (+1.59% to +1.62%).

**Out of sample, and against a placebo (2026-09-21).** The reference window, the 100 ticks and
both thresholds had been chosen while looking at the same 120 pool-days the figures above are
computed on. So the protocol was [written down and committed](H2_PREREGISTRATION.md) before ten
earlier days (2026-08-10 to 2026-08-19) were fetched, and then run unchanged
([results](evidence/2026-09-21/h2_out_of_sample.md)). What came out, for and against:

- *For.* On the 39 hold-out pool-days, 10 are beyond 1% and the revaluation brings 6 of them
  inside (5 of 8 where we are higher, 1 of 2 where the source is): 60%, against 62% in sample.
  Flagged pool-days go from 4 to 2. And the placebo is flat: revaluing the same number of
  swaps per pool-day, but non-displaced ones picked at random, brings **0 of 24** in-sample
  days inside 1% in every one of 20 seeds, where revaluing the displaced ones brings 16. It is
  the displaced swaps that carry the effect, not revaluation as such.
- *Against.* By a criterion fixed beforehand, this weakens it: Pearson's r between the daily
  difference and the adjustment is **+0.05** on the hold-out, against +0.72 in sample. It also
  breaks a larger share of the days that reconciled (3 of 29, 10%, against 6 of 96, 6%), and
  it makes two hold-out days worse (USDC/WETH 0.01% 2026-08-11, +1.31% to +1.93%; wstETH/USDC
  0.05% 2026-08-11, -9.01% to +2.50%).
- *What the hold-out adds that H2 does not touch.* USDC/WETH 0.05% on 2026-08-19: +7,766,114
  USD (+2.63%), by far the largest single difference in the project (the next is +1,615,421), 82% of it in
  one hour (15h), and unchanged by the revaluation (+2.65%). With 2026-08-27 and 2026-08-29 in
  the same pool, that is three days where the source has less than the chain in a pool that
  has almost no displaced swaps: a second mechanism that this project has not identified.
  2026-08-20, never evaluated before because it was a partial day, goes the same way (+1.07%,
  no displaced swap, not fixed).

Read together: a difference in how same-block round trips are valued would account for a real
part of the gap in USDC/WETH 0.01% and wstETH/USDC 0.05%; the placebo shows it is not an
artefact of revaluing as such; and it is not the whole story. PARTLY EXPLAINED stands, with less confidence in the correlation than the
in-sample figure suggested.

### 8. 2026-08-29: three pools high on a quiet Saturday — PARTLY EXPLAINED

Three of four pools are above the source (+1.80%, +1.34%, +1.44%) on the third quietest day
of the window, 0.42x the median volume ([evidence §7](evidence/2026-09-20/reconciliation_evidence.md#7-the-same-day-across-the-pools)). It does not hold up as one effect of the
source: USDC/WETH 0.01% comes to +0.83% under the valuation reading of finding 7; the
wstETH/USDC 0.05% difference is 18 USD; USDC/WETH 0.05% stays at +1.44% (+368,871 USD), 91% of
it in two hours, 14h and 15h, with no displaced swap ([evidence §9](evidence/2026-09-20/reconciliation_evidence.md#9-swaps-executed-away-from-the-pools-own-recent-price), [evidence §11](evidence/2026-09-20/reconciliation_evidence.md#11-the-flagged-pool-days-hour-by-hour)). That last one is
UNEXPLAINED.

### 9. Days on which the source reports more than the chain — PARTLY EXPLAINED

2026-09-07 (-2.04%, -833,802 USD) and 2026-09-16 (-1.27%, -611,518 USD) in USDC/WETH 0.01%.
A source that filtered could not produce them. They were expected to stay unexplained; the
evidence says otherwise: valued at the going price they read +0.02% and -0.02%, and 86% and
85% of each difference sits in one hour, the hour of the largest round trip of the day
(08:58:35, 1.84 million USD, tick 198,110 to 206,583; 02:33:47, 1.26 million USD, tick 198,475
to 211,745) ([evidence §12](evidence/2026-09-20/reconciliation_evidence.md#12-flagged-days-on-which-the-source-has-more-than-the-chain), [evidence §10](evidence/2026-09-20/reconciliation_evidence.md#10-round-trips-inside-one-block)). The same holds for the three other flagged days on which the
source is higher. PARTLY and not fully EXPLAINED because the source's method is unpublished.
Next step: a second, independent external source, preferably one that documents how it
values a swap.

### 10. In thin pools a percentage alone does not discriminate — EXPLAINED

wstETH/USDC 0.3% had 625 swaps in that window (673 over the 43 days loaded today); on
2026-09-19 one swap of 617.28 USD is 44% of its day. Of the 24 compared pool-days beyond 1%,
12 differ by less than 1,000 USD, 2,098 USD in total, all in the two wstETH pools (today: 35
beyond 1%, 18 of them below 1,000 USD, 3,682 USD in total, same two pools)
([report, below the absolute threshold](evidence/2026-09-20/reconciliation.md#b-beyond-1-but-below-the-absolute-threshold-of-1000-usd)).
Resolution: a pool-day is flagged beyond 1% **and** beyond 1,000 USD; the others are listed
apart ([DECISIONS.md #16](../DECISIONS.md#16-a-pool-day-is-flagged-beyond-1-and-beyond-1000-usd)).

## What is still open

| Pool-day | Difference | What is known |
|---|---|---|
| USDC/WETH 0.05%, 2026-08-27 | +1.35%, +1,112,611 USD | One hour (00h, +1,105,947 USD); no displaced swap; UNEXPLAINED |
| USDC/WETH 0.05%, 2026-08-29 | +1.44%, +368,871 USD | Two hours (14h, 15h); no displaced swap; UNEXPLAINED |
| USDC/WETH 0.01%, 2026-09-03 | +1.59%, +710,478 USD | One hour (17h, +631,096 USD); unchanged by the valuation reading; UNEXPLAINED |
| USDC/WETH 0.01%, 2026-09-11 | +3.14%, +1,615,421 USD | Comes to +1.35% under the valuation reading; the rest UNEXPLAINED |
| USDC/WETH 0.05%, 2026-08-19 (hold-out) | +2.63%, +7,766,114 USD | 82% in one hour (15h); 7 displaced swaps; unchanged by revaluation; UNEXPLAINED |
| USDC/WETH 0.05%, 2026-08-20 (hold-out, secondary) | +1.07%, +1,273,956 USD | No displaced swap; UNEXPLAINED |
| USDC/WETH 0.01%, 2026-08-11 (hold-out) | +1.31%, +396,150 USD | Made worse by revaluation (+1.93%); UNEXPLAINED |
| wstETH/USDC 0.05%, 2026-08-17 (hold-out) | +121.53%, +812 USD | Below the absolute threshold; unchanged by revaluation; UNEXPLAINED |
