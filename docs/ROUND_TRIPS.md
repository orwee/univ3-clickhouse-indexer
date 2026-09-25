# Round trips in one block

**The question.** A pool's reported volume counts every swap. How much of it is a swap that the
same sender undid in the same block, so that almost nothing changed hands by the end of it?

Every figure below is from the run of 2026-09-25 (1,240,618 swaps, 4 pools, 2026-08-09 to
2026-09-25, every pool-day of the window, the partial first and last days included), in the
committed report [evidence/2026-09-25/analysis.md](evidence/2026-09-25/analysis.md). USD is
the stablecoin leg at 1 USD, as everywhere in this repository.

## The definition

The one the reconciliation already used for finding 7
([sql/reconciliation/16_evidence_round_trips.sql](../sql/reconciliation/16_evidence_round_trips.sql)),
unchanged, applied to the whole dataset instead of one pool-day:

- two swaps of the **same pool**, in the **same block**, with the **same `sender`**;
- the second one **later in the block** (a higher `log_index`);
- moving the **non-stable leg in the opposite direction**;
- and **undoing 90% to 110%** of it: `|first + second| <= 0.1 * |first|` on the raw amount of
  that leg.

`sender` in a Swap log is the contract that called the pool, not the account that signed the
transaction; nothing here says who is behind it, or why. A swap can be a leg of more than one
pair (a sender with three swaps in a block); legs are counted once.

## Where it lives

| What | File |
|---|---|
| Every leg, one row per swap | [dbt/models/marts/fct_round_trip_legs.sql](../dbt/models/marts/fct_round_trip_legs.sql) |
| Per pool and day: pairs, legs, their USD, the volume left without them | [dbt/models/marts/fct_pool_daily_round_trips.sql](../dbt/models/marts/fct_pool_daily_round_trips.sql) |
| Tests that can fail: a recomputation of the legs from the raw table, ranges and coverage, keys | [dbt/tests/assert_round_trip_legs_match_their_definition.sql](../dbt/tests/assert_round_trip_legs_match_their_definition.sql), [dbt/tests/assert_round_trips_are_a_part_of_the_pool_day.sql](../dbt/tests/assert_round_trips_are_a_part_of_the_pool_day.sql) |
| Three scenarios of `make dbt-prove` that break the data so each new test fails | [scripts/prove_dbt_tests_can_fail.py](../scripts/prove_dbt_tests_can_fail.py) |
| The analysis: per pool, by hour, by sender, by tolerance, by size, what sits between the legs | [sql/analysis/](../sql/analysis/10_round_trips_by_pool.sql), 10 to 15, run by `make analysis` |

The recomputation in `13_round_trips_tolerance.sql` works from the raw table, not from the
marts, and `make analysis` stops if, at the 10% of the definition, the two disagree on pairs,
legs or USD.

## What it shows

| Pool | Pairs | Swaps in them | Share of the pool's swaps | Share of the pool's USD | Median day |
|---|---|---|---|---|---|
| USDC/WETH 0.01% | 3,147 | 5,759 | 0.62% | **24.4%** | 24.8% |
| USDC/WETH 0.05% | 2,065 | 3,616 | 1.18% | 0.96% | 0.06% |
| wstETH/USDC 0.05% | 81 | 162 | 2.66% | 0.40% | 16.2% |
| wstETH/USDC 0.3% | 6 | 12 | 1.29% | 5.75% | 0.0% |
| **All four** | **5,299** | **9,549** | **0.77%** | **9.80%** | |

- **9.8% of all USD volume** (587 M of 5,992 M USD) is round-trip legs, but only 0.77% of the
  swaps. That share counts both legs, as a reported volume does. The second legs alone, the
  part that comes back, are 292 M USD: **4.9%** of all USD volume.
- **Most legs are small; the money is in the large ones.** 5,509 of the 9,549 legs are under
  1,000 USD and hold 0.16% of the round-trip USD; the 1,446 legs of 100,000 USD or more hold
  87.4% of it.
- **It is concentrated in one pool and a few contracts.** In USDC/WETH 0.01% it is a quarter of
  the money on a median day; in USDC/WETH 0.05%, the larger pool by
  volume, it is under 1%. 124 contracts called the pool for these pairs; the largest one
  accounts for 25.3% of the round-trip USD, the largest three for 69.8%, the largest ten for
  97.5%. How many accounts are behind those contracts is not known from a Swap log.
- **By hour of the day** (UTC) the share of each hour's USD goes from 5.8% (23h) to 16.9%
  (05h), around a median of 9.25%: no hour is free of it.
- **The shape.** 95.0% of the round-trip USD sits in pairs whose two legs are in different
  transactions with a swap of somebody else between them in the same pool (2,228 of the 5,299
  pairs). 4.5% is two transactions with nothing between, and 0.5% is inside one transaction
  (1,272 pairs, mostly small). The first shape is **consistent with a sandwich pattern**: a
  swap before someone else's and its reversal after it. Nothing here observes intent, and the
  data cannot tell a sandwich from other strategies that take the same shape.

## How much this depends on the tolerance

The 10% of the definition is a choice. The same recomputation with the tolerance open
([13_round_trips_tolerance.sql](../sql/analysis/13_round_trips_tolerance.sql)):

| Tolerance | Pairs | Share of all USD |
|---|---|---|
| 0% (exact reversal) | 113 | 0.12% |
| 1% | 1,841 | 7.30% |
| 5% | 3,126 | 9.14% |
| **10% (the definition)** | **5,299** | **9.80%** |
| 20% | 7,676 | 10.21% |
| 50% | 15,089 | 10.67% |

The count of pairs depends heavily on it; the USD share much less, because most of the USD is
in pairs that reverse to within 1% (7.3 of the 9.8 points).

## Limitations

- **One pool at a time.** A pair whose legs are in two different pools, or in two different
  protocols, is not seen. Neither is a reversal split over several swaps.
- **`sender` is a contract.** A router that carries many users can pair two users' trades, and
  such pairs are in the counts.
- **Not one-to-one.** A leg can belong to two pairs. The USD counts each leg once; the number
  of pairs is the number of qualifying pairs, not a matching.
- **The dbt test that recomputes the legs repeats the definition.** It catches a stale or a
  broken mart, not a definition that is wrong; the tolerance table is the check on the
  definition's choice.
- **Stablecoin at 1 USD**, like the rest of the repository.

## Why it matters

A volume figure that counts a swap and its reversal inside one block reports activity that
left little or no position behind. Anything computed from volume inherits it: estimated fees,
a pool's share of its pair, a ranking of pools. Here it is a quarter of the reported volume of
one pool and under 1% of its larger sibling, so the two fee tiers of the same pair would be
compared on different footings unless it is netted out. It is also the pattern that finding 7
of the reconciliation turned on, where part of the gap with the external source is consistent
with the source valuing these swaps differently, a reading that stays partly explained
([RECONCILIATION_FINDINGS.md](RECONCILIATION_FINDINGS.md)).
