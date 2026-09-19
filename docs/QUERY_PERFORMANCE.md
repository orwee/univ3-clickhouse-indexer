# Query performance experiments

Measured on 2026-09-20 on a **copy** of the real table (881,187 swaps, 31 days, 4
pools) in a throw-away database, ClickHouse 26.3.33.24. The schema of `onchain`
was not touched. Reproduce with:

```
PYTHONPATH=src:scripts uv run python scripts/query_performance.py > results.json
```

Raw results: `docs/experiments/query-performance-2026-09-20.json`. Rows and bytes
read come from `system.query_log`, granules from `EXPLAIN indexes = 1`. Every
query was run with the query condition cache **off** (what the indexes do by
themselves) and **on** (the default; from the second run of a filter on it
remembers which granules had no match). Timings are medians of 5 runs; at this
size they are all single-digit milliseconds and say little. **Rows read is the
number to look at.**

The table: `ORDER BY (pool_address, block_timestamp, block_number, log_index)`,
`PRIMARY KEY (pool_address, block_timestamp)`, monthly partitions. After
`OPTIMIZE FINAL`: 2 parts (one per month), 109 granules, 74.7 MB.

## 1. What the main queries read, and why

| Query | Rows read (cache off) | Cache on | Granules | ms |
|---|---|---|---|---|
| Daily volume, all pools, whole table | 881,187 | 881,187 | 109 / 109 | 34 |
| One pool, one day: biggest pool (73% of rows) | 24,576 | 24,576 | 3 / 43 | 5 |
| One pool, one day: smallest pool (610 rows in total) | 8,192 | 8,192 | 1 / 43 | 4 |
| All pools, one day | 57,344 | 57,344 | 7 / 43 | 5 |
| All pools, one week | 208,897 | 208,897 | 26 / 43 | 8 |
| Point lookup by `tx_hash` | **881,187** | 8,192 | 109 / 109 | 6 |
| Point lookup, hash that does not exist | **881,187** | 0 | 109 / 109 | 7 |

`EXPLAIN` for "one pool, one day" shows the three stages ClickHouse applies, in
order:

```
MinMax      block_timestamp in [day, day+1)        Parts: 1/2    Granules: 43/109
Partition   toYYYYMM(block_timestamp) = 202608     Parts: 1/1    Granules: 43/43
PrimaryKey  pool_address = … AND block_timestamp…  Parts: 1/1    Granules: 3/43   (binary search)
```

- The **whole-table aggregate reads everything**: there is nothing to prune.
- **Pool and day**: the partition's min/max drops September, then a binary search
  on the primary key leaves 3 granules of 43. The smallest pool fits in one.
- **Day only**: still pruned (7 of 43) although the date is the *second* key
  column, because the first one has only 4 distinct values and the index can skip
  inside each. The read is about four times the single-pool one: one slice per pool.
- **`tx_hash` is not in any index**: a point lookup scans all 109 granules. With
  the condition cache on, the second run of the *same* hash reads one granule;
  a different hash scans everything again.

## 2. A projection ordered by time

`ADD PROJECTION by_time (SELECT * ORDER BY block_timestamp, pool_address)`, for the
"all pools in a date range" pattern. ClickHouse picks it by itself
(`ReadFromMergeTree (by_time)` in `EXPLAIN`).

| Query | Base: rows read | With projection | Granules |
|---|---|---|---|
| All pools, one day | 57,344 | **40,960** (−29%) | 7 / 43 → 5 / 43 |
| All pools, one week | 208,897 | 200,705 (−4%) | 26 / 43 → 25 / 43 |
| One pool, one day | 24,576 | 24,576 (projection not used) | 3 / 43 |
| Whole-table aggregate | 881,187 | 881,187 | 109 / 109 |

Cost: **75.0 MB**, against 74.7 MB for the table itself. `SELECT *` in a projection
is a second full copy of the data in another order: +100% on disk, and every insert
writes both. Built in 0.4 s here.

## 3. A bloom filter skipping index on `tx_hash`

`ADD INDEX tx_bloom tx_hash TYPE bloom_filter(0.01) GRANULARITY 1`.

| Query | Base: rows read (cache off) | With the index | Granules |
|---|---|---|---|
| Point lookup, existing hash | 881,187 | **8,192** | 1 / 109 |
| Point lookup, hash that does not exist | 881,187 | 24,576 | 3 / 109 (false positives) |

Cost: **1.07 MB**, 1.4% of the table, built in 0.04 s. The index does not locate a
row; it says which granules *cannot* contain the value, and the rest are read.
With a 1% false-positive rate and 109 granules, about one false granule per lookup
is expected, and three were seen for the absent hash.

## 4. One insert against a thousand

The same 50,000 rows, inserted once and inserted as 1,000 inserts of 50 rows.
Background merges left running; measured right after and 20 s later
(`system.parts`, `system.part_log`).

| | 1 insert | 1,000 inserts |
|---|---|---|
| Time to insert | 0.14 s | **74.6 s** |
| Parts created | 1 | 1,000 |
| Merges run by the server | 0 | **491** |
| Rows rewritten by merges | 0 | **4,598,150** (92 times the data) |
| Bytes written by merges | 0 | **399 MB** (for 4.3 MB of final data) |
| Merge time | 0 | 12.8 s |
| Active parts right after / 20 s later | 1 / 1 | 7 / 6 |
| Parts still on disk, inactive ones included | 1 | 1,491 |
| Marks | 7 | 17 |

Every insert creates a part; the server then merges small parts into bigger ones,
again and again, and each merge rewrites the rows it touches. The thousand-insert
table ended with the same 50,000 rows, reached by writing the data 92 times over.
Old parts stay on disk for a while after being merged away (1,491 here). Nothing
failed: the active part count never came near `parts_to_delay_insert` (1,000) or
`parts_to_throw_insert` (3,000), because merges kept up with 13 inserts a second.

## What the numbers suggest

Without concluding that anything should change:

- The decided sorting key serves the filtered queries it was chosen for; the
  whole-table aggregate is a full scan with any key, and at 881,187 rows that is
  34 ms.
- The date-range pattern across all pools is already pruned by the primary key.
  The projection improves it by 29% for one day and 4% for a week, and costs a
  second copy of the table.
- A lookup by `tx_hash` is the one pattern the table cannot serve without a full
  scan. The bloom filter turns it into one granule for 1.4% more disk. Whether that
  pattern exists in this project is a separate question.
- The query condition cache hides both effects from the second identical query on:
  measuring with it on would have shown the point lookup as already cheap.
- Batch size is the largest factor measured in this file, by two orders of
  magnitude: 0.14 s against 74.6 s, and 0 against 399 MB of merge writes. The
  loader inserts about 100,000 rows at a time.
