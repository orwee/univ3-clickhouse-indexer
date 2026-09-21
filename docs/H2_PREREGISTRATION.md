# H2: what will be tested out of sample, written before the data exists

Committed on 2026-09-21, before any block earlier than 25,794,751 (2026-08-20 07:10 UTC) was
fetched. The commit that adds this file also adds the code that will be run
(`src/univ3_indexer/h2_check.py`, `sql/reconciliation/18_evidence_revaluation_placebo.sql`);
neither may change between this commit and the run, and the run's report says which commit
it was made with.

## Why

[Finding 7](RECONCILIATION_FINDINGS.md#7-round-trips-inside-one-block-valued-differently--partly-explained)
says that valuing swaps at a going price ("H2") brings 15 of 24 pool-days inside 1% and breaks
6 of 96. The reference window (21 swaps), the displacement threshold (100 ticks) and both
reconciliation thresholds (1%, 1,000 USD) were all chosen while looking at the same 120
pool-days that figure is computed on. An independent review said so, and it is right: that
is a fit, not a test.

## What is frozen

| Thing | Value | Where |
|---|---|---|
| Reference tick | median of the pool's tick over the 21 consecutive swaps centred on the swap | the SQL |
| Displaced | more than 100 ticks from the reference, at either end of the swap | `reconcile.DISPLACEMENT_TICKS` |
| Compared | days complete on our side, external candle closed when downloaded | `make reconcile` defaults |
| Beyond / flagged | beyond 1% / also beyond 1,000 USD | `make reconcile` defaults |
| Hold-out | 2026-08-10 to 2026-08-19, 4 pools: 40 pool-days if the source has all of them | `h2_check.HOLD_OUT` |
| Secondary | 2026-08-20, partial until now, never evaluated under H2; reported apart | `h2_check.SECONDARY` |
| Placebo seeds | 1 to 20 | `h2_check.PLACEBO_SEEDS` |

## What will be reported, whatever it says

1. **Hold-out.** On the hold-out pool-days only: how many are beyond 1% before and after the
   adjustment, how many it fixes (by sign), how many that were inside it breaks, flagged
   before and after, and Pearson's r. For two adjustments: every swap revalued (H2 as first
   tested) and displaced swaps only.
2. **Placebo, in sample.** For each pool-day, revalue the same NUMBER of swaps, but
   non-displaced ones picked by a seeded hash, 20 seeds. If the placebo fixes about as many
   days as revaluing the displaced swaps does, the displaced swaps are not what matters.

## What would weaken H2, decided now

- The hold-out has pool-days beyond 1% and the adjustment fixes clearly fewer of them, in
  proportion, than in sample (in sample: 15 of 24).
- It breaks a clearly larger share of the days that were inside (in sample: 6 of 96).
- r on the hold-out is near zero or negative (in sample: +0.72).
- The placebo's median number of fixed days is close to that of the displaced-only adjustment.

If the hold-out has fewer than 5 pool-days beyond 1%, it cannot say much either way, and the
report will say that instead of claiming support. Ten days were chosen because they are the
days the external source's hourly candles still reach; nothing else was looked at to pick them.

## What cannot be fixed by this

The external source still publishes no methodology, so even a clean result keeps finding 7 at
PARTLY EXPLAINED. And the hold-out is ten days earlier in the same market, not an independent
regime.
