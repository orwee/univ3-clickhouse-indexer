# The daily materialized view: procedure and what was observed

`swaps_daily` gives swaps and raw token volume per pool and UTC day, kept up to
date by a materialized view on `raw_swaps`. This page records how it was put in
place on a table that already held data, and what ClickHouse actually did at
each step. Everything here was run against the real `onchain` database on
2026-09-20; the same behaviour is pinned by `tests/test_mv.py` in a throw-away
database.

## The one thing to know

**A ClickHouse materialized view is an insert trigger, not a stored query.** It
runs its `SELECT` over each block of rows being inserted into the source table
and writes the result to a target table. It never reads the source table. So:

- rows that were in the table before the view existed are **not** in the target;
- `TRUNCATE`, `ALTER … DELETE` and `DROP PARTITION` on the source are **invisible**
  to it: the target keeps counting rows that are gone;
- inserting the same rows again counts them again.

## The objects (`sql/mv/`)

| File | Object | Notes |
|---|---|---|
| `001_swaps_daily_agg.sql` | `swaps_daily_agg` | `AggregatingMergeTree`, `ORDER BY (pool_address, block_date)`. `swaps` is `SimpleAggregateFunction(sum, UInt64)`; the two volume columns are `SimpleAggregateFunction(sum, UInt256)`, in raw units |
| `002_swaps_daily_mv.sql` | `swaps_daily_mv` | `CREATE MATERIALIZED VIEW … TO swaps_daily_agg`. `TO` is explicit so the target is an ordinary table that can be truncated, backfilled and inspected, and outlives the view |
| `003_swaps_daily_view.sql` | `swaps_daily` | What to read. Re-aggregates with `GROUP BY` + `sum()` |
| `010_backfill.sql` | | One-off `INSERT … SELECT` with a block cut-off |
| `020_compare.sql` | | `swaps_daily` against a direct `GROUP BY`; returns the differing pool-days |

**Why UInt256 for the sums.** One `|amount|` is at most 2^255. The largest real
one so far is 1,136 WETH, about 2^70, and the busiest pool-day has about 30,000
swaps (2^15), so a real daily sum is around 2^85. UInt128 would hold the data;
UInt256 is the width that needs no argument, because a sum of token amounts is
bounded by supply times turnover and not by any power of two I would want to
defend. `abs(Int256)` is already `UInt256` in ClickHouse, and so is its `sum`.

**Why the read view has a `GROUP BY`.** Every insert into `raw_swaps` adds new
rows to the target, one per (pool, day) present in that insert block. The same
(pool, day) is stored several times until a background merge collapses it, and
merges are eventual and never guaranteed. A day that straddles the backfill
cut-off has one row from the backfill and others from the trigger. Summing at
read time is right in every one of those states.

## Procedure, and what happened

`make mv-setup` does steps 1 to 3. There was no ingestion writing to the table,
which is what makes this simple: with a live writer the cut-off has to be chosen
with care (see "With a live writer" below).

**1. Create target, view and read view.**

**2. Look at the target before doing anything else.**

```
created. raw rows: 863587 | target rows right after creation: 0
```

863,587 rows in the source, **zero** in the target. The view saw none of them.

**3. Backfill the history, once**, up to the highest block present:

```
backfilled. target rows: 124
swaps_daily: 124 pool-days; differing from a direct GROUP BY: 0
```

124 pool-days (4 pools × 31 days), identical to a direct `GROUP BY` over
`raw_swaps` in swaps, `sum(|amount0|)` and `sum(|amount1|)`.

**4. The trigger, with real data.** The landing zone was extended with a new
backfill plan from block 26,010,751 (the block after the first plan ended) to
the chain tip minus 64, block 26,014,668: 3,918 blocks, 392 calls, **17,600
swaps**. Then `make load`, incremental:

| | raw_swaps | sum(swaps) in swaps_daily | rows in swaps_daily_agg |
|---|---|---|---|
| before | 863,587 | 863,587 | 124 |
| after | 881,187 | **881,187** | 127 |

```
load (incremental): files_loaded=4, files_skipped=216, rows_inserted=17600, inserts=1
"materialized_view_mismatches": 0
```

The view gained exactly the 17,600 rows that were inserted, and nobody ran a
backfill: they arrived through the trigger. The target gained 3 rows, not
17,600: one per pool that traded in that insert (wstETH/USDC 0.3% did not).
All of them fall on 2026-09-19, which now has **7 rows in the target for 4
pools**: four from the backfill and three from the trigger. That is the case the
read view exists for; `make mv-check` still reports 0 differences.

**5. A full reload with the view attached.** `make load-full` truncates
`raw_swaps` and reloads it. Done naively that counts everything twice, because
the trigger does not see the truncate and then sees every reinserted row. The
loader now truncates the target too and lets the trigger refill it:

```
load (full): files_loaded=220, rows_inserted=881187, inserts=9
"materialized_view_mismatches": 0
```

After it: 881,187 swaps in the view, 136 rows in the target for 124 pool-days (9
insert blocks, partly merged already), 0 differences.

## Things that go wrong, each with a test

| Mistake | What happens | Test |
|---|---|---|
| Create the view and assume it is populated | The target is empty; every total is 0 | `test_a_…leaves_its_target_empty` |
| Backfill with the cut-off one block too low | The rows of that block are in nobody's hands | `test_c_a_cut_off_by_one_too_low_is_detected` |
| Run the backfill twice | The whole history is counted twice | `test_d_running_the_backfill_twice…` |
| Read `swaps_daily_agg` directly | Several rows per (pool, day) until a merge | `test_the_target_holds_several_rows_per_key…` |
| Truncate and reload the source | Double count | `test_truncate_and_reload_without_care_double_counts` |
| Delete rows from the source and reinsert them | Those days are too high | `test_an_incremental_repair_with_the_view_attached_stays_exact` |

The way out of all of them is the same: `make mv-check` to find out, and
`PYTHONPATH=src uv run python -m univ3_indexer.mv --rebuild` (truncate the target, aggregate the source
again) to repair, with ingestion stopped. `make load`, `make load-full` and
`make load-verify` now compare `swaps_daily` with a direct `GROUP BY` and exit
non-zero when they differ.

## With a live writer

**A sketch, not something this repo does or tests.** Everything above was done with
ingestion stopped, and the tests of the cut-off (`test_c_…`) are sequential, with no
concurrent writer.

The view only handles inserts that start after it exists, so the usual recipe is: create
the view first; note a cut-off; backfill `WHERE block_number <= cut-off`. For "rows above
the cut-off belong to the trigger and rows at or below it to the backfill" to be TRUE,
two things must hold that nothing in `002_swaps_daily_mv.sql` enforces (the trigger has
no block predicate): inserts arrive in increasing block order, and the cut-off is the
last block inserted before the view existed. This loader breaks the first one whenever it
repairs an old file. With a live writer the robust version puts the predicate in the view
itself (`WHERE block_number > X`, with X still in the future), waits for ingestion to
pass X, and then backfills `<= X`; or it backfills into a second target and swaps the
tables.
