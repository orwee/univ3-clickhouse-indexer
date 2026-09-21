# Schema options for the swaps table (undecided)

> **Historical document, from before the decision.** The schema is already decided: engine in
> [DECISIONS.md #10](../DECISIONS.md#10-engine-mergetree-with-deduplication-left-to-the-load),
> `ORDER BY` and `PRIMARY KEY` in
> [#11](../DECISIONS.md#11-order-by-pool_address-block_timestamp-block_number-log_index-primary-key-on-the-first-two),
> partitioning in [#12](../DECISIONS.md#12-partition-by-month-for-management-and-not-for-speed),
> types in [#13](../DECISIONS.md#13-types-lossless-integers-and-hashes-and-addresses-in-binary)
> and denormalisation in
> [#14](../DECISIONS.md#14-nothing-from-poolsyml-is-denormalised-into-the-raw-table). The real
> table is [sql/001_raw_swaps.sql](../sql/001_raw_swaps.sql). What follows is kept exactly
> as it was written, as a record of the options that were considered.

Working document for Roberto to decide. **Nothing is decided here**: each
section gives options, tradeoffs, a reasoned recommendation and the interview
question that decision usually provokes. The decisions, when they are taken,
go to `DECISIONS.md`, written by him.

The column names that appear are illustrative, not a proposal of names.

> **Reliability notice.** What comes from my own measurements is marked as
> *measured*. What I claim about ClickHouse behaviour is general knowledge,
> not checked against the 26.3.33.24 of this repo. Where the detail matters
> (setting names, default values) it says **check**: they are good candidates
> for trying in the container before taking them as good.

## 0. The numbers that govern

Measured on 2026-09-18 against Alchemy (detail in `docs/MEASUREMENTS.md`, RPC
client branch):

| Figure | Value |
|---|---|
| Estimated rows in 30 days | **~684,000** (3.17 swaps per block, 216,000 blocks) |
| Rows per day | ~23,000 |
| Split per pool | USDC/WETH 0.01%: **99.5%** · wstETH/USDC 0.05%: ~3,100 rows · wstETH/USDC 0.3%: of the order of 1,000 |
| Swaps per block (max seen) | 9 |
| Swaps per transaction (max seen) | 4 |

Two consequences that run through the whole document:

1. **The data set is tiny for ClickHouse.** With the default granularity
   (8,192 rows per mark) that is about **84 marks** in total. Any reasonable
   schema answers in milliseconds. Almost no decision here will show in speed:
   they show in **correctness** (duplicates, loss of precision) and in **what
   you are able to explain**. It is worth saying exactly that in the interview
   instead of pretending a problem of scale.
2. **The skew is extreme.** One pool is 99.5% of the rows. An index that
   starts with `pool` discards almost everything when you ask about a small
   pool and almost nothing when you ask about the big one.

---

## a. Engine: MergeTree or ReplacingMergeTree

### The real problem

The logs of finalised blocks are immutable: the chain does not correct them.
Duplicates can only come **from our own pipeline**. The backfill runner (RPC
client branch) delivers *at least once*: if the process dies after the sink
accepts a batch and before the checkpoint is saved, that batch is delivered
again. There is a test that demonstrates it on purpose. The question is where
that is resolved.

### Option 1: MergeTree + idempotent ingestion

The table knows nothing about duplicates; the pipeline guarantees that it does
not put any in. Ways to achieve that:

- **Insert deduplication by token.** ClickHouse can discard a repeated insert.
  On replicated tables it comes enabled; on MergeTree without replication it
  has to be enabled with the table setting `non_replicated_deduplication_window`
  (0 by default, disabled) (**check**). With the query setting
  `insert_deduplication_token` you set the token yourself, for example the
  range of the batch (`"26000000-26000499"`): a batch redelivered with the same
  token is discarded whole. It fits the runner, which redelivers with the same
  starting block. Small print: the window is finite (the last N inserts), and
  the last short batch of a run can be redelivered with a higher end, so the
  token should be derived from the starting block.
- **Load per partition with an atomic swap.** Load into a staging table and do
  `ALTER TABLE ... REPLACE PARTITION`. Idempotent by construction and atomic,
  but it ties ingestion to partitioning (section c).
- **Delete the range and reinsert.** `ALTER TABLE ... DELETE` is a mutation:
  asynchronous and it rewrites whole parts. There is the lightweight
  `DELETE FROM`, cheaper. It works, but it is using a hammer: in ClickHouse
  deleting is the expensive operation.

For: the queries are simple and always correct, with no `FINAL` and no
`argMax`. What you see in the table is what there is.
Against: if the pipeline fails its guarantee, the duplicates stay forever and
nobody warns you. It has to come with a test that watches for it (in dbt:
`count()` against `uniqExact` of the log identity).

### Option 2: ReplacingMergeTree

The table removes, **during merges**, the rows with the same sorting key,
keeping the last one (or the one with the highest version if it is given a
version column).

What has to be clear, because it is where people get it wrong:

- Deduplication is **eventual and with no guaranteed deadline**. The merges
  happen when ClickHouse wants. In the meantime, the duplicates are there and
  are read.
- It only deduplicates rows **with the same ORDER BY key** and **within the
  same partition**. The sorting key becomes the deduplication key: this
  constrains section b.
- To read without duplicates you have to ask for it: `SELECT ... FINAL`, or
  aggregate with `argMax` / `GROUP BY` over the key. Forgetting it in a single
  query gives a wrong number, silently.
- **Cost of `FINAL`**: it does the merge's work at read time. Historically it
  was serious (almost sequential reading); recent versions parallelise it and
  allow not merging across partitions
  (`do_not_merge_across_partitions_select_final`) (**check**). With 684,000
  rows the cost is milliseconds: here it is not a performance argument, but
  one of **discipline in the queries**.
- `OPTIMIZE TABLE ... FINAL` forces the merge. It is good for a demo or after a
  backfill, not as a scheduled operation: it rewrites everything.

For: a safety net inside the table; it tolerates an imperfect pipeline.
Against: every query (and every dbt model) carries `FINAL` or an equivalent, and
the sorting key stops being chosen for the queries alone.

### Recommendation

**MergeTree with idempotent ingestion (a token per batch) and a duplicates
test.** The data is immutable by nature; ReplacingMergeTree is meant for rows
that change (upserts, CDC), and using it to cover a pipeline defect moves the
cost onto every query, forever. Fixing it at the source is cheaper and easier
to reason about.

That said, for this project there is an argument for **trying both**: load the
same data into a table of each type, force the redelivery of a batch and show
with `system.parts` and `system.query_log` what happens before and after the
merge and how much `FINAL` costs. It is exactly the kind of thing the project
says it wants to observe (DECISIONS #1).

### Interview question

*"You have duplicates in a ReplacingMergeTree table and your dashboard gives
inflated figures. Why, if the engine deduplicates?"* Expected answer: it
deduplicates on merges, eventually, by sorting key and by partition; you have
to read with `FINAL` or aggregate; and the underlying question is why duplicates
are arriving. Usual follow-up: *"and how much does FINAL cost and how would you
reduce it?"*

---

## b. ORDER BY

### How it works, in three sentences

The rows of each part are stored **sorted** by the key. The primary index is
**sparse**: it stores the key value once per granule (8,192 rows), not per row,
and it fits in memory. A query with a filter on a prefix of the key does a
binary search over those marks and reads only the granules that can contain
data; for columns that are not a prefix the index helps little, unless the
earlier ones have low cardinality.

Practical rule: columns you filter by, **from lowest to highest
cardinality**. The order also decides the compression: similar values
together compress better.

Here: 684,000 rows are ~84 granules. The two small pools fit in **less than
one granule each**. A full scan of the table is trivial. The decision matters
for correctness (if the engine is Replacing) and for being able to justify it.

### The main query

Daily volume per pool: it filters (or groups) by `pool` and by date range.

### The tension

The "natural" identity of a log is usually written `(tx_hash, log_index)`. As a
sorting key it is **the worst possible one**: `tx_hash` is random, so it
destroys locality (rows from the same day spread across the whole table), the
index is no use for date ranges and the compression gets worse.

Way out: `log_index` is the index of the log **within the block**, not within
the transaction. So `(block_number, log_index)` identifies a log in the
canonical chain just as well as `(tx_hash, log_index)`, and it is also
monotonic in time. A key `(pool, block_number, log_index)` serves **both** the
queries and the deduplication. The tension dissolves almost entirely; what is
left is the nuance of reorgs (same block number, different hash), which is
avoided by ingesting only finalised blocks (the runner stays 64 blocks behind
the tip).

*Measured in the fixtures:* `(block_hash, log_index)` is unique across the 205
real logs (there is a test that checks it).

### Candidates

| Key | For the main query | As a dedup key | Comment |
|---|---|---|---|
| `(pool, block_timestamp, log_index)` | Very good: low-cardinality prefix and then time; the date filter uses the index | Valid in practice (one block per 12 s slot, one timestamp per block), but it depends on that property | The most direct one for date queries |
| `(pool, block_number, log_index)` | Good by pool; **a date filter does not use the index** (the key does not contain the date) unless there is a minmax index on the timestamp or partition pruning | Exact and with no assumptions | The cleanest as an identity; it matches how the checkpoint works |
| `(toDate(block_timestamp), pool, ...)` | Good if the usual thing is "all the pools in a date range" | Same as above | With 3 pools the difference from pool-first is imperceptible |
| `(tx_hash, log_index)` | Bad | Exact | Only to explain why not |

Note: `PRIMARY KEY` can be a **prefix** of `ORDER BY`. For example sort by
`(pool, block_timestamp, log_index)` and index only
`(pool, block_timestamp)`: `log_index` gives a deterministic order (and dedup)
without taking space in the in-memory index. Here the saving is nil, but it is
a detail that shows the difference between the two clauses is understood.

### Recommendation

`ORDER BY (pool, block_timestamp, log_index)` if the engine is MergeTree
(section a): it is the one that answers the main query with no help. If
ReplacingMergeTree is chosen, better `(pool, block_number, log_index)`, which is
an exact identity, adding a `minmax` skipping index on the timestamp or relying
on partition pruning for the date filters.

With the 99.5% skew, `pool` first helps the small pools a lot and the big one
not at all: for the big one what prunes is time, which goes second. It is the
correct order all the same.

### Interview question

*"How does the ClickHouse primary index differ from the Postgres one, and what
happens if I filter by a column that is not a prefix of the key?"* And the trap:
*"Why not sort by tx_hash, if it is what identifies the row?"*

---

## c. PARTITION BY

### The honest thing first

**Partitioning is data management, not speed.** A partition is the unit for
deleting, moving, swapping or expiring data (`DROP` / `DETACH` /
`REPLACE PARTITION`, TTL). For queries to go fast there is the sorting key.
There is partition pruning, yes, but the primary index already does that work,
and over-partitioning makes things **worse**:

- Parts **never merge across partitions**. More partitions = more small
  parts = more files and worse compression.
- An insert that touches N partitions creates N parts. With small batches and
  fine partitions you reach the "too many parts" error.
- There is a limit of partitions per insert block
  (`max_partitions_per_insert_block`, 100 by default) (**check**): a one-year
  backfill with daily partitions breaks it on the first insert.
- The general guidance is to keep the number of partitions in the tens or
  hundreds, not thousands.

### Options for ~30 days and ~684,000 rows

| Option | Partitions | Rows per partition | Assessment |
|---|---|---|---|
| None | 1 | 684,000 | Perfectly defensible at this size. The simplest. You lose the ability to reload or drop a chunk with a partition operation |
| Monthly `toYYYYMM(ts)` | 1 or 2 | ~340,000 to 684,000 | The convention. It gives `REPLACE PARTITION` as an idempotent reload mechanism and scales unchanged if the window grows to a year (12 partitions) |
| Daily `toDate(ts)` | 30 | ~23,000 | 30 partitions of 3 granules each. It gives no trouble at this size, but it is the wrong habit: at a year it is 365, and every backfill batch that crosses days creates several parts. It is only justified if the real reload unit is the day |

Interaction with section a: ReplacingMergeTree does not deduplicate across
partitions. It is not a problem here (the same log always falls in the same
partition), but it has to be known.

### Recommendation

**Monthly.** Not for speed (at this size there is no measurable difference), but
because it is the natural management unit, it leaves reload per partition open
and it is the answer that does not have to be corrected if the window goes from
30 days to a year. "None" is the second option and it is honest; "daily" is the
one that would have to be defended, and here there is nothing to defend it with.

### Interview question

*"Would you partition this table by day so that date queries go faster?"* The
answer they are looking for is "no, that is what the ORDER BY is for", followed
by the problems over-partitioning brings. Follow-up: *"and when would you
partition by day?"* (daily TTL retention, atomic daily reloads, volumes of
billions of rows per month).

---

## d. Types

Ranges *measured* over 1,474 real decoded swaps (the 205 from the fixtures plus
the rest of the sample they came from), blocks 26,003,451 to 26,003,970.

| Field | Solidity type | Range seen | Bits needed (seen) | Options | Recommendation |
|---|---|---|---|---|---|
| amount0 | signed int256 | USDC: ±1.27e11 (±127,000 USDC). wstETH: ±6.1e16 | 37 / 56 | Int64, Int128, **Int256** | **Int256** |
| amount1 | signed int256 | WETH: **±5.08e19** (±50.8 WETH). USDC: ±1.9e8 | **66** / 28 | Int64, Int128, **Int256** | **Int256** |
| sqrtPriceX96 | uint160 | 1.58e33 (USDC/WETH) · 4.4e24 (wstETH/USDC) | 111 / 82 | UInt128, **UInt256** | **UInt256** |
| liquidity | uint128 | 1.3e13 to 7.7e17 | 60 | UInt64, **UInt128** | **UInt128** |
| tick | signed int24 | +198,002 to +198,131 · −195,874 to −195,601 | 18 + sign | Int16, **Int32** | **Int32** |
| log_index | integer | max. 2,253 | 12 | UInt16, UInt32 | UInt32 |
| tx_index | integer | max. 575 | 10 | UInt16, UInt32 | UInt16 or UInt32 |
| block_number | integer | ~26,003,000 | 25 | **UInt32**, UInt64 | UInt32 |
| block_timestamp | seconds | comes in the log itself (Alchemy) | | **DateTime('UTC')**, DateTime64 | DateTime('UTC') |

What the data says, beyond the table:

- **Int64 overflows on real data.** A swap of 50.8 WETH is 5.08e19 minimum
  units and the maximum of Int64 is 9.22e18. It is not a theoretical case: it
  appears in half an hour of data from a low-fee pool. Any 64-bit type for
  amounts of tokens with 18 decimals is a bug waiting to happen.
- **Int128 would fit what has been seen**, but the ABI type is int256 and
  decision #3 talks about decoding without loss. Int256 is the only option that
  needs no argument. The cost: 32 bytes per value uncompressed, but the high
  bytes are almost always zeros (or `ff` on negatives) and the compression eats
  them; arithmetic on 256 bits is slower, irrelevant at 684,000 rows. It can be
  measured in `system.columns` (compressed against uncompressed bytes per
  column), which is a good demo.
- **Careful when converting to floating point.** `toFloat64` of an Int256 loses
  precision above 2^53. For analytics (volume in USD) it does not matter; for
  **reconciling** against the subgraph, it does: the reconciliation has to be
  done over integers or over `Decimal`, and the readable amounts have to be
  derived columns in dbt, not a replacement for the raw ones.
  `Decimal(38, 18)` takes 38 digits and what has been seen has 20: it fits with
  room to spare (**check** the behaviour of the Int256 to Decimal division).
- **sqrtPriceX96 has no native 160-bit type.** UInt128 would hold what has been
  seen (111 bits), but not the range of the type: a pair with very different
  decimals can exceed it. UInt256.
- **tick does not fit in Int16** (±32,767): what has been seen reaches
  ±198,000. There is no Int24 in ClickHouse; Int32.
- **liquidity** is uint128 and ClickHouse has UInt128: an exact fit.

Text and hash fields:

| Field | Options | Comment |
|---|---|---|
| pool (3 values) | `LowCardinality(String)` in hex, `FixedString(20)` binary, `Enum` | LowCardinality in hex: readable and, with 3 values, it takes practically nothing. Enum forces an `ALTER` for every new pool |
| tx_hash | `String` of 66 characters, `FixedString(32)` binary | Random, it does not compress: ~45 MB against ~22 MB over 684,000 rows. The binary one saves half but forces `hex()` / `unhex()` in every query and in the join with the subgraph, whose identifiers are hex text. At this size, readability |
| sender | `LowCardinality(String)`, `String` | *Measured:* 145 distinct in 1,474 swaps (they are mostly routers). A good candidate for LowCardinality |
| recipient | `String`, `LowCardinality(String)` | *Measured:* 277 distinct in 1,474 and it grows with no ceiling. LowCardinality stops paying off towards tens or hundreds of thousands of values (**check**). Measure with the full month before deciding |
| block_hash | store it or not | Not needed for analytics. It is useful for auditing reorgs. 66 bytes per row that do not compress |

Codecs (optional, measurable): `Delta` or `DoubleDelta` plus `ZSTD` on
`block_number` and `block_timestamp`, which are monotonic. A real gain in bytes,
none in perception at this size; useful as a demonstration with
`system.columns`.

To check before fixing anything: that `clickhouse-connect` inserts and reads
Int256 / UInt256 as a Python `int` without going through float (**check** with a
round-trip test using the extreme value from the fixtures).

### Interview question

*"Why Int256 and not Decimal or Float64 for the amounts?"* It is answered with
the data: 50.8 WETH already do not fit in 64 bits, Float64 loses integers from
2^53 on, and reconciliation demands exact equality. Follow-up: *"and what does
it cost you?"* (storage almost nothing thanks to compression; slower arithmetic;
explicit conversions in the presentation layer).

---

## e. What to denormalise from pools.yml

`pools.yml` has, per pool: address, symbols, decimals, fee and label. The
decimals are needed for any readable amount; the label and the fee, for any
report.

| Option | For | Against |
|---|---|---|
| **Nothing in the raw table**; `pools.yml` loaded as a dbt seed (or a small table) and joined in the models | The raw table is faithful to the chain. `pools.yml` stays the single source. Changing a label does not touch data | A join in every model that needs decimals (against a table of 3 rows: free) |
| **A ClickHouse dictionary** over that table, with `dictGet` | Idiomatic in ClickHouse, no join, in memory | One more piece to create and refresh; less natural in dbt |
| **Denormalise into the raw table** (symbols, decimals, fee on every row) | Direct queries with no join. In a columnar store, with 3 distinct values and LowCardinality, the cost on disk is almost zero | It mixes facts from the chain with metadata maintained by hand. If a value in `pools.yml` was wrong, the table has to be rewritten. Two sources of truth |
| **Denormalise in the dbt marts layer**, not in the raw one | The best of both: a faithful raw table, marts that are convenient and rebuildable with `dbt run` | None relevant |

Context worth being able to explain: in ClickHouse denormalising is cheap
(columnar and compression) and joins are comparatively expensive because the
right-hand side is loaded in memory as a hash table. That is why the culture is
"wide table". But that cost depends on the size of the right-hand side, and here
it is 3 rows.

### Recommendation

**A raw table with only the pool address; `pools.yml` as a dbt seed;
denormalise in the marts.** The decimals and the fee are immutable on the
chain, so denormalising them would not be a mistake, but the label is
editorial and `pools.yml` has to stay the single source (it is also a rule for
the agents).

### Interview question

*"In ClickHouse denormalising is recommended. Why would you do a join here?"*
Answer: because the recommendation comes from the cost of the join, which
depends on the size of the right-hand side; with a dimension of 3 rows the cost
is nil and you gain a single source of truth. Follow-up: *"and with 50,000
pools?"* (a dictionary, or denormalising at ingestion).

---

## Summary for deciding

| # | Decision | Recommendation | Reasonable alternative | Roberto's decision |
|---|---|---|---|---|
| a | Engine | MergeTree + idempotent ingestion (a token per batch) + duplicates test | ReplacingMergeTree, or both in parallel as an experiment | |
| b | ORDER BY | `(pool, block_timestamp, log_index)` | `(pool, block_number, log_index)` if the engine is Replacing | |
| c | PARTITION BY | Monthly | None | |
| d | Types | Int256 / UInt256 / UInt128 / Int32; readable hex text | Binary FixedString for hashes | |
| e | Denormalisation | Nothing in the raw table; dbt seed; denormalise in marts | Dictionary | |

Suggested order: **a** before **b** (the engine constrains the key), and **d**
with a round-trip test of Int256 through `clickhouse-connect` before writing
the DDL.
