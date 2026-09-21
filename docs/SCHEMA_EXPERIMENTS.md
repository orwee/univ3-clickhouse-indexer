# Schema experiments on real data (not concluded)

> **The decisions that came out of these measurements** are in
> [DECISIONS.md](../DECISIONS.md), entries
> [#10](../DECISIONS.md#10-engine-mergetree-with-deduplication-left-to-the-load) (engine),
> [#11](../DECISIONS.md#11-order-by-pool_address-block_timestamp-block_number-log_index-primary-key-on-the-first-two)
> (`ORDER BY`), [#12](../DECISIONS.md#12-partition-by-month-for-management-and-not-for-speed)
> (partitioning) and
> [#13](../DECISIONS.md#13-types-lossless-integers-and-hashes-and-addresses-in-binary)
> (types); the real table is [sql/001_raw_swaps.sql](../sql/001_raw_swaps.sql). This document
> measures and does not choose; it was measured on 463,447 and 863,587 rows (today the table holds 898,404).

Measurements for Roberto to decide the schema. **This document chooses nothing.**
It complements `SCHEMA_OPTIONS.md` (which reasons) with measured numbers. The decisions
go to `DECISIONS.md`, written by him.

## Update 2026-09-21: `FINAL` measured with the REAL key

What this document measured about `FINAL` (further down) used a Replacing table sorted by
`(pool, block_number, log_index)`, a key **with no time in it**: with it a one-day query
could not prune either with `FINAL` or without it. An independent review pointed it out. Here
it is repeated with the `ORDER BY` of the real table, `(pool_address, block_timestamp, block_number, log_index)`,
which is also unique per log and therefore serves as the deduplication key as well.

`scripts/final_experiment.py`, raw results in
`docs/experiments/final-real-key-2026-09-21.json`. Two tables with the same columns and the
same key, MergeTree and ReplacingMergeTree, filled from the real table (898,404 rows) with
the same 200 inserts, merges stopped, and one batch in ten delivered twice
(90,081 repeated rows: 988,485 rows stored). It is measured unmerged (221 parts) and after
`OPTIMIZE FINAL` (2 parts, one per monthly partition). A plain MergeTree rejects `FINAL`
(`ILLEGAL_FINAL`), so there the measurement is only without it.

**Replacing, 221 unmerged parts**

| Query | Without `FINAL`: rows · bytes · ms · memory | With `FINAL` | Answer without / with |
|---|---|---|---|
| Daily volume, all pools | 988,485 · 36.6 MB · 45 ms · 9 MB | 988,485 · 48.5 MB · **116 ms (2.6x)** · **48 MB** | total 10.0% too high / correct |
| One day of the big pool | 39,756 · 1.47 MB · 6 ms | **39,756** · 1.95 MB · 10 ms | 28,179 swaps (**+17.6%**) / 23,961 |
| One day of the small pool | 39,756 · 1.47 MB · 7 ms | 39,756 · 1.95 MB · 7 ms | 19 / 14 |
| One day, all pools | 39,756 · 1.43 MB · 5 ms | 39,756 · 1.95 MB · 7 ms | 36,562 / 31,013 |

**Replacing, after merging (2 parts; the duplicates no longer exist: 898,404 rows, not one lost)**

| Query | Without `FINAL` | With `FINAL` | With `FINAL` and `do_not_merge_across_partitions_select_final = 1` |
|---|---|---|---|
| Daily volume, all pools | 898,404 · 33.2 MB · 39 ms | 898,404 · 33.2 MB · 51 ms (1.3x) | 898,404 · 33.2 MB · **39 ms** |
| One day of the big pool | 24,576 · 0.91 MB · 4 ms | 24,576 · 0.91 MB · 4 ms | same |
| One day of the small pool | 8,192 · 0.04 MB · 3 ms | 8,192 · 0.30 MB · 4 ms | same as with `FINAL` |
| One day, all pools | 57,344 · 2.06 MB · 5 ms | 57,344 · 2.06 MB · 5 ms | same |

**MergeTree with the same duplicates:** 988,485 rows unmerged and **988,485 after merging**.
Nothing ever removes them; the day of the big pool still says 28,179 swaps.

The condition cache, off or on, changed no row or byte figure: all these queries prune by
the key and leave it nothing to remember.

What these numbers say, without deciding anything:

- **With the real key, `FINAL` does not remove the pruning.** It reads exactly the same rows
  as the query without `FINAL`, merged or unmerged. It reads more bytes when unmerged (+32%:
  it needs the key columns) and practically the same once merged.
- **The cost of `FINAL` is in the query that reads everything, and only while there are many
  parts:** 2.6x in time and 5x in memory. Merged, 1.3x, and with
  `do_not_merge_across_partitions_select_final = 1`, nothing measurable. The filtered queries
  pay between 0 and 4 ms.
- **The real key is unique per log:** the Replacing table lost no row (the 64.4% lost
  further down is from a NON-unique key, a misuse, not from this one).
- **Without `FINAL`, the unmerged Replacing table gives the same wrong figure as the MergeTree.** The
  difference is that in the Replacing table the error disappears on merging or on saying `FINAL`, and in the
  MergeTree it never disappears: there the whole defence is that the load does not duplicate.
- A fact that does not depend on the engine: the materialized view is an INSERT trigger, so
  a row delivered twice **goes twice into `swaps_daily_agg`** even if the source table
  were Replacing. With the view in place, the load has to be idempotent anyway.

## Update: the full 30 days (863,587 swaps)

Repeated on 2026-09-19 with the backfill finished: 216 files, blocks 25,794,751 to
26,010,750, **863,587 swaps**. Same script, same version, condition cache
off and on. Raw result in `docs/experiments/schema-2026-09-19-30d.json`.
The rest of the document describes the first pass, with 52% of the data; it is left
as it was because the method and the explanations are the same. **No observation
changes sign; the differences grow with the data.**

Split: USDC/WETH 0.01% 630,611 (73.0%) · USDC/WETH 0.05% 227,678 (26.4%) ·
wstETH/USDC 0.05% 4,688 (0.5%) · wstETH/USDC 0.3% 610 (0.07%).

| Observation | First pass (463,447) | 30 days (863,587) |
|---|---|---|
| Replacing with a non-unique key: rows lost | 65.7% | **64.4%** (307,720 left) |
| Replacing without `FINAL` or merge: total too high | 11.2% | **10.5%** (954,496 instead of 863,587) |
| `FINAL` unmerged, main query | 69 ms against 23 (3.0x) | **114 ms against 41 (2.8x)**, 45 MB of memory against 9 |
| `FINAL` unmerged, one day of one pool | whole table, **the same as without `FINAL`** | whole table with and without `FINAL` (954,496 rows); 116 ms against 21. The key tested here has no time in it, so nothing was being pruned that `FINAL` could have cost |
| One day of the big pool, `(pool, timestamp)` | 32,768 rows · 4/57 granules | **32,768 rows · 4/106 granules** |
| One day of the big pool, `(pool, block_number, log_index)` | 348,759 rows · 43/57 | **634,211 rows · 78/106** (19 times more) |
| …the same one, with the condition cache on | 49,152 | 49,152 |
| One day of the small pool, keys with `pool` first | 8,192 rows · 1 granule | 8,192 rows · 1 granule |
| One day of the small pool, `(timestamp, pool)` | 49,152 rows | 49,152 rows |
| One day, all pools: `(pool, ts)` / `(ts, pool)` / `(pool, block, log)` | 65,536 / 49,152 / 463,447 | 65,536 / 49,152 / **863,587** |
| Monthly partitioning against none: rows read | identical | **identical** (prunes 1 of 2 parts; the index already discarded them) |
| Main query, any key | whole table, 19 to 23 ms | whole table, **34 to 42 ms** |
| `tx_hash` in hex: share of the disk | 52.9% | **53.0%** (55.8 of 105.2 MB) |
| Table size with hashes as text | 56.9 MB · 123 B/row | **105.2 MB · 122 B/row** |

What is read from the table, without judging it: what a query well served by the
key reads **does not grow** with the table (32,768 rows with twice the data), and what a badly
served one reads grows in proportion (from 348,759 to 634,211).

### The real table, with the types decided

After these experiments the schema was decided (DECISIONS.md #10 to #14) and
`onchain.raw_swaps` was loaded. Measured on that table, with `tx_hash`, `sender` and
`recipient` in binary (`FixedString`):

| | Hashes as text (candidate) | Hashes in binary (real table) |
|---|---|---|
| Compressed | 105.2 MB | **73.2 MB (−30%)** |
| Bytes per row | 122 | **84.8** |
| `tx_hash` | 55.8 MB · 53.0% | **26.2 MB · 35.7%** |
| `sender` + `recipient` | 12.5 MB | 8.0 MB |
| Partitions / parts after the load | | 2 partitions, 5 parts (9 inserts) |

`tx_hash` is still the largest column even in binary: it is random and does not compress
(ratio 1.0). The three 256-bit integers add up to 38.6% of the real table.

---

## What was measured and with what

- **Data:** the first 113 files of the landing zone of the real backfill,
  blocks 25,794,751 to 25,907,750 (20 August to 4 September 2026):
  **463,447 swaps**, 52% of the 30-day window. The backfill was still running.
- **Server:** ClickHouse 26.3.33.24, the repo's container (3 GiB, no swap).
- **Split by pool:** USDC/WETH 0.01% 345,451 (74.5%) · USDC/WETH 0.05% 115,418
  (24.9%) · wstETH/USDC 0.05% 2,456 (0.5%) · wstETH/USDC 0.3% 122 (0.03%).
- **Method:** `scripts/schema_experiments.py`. It creates the `test_schema_exp` database,
  loads the same rows into each candidate table (one `INSERT` per file, as a real
  loader would), measures, and **drops the database when it finishes**. Raw result in
  `docs/experiments/schema-2026-09-19.json`.
- **Where each number comes from:** rows and bytes read, from `system.query_log`;
  granules and parts that survive, from `EXPLAIN indexes = 1`; sizes and parts, from
  `system.parts` and `system.parts_columns`. Times: median of 5 runs.

Columns of all the tables (illustrative, not a proposal of names):
`pool LowCardinality(String)`, `block_number UInt32`, `block_timestamp DateTime('UTC')`,
`log_index UInt32`, `tx_hash / sender / recipient String`, `amount0 / amount1 Int256`,
`sqrt_price_x96 UInt256`, `liquidity UInt128`, `tick Int32`.

### Reproducing

```
PYTHONPATH=src uv run python scripts/schema_experiments.py \
    --landing /var/lib/univ3-indexer/landing > resultados.json
```

Without `--max-files` it uses everything that has landed: when the backfill finishes it is
worth repeating it with the full 30 days. It needs no API keys and no network, only
ClickHouse. It takes ~1 min.

### Two warnings about how to read the numbers

1. **At this size the times tell nothing apart.** Every query takes between
   3 and 25 ms; differences of 1 or 2 ms are noise. What does discriminate is **how many
   rows and bytes are read**, which is what would scale with more data. Read the times as
   "everything has room to spare", not as a ranking.
2. **The query condition cache deceives the measurement.** It happened to me: the first pass
   gave, for one and the same query, 43 of 57 granules according to `EXPLAIN` but only 49,152
   rows read according to `query_log`. The cause is `use_query_condition_cache = 1` (the
   default in this version): ClickHouse remembers, per filter, which granules had no matching
   rows, and from the second run onwards it skips them. That **covers up exactly the
   difference between sorting keys** that is to be measured. That is why the tables
   below give both figures: with the cache off (what the `ORDER BY` prunes on its
   own) and with it on (what real use will see in repeated queries).

## 1. Type round-trip with clickhouse-connect

The real extreme values of a sample were inserted (the first three files,
~14,000 swaps) plus the limits of each type, and they were read in three ways: as a Python value through the driver, as text (`toString`) on
the server, and byte by byte (`hex(reinterpretAsFixedString(amount1))`, 32 bytes in
little-endian reconstructed in Python).

| Value | Bits | Driver exact | Text exact | Bit for bit |
|---|---|---|---|---|
| amount1 real maximum: 635,972,951,593,090,648,054 (≈ 636 WETH) | 70 | yes | yes | yes |
| amount1 real minimum: −633,544,440,917,790,349,267 | 70 | yes | yes | yes |
| amount0 real maximum / minimum (wstETH, ±1.3e17) | 57 | yes | yes | yes |
| sqrt_price_x96 real maximum (1.71e33) | 111 | yes | yes | yes |
| liquidity real maximum (3.3e20) | 69 | yes | yes | yes |
| tick real minimum / maximum: −196,981 / +199,650 | 18 | yes | yes | yes |
| Limits: Int256 min and max, UInt256 max, UInt128 max, Int32 min | 256 | yes | yes | yes |

- **No surprises in the big integers.** `Int256`, `UInt256` and `UInt128` go in and
  come out as a Python `int`, without passing through a float, over the whole range of the type.
- **`JSONEachRow` with the integers as strings works** (`"amount1": "-6335…"` goes into
  an `Int256` column exactly). It is the format of the landing zone, so a
  loader can send the files almost as they are.
- **A minor surprise from the driver:** a `DateTime('UTC')` column comes back as a `datetime`
  **with no time zone** (`tzinfo=None`). The instant is correct, but it is a naive
  `datetime`: comparing it with a time-zone-aware one raises `TypeError` in Python.
- **The figure that has grown:** yesterday the largest seen was 66 bits (50.8 WETH). Going over
  everything landed so far (525,295 swaps, 129 files) the largest `amount1`
  is **1,136 WETH, 70 bits**: `Int64` falls short by a factor of 123. Other
  extremes from that pass: `amount0` 61 bits, `sqrt_price_x96` 111, `liquidity` 69,
  tick from −203,307 to +206,590, `log_index` up to 10,500 (it does not fit in `UInt8`; it does in
  `UInt16`, with little of the usual margin: better `UInt32`). They all fit in the types
  tested, whose full range is verified in the last row of the table.
- **What happens if a Float64 slips in:** `toInt256(toFloat64(amount1))` on the real
  minimum returns −633,544,440,917,790,**294,046**: 55,221 wei are lost. It raises no error.

## 2. Candidate tables

Each comparison changes **one single thing**.

| Table | Engine | ORDER BY | PARTITION BY |
|---|---|---|---|
| `mt_pool_ts` (baseline) | MergeTree | (pool, block_timestamp) | none |
| `mt_ts_pool` | MergeTree | **(block_timestamp, pool)** | none |
| `mt_pool_block_log` | MergeTree | **(pool, block_number, log_index)** | none |
| `rmt_pool_block_log` | **ReplacingMergeTree** | (pool, block_number, log_index) | none |
| `mt_pool_ts_monthly` | MergeTree | (pool, block_timestamp) | **toYYYYMM(block_timestamp)** |

Pairs to compare: ORDER BY → the first three against each other. Engine → `mt_pool_block_log`
against `rmt_pool_block_log`. Partitioning → `mt_pool_ts` against `mt_pool_ts_monthly`.

The queries:

- **Q1, the main one:** daily volume per pool, over the whole table.
- **Q2-big:** one pool and one day (2026-08-21), for USDC/WETH 0.01% (74.5% of the rows).
- **Q2-small:** the same for wstETH/USDC 0.3% (122 rows in total).
- **Q3:** all the pools on that day (filter by date only).

### 2.1 Storage

After `OPTIMIZE ... FINAL` (one part per partition):

| Table | Parts before → after | Compressed | Uncompressed | Primary index in memory | Marks |
|---|---|---|---|---|---|
| mt_pool_ts | 113 → 1 | 56.87 MB | 140.4 MB | 448 B | 58 |
| mt_ts_pool | 113 → 1 | 56.39 MB | 140.4 MB | 232 B | 58 |
| mt_pool_block_log | 113 → 1 | 56.87 MB | 140.4 MB | 448 B | 58 |
| rmt_pool_block_log | 125 → 1 | 56.87 MB | 140.4 MB | 448 B | 58 |
| mt_pool_ts_monthly | 114 → 2 | 56.87 MB | 140.4 MB | 616 B | 60 |

- ~123 bytes per row compressed, ~303 uncompressed. Extrapolated to 30 days (~881,000
  rows): **~108 MB** on disk. The JSONL landing zone takes ~12 times more.
- **The ORDER BY barely changes the size** (less than 1%). The primary index takes
  hundreds of bytes in every case: at this scale it is not a criterion.
- "Before" is one part per `INSERT` because merges were stopped on purpose during the
  load (`SYSTEM STOP MERGES`), so that the figure is deterministic. The monthly table
  has one more because one file crossed from August to September: **an insert that touches
  two partitions creates two parts.**

By column, in `mt_pool_ts`:

| Column | Compressed | % of the total | Ratio |
|---|---|---|---|
| tx_hash | 30.11 MB | **52.9%** | 1.1x |
| sqrt_price_x96 (UInt256) | 7.36 MB | 12.9% | 2.0x |
| amount1 (Int256) | 5.23 MB | 9.2% | 2.8x |
| recipient | 4.11 MB | 7.2% | 5.6x |
| amount0 (Int256) | 3.46 MB | 6.1% | 4.3x |
| sender | 2.73 MB | 4.8% | 8.5x |
| log_index | 1.33 MB | 2.3% | 1.4x |
| tick | 0.88 MB | 1.6% | 2.1x |
| block_timestamp | 0.68 MB | 1.2% | 2.7x |
| block_number | 0.67 MB | 1.2% | 2.8x |
| liquidity (UInt128) | 0.31 MB | 0.5% | 24.1x |
| pool (LowCardinality) | 0.002 MB | 0.0% | 189x |

- **More than half the disk is `tx_hash`**, which being random does not compress (1.1x).
  Storing it as binary `FixedString(32)` would leave it around half: it is, by far,
  the type decision that moves the most bytes.
- **The three 256-bit fields together are 28%.** `Int256` costs 32 bytes uncompressed
  per value, but compresses 2.8 to 4.3x: `amount0` and `amount1` end up at ~7 and
  ~11 bytes per row. `sqrt_price_x96` compresses worse (2.0x) because it changes on every swap.
- `sender` compresses 8.5x while being a `String` (a few repeated routers); `recipient`, 5.6x.
- `pool` as `LowCardinality` takes 2.4 KB in total.

### 2.2 What each ORDER BY reads

Rows read with the condition cache **off** (in brackets, on), and
granules that survive the primary index out of 57:

| Query | (pool, timestamp) | (timestamp, pool) | (pool, block_number, log_index) |
|---|---|---|---|
| Q1 main, the whole table | 463,447 · 57/57 · 19 ms | 463,447 · 57/57 · 21 ms | 463,447 · 57/57 · 23 ms |
| Q2-big (74.5% of the rows) | **32,768** · 4/57 | 49,152 · 6/57 | **348,759** (49,152) · 43/57 |
| Q2-small (122 rows) | **8,192** · 1/57 | 49,152 · 6/57 | **8,192** · 1/57 |
| Q3 one day, all the pools | 65,536 · 8/57 | **49,152** · 6/57 | **463,447** (57,344) · 57/57 |

What is observed, without judging it:

- **The main query reads the whole table with any key.** It groups all the
  pools and all the days: there is nothing to prune. The `ORDER BY` does not affect it (19 to 23 ms,
  17 MB read). The keys only differ on the queries **with a filter**.
- **`(pool, timestamp)`:** with the pool and date filter it reads 4 granules for the big
  pool and 1 for the small one. Filtering **by date only** (Q3) it still prunes (8/57)
  even though the date is the second column of the key: with only 4 distinct values in the
  first, the index can skip inside each one.
- **`(timestamp, pool)`:** it always reads the 6 granules of the day, **whichever the pool is**.
  For the small pool that is 49,152 rows to find a few: 6 times more than
  with the pool first. For the big one, 1.5 times more. It is the best for Q3.
- **`(pool, block_number, log_index)`:** the date filter **does not use the index**, because
  the date is not in the key. For the big pool it reads its 43 granules in full
  (348,759 rows, 10.6 times more than with the timestamp in the key) and for Q3, the whole
  table. For the small pool it makes no difference: it fits in one granule.
- **The effect of the skew, measured:** putting `pool` first saves the small pool almost
  everything (1 granule of 57) and the big one almost nothing on its own (43 of 57): what
  prunes for the big one is the **second** column of the key.
- **The condition cache covers up the problem of the third key** in repeated
  queries (348,759 → 49,152 rows), but not on the first run of each filter, nor
  with `FINAL` (see 2.4).

### 2.3 Monthly partitioning against none

Same key `(pool, timestamp)`; the data crosses from August to September.

| | No partitioning | Monthly |
|---|---|---|
| Parts after optimising | 1 | 2 (one per month) |
| Q1 main | 463,447 rows · 19 ms | 463,447 rows · 21 ms |
| Q2-big | 32,768 rows · 4/57 granules · 1/1 parts | 32,768 rows · 4/43 granules · **1/2** parts |
| Q2-small | 8,192 rows | 8,192 rows |
| Q3 | 65,536 rows | 65,536 rows |
| Primary index in memory | 448 B | 616 B |

- Partition pruning **does happen** (it discards the September part: 1 of 2), but the
  rows read are **identical**: the primary index was already discarding those granules.
- What it adds is one more part, and an extra part for every insert that crosses a month boundary.
- What has not been measured here, because it is not a query: monthly partitioning allows
  `DROP` / `REPLACE PARTITION` of a whole month.

### 2.4 MergeTree against ReplacingMergeTree

Same key `(pool, block_number, log_index)`, which is unique per log. One file in ten was
redelivered to the Replacing table (51,883 repeated rows), simulating
what the backfill runner does if it dies between the sink and the checkpoint.

**Before the merge** (merges stopped; 125 parts):

| | `count()` | Q1 main | Q2-big |
|---|---|---|---|
| Without `FINAL` | **515,330** (11.2% too many) | 23 ms · 515,330 rows · 19 MB | 13 ms · 515,330 rows |
| With `FINAL` | 463,447 (correct) | **69 ms** · 515,330 rows · 23 MB · 16 MB of memory | **67 ms** · 515,330 rows · 23 MB |

**After the merge** (`OPTIMIZE ... FINAL`; 1 part; 463,447 rows):

| | Q1 main | Q2-big | Q2-small |
|---|---|---|---|
| MergeTree, without `FINAL` | 23 ms · 17.2 MB | 4 ms · 348,759 rows · **2.5 MB** | 3 ms · 0.04 MB |
| Replacing, without `FINAL` | 25 ms · 17.2 MB | 6 ms · 348,759 rows · 2.5 MB | 3 ms · 0.04 MB |
| Replacing, with `FINAL` | 22 ms · 17.2 MB | 7 ms · 348,759 rows · **12.9 MB** | 3 ms · 0.30 MB |

- **Without `FINAL` and without a merge, the total comes out 11.2% too high and nothing warns.** It is the
  scenario `SCHEMA_OPTIONS.md` talks about, now with a figure.
- **`FINAL` with many small parts costs 3 times more** on the main query
  (69 against 23 ms). The one-day query takes 67 ms against 13, but reads the
  same rows with and without `FINAL` (the whole table: the key of this experiment has no
  time in it). An earlier version of this text said that `FINAL` "removes the pruning": the
  raw results do not show it. In absolute terms they are still milliseconds.
- **With the table already merged, `FINAL` is almost free in time** (22 against 25 ms),
  but it reads **5 times more bytes** on the filtered query (12.9 against 2.5 MB). My
  explanation, unverified: with `FINAL` the filter does not move ahead of the read
  (`PREWHERE`) and the condition cache does not act, so the full columns
  of every candidate granule are read.
- Once merged, the two tables take exactly the same (56.87 MB).
- **In the first test, with merges active, the duplicates disappeared on their own in
  less than 3 seconds**: "eventual" can be very fast with small tables. But it is not
  guaranteed, and that is why merges were stopped here to measure it.

### 2.5 A trap, measured

`ReplacingMergeTree` with `ORDER BY (pool, block_timestamp)`, a key that is **not
unique per swap** (all the swaps of a pool in a block share a timestamp):

| Rows loaded | Rows in the table | Lost |
|---|---|---|
| 463,447 | **159,151** | **304,296 (65.7%)** |

No error and no warning. And it is not "eventual": the loss was already there **before any
merge** (159,151 rows with merges stopped), because the engine collapses the repeated
keys inside each inserted block. With Replacing, the sorting key has
to be the identity of the row; `(pool, block_number, log_index)` is.

## 3. Settings checked on this version

Several points marked **to verify** in `SCHEMA_OPTIONS.md`, read from `system.settings`
and `system.merge_tree_settings` on 26.3.33.24:

| Setting | Default value here | What it implies |
|---|---|---|
| `non_replicated_deduplication_window` | 0 | Insert deduplication is **off** in a MergeTree without replication. It has to be enabled on the table for `insert_deduplication_token` to be of use |
| `insert_deduplication_token` | empty | It exists as a query setting |
| `max_partitions_per_insert_block` | 100 | An insert that touches more than 100 partitions fails |
| `do_not_merge_across_partitions_select_final` | 0 | Off by default |
| `use_query_condition_cache` | 1 | On by default. See warning 2 |
| `index_granularity` | 8192 | |
| `count_distinct_implementation` | uniqExact | |
| `join_use_nulls` | 0 | |

Not tested: that `insert_deduplication_token` really does discard a redelivered batch with
the window enabled. It is the experiment missing if MergeTree with idempotent ingestion is
the way taken.

## 4. What these numbers suggest, without choosing

- The **main query does not distinguish** between any of the options. What will decide the
  `ORDER BY` are the filtered queries one wants to run alongside it.
- If there is going to be **filtering by date**, having the date in the key changes what is read by an
  order of magnitude (32,768 against 348,759 rows). If the key has to be the
  identity of the log (Replacing), that has to be recovered some other way.
- The **pool/date order** is a tradeoff between queries by pool (above all the
  small ones) and queries of all the pools by date. With 4 pools the largest difference
  measured is 6 times in rows and 0 ms in time.
- **Monthly partitioning changes no read at all**. Its value, if it has one, is operational.
- **Replacing protects the total against redeliveries only if it is read with `FINAL`**, and
  `FINAL` costs more the more unmerged parts there are. MergeTree protects nothing: the
  guarantee has to be in the ingestion. The landing zone already makes the load idempotent per file.
- In **types**, what moves the most bytes is not the 256-bit integers but `tx_hash`.
- **At 881,000 rows, all of this is milliseconds and ~108 MB.** No option is slow. What
  separates the options is correctness and what each one forces you to remember when
  writing queries.
