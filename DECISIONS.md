# Decisions

> Drafted with AI assistance from the measurements in this repo and checked by an independent review pass. Design decisions were proposed with AI assistance, tested by measurement and approved by Roberto.

Why things are the way they are, written when the decision was made, including
what I gave up. Newest entries go at the bottom. An entry is never rewritten:
if I change my mind, I add a new entry and mark the old one `Superseded by #N`.

## Entry template

```
## N. Short title

- Date: YYYY-MM-DD
- Status: Accepted | Superseded by #N

**Context.** What forced a choice.
**Decision.** What I chose.
**Why.** The reasoning, and the measurement behind it.
**Tradeoff.** What this costs me or leaves out.
**Revisit when.** The signal that would make me reopen it.
```

---

## 1. Local Docker instead of the ClickHouse Cloud trial

- Date: 2026-09-18
- Status: Accepted

**Context.** I am learning ClickHouse for an interview and will show this repo
publicly. I can run the server locally or use the Cloud trial.

**Decision.** A single ClickHouse server in Docker, started with `make up`.

**Why.** I need to observe the real MergeTree engine: parts, merges and the
system tables that describe them. Cloud swaps in SharedMergeTree, so what I
would be looking at is not the engine I want to understand. And the repo has to
be reproducible by anyone with one command, without an account or a trial that
expires.

**Tradeoff.** I get no experience of the managed product: no SharedMergeTree,
no separation of storage and compute, no Cloud console.

**Revisit when.** Stretch goal: load the same data into a Cloud trial and
compare parts, merges and query plans side by side.

## 2. RPC as the raw source, the subgraph only as an external check

- Date: 2026-09-18
- Status: Accepted for the RPC part. The choice of the subgraph as the external
  check is superseded by #17

**Context.** Swap events are available from an Ethereum JSON-RPC node and,
already decoded, from the Uniswap subgraph.

**Decision.** Ingest from RPC (`eth_getLogs`). Use the subgraph only to
reconcile against.

**Why.** Reconciling against the same source you ingested from proves nothing.
The check is only worth something if the two paths are independent: raw logs
decoded by me on one side, someone else's indexer on the other.

**Tradeoff.** The free tier limits `eth_getLogs` to a 10-block range, which
means about 21k calls for the window I want. Checkpointing is mandatory, not
optional: the backfill must be resumable from the last completed range.

**Revisit when.** The call count or rate limits make the backfill impractical,
or I need a window long enough to justify a paid tier.

## 3. Plain JSON-RPC over `requests`, not web3.py

- Date: 2026-09-18
- Status: Accepted

**Context.** I need an Ethereum client in Python. web3.py is the default choice.

**Decision.** Plain JSON-RPC calls over `requests`. No web3.py.

**Why.** I only need two methods, `eth_blockNumber` and `eth_getLogs`. I want
to control the chunking into 10-block ranges, the retries and the checkpoint
myself, because that is where this pipeline can go wrong. And decoding the Swap
event by hand is something I want to be able to explain in an interview.

**Tradeoff.** I write and test the decoding of signed `int256` values myself
(`amount0` and `amount1` are two's complement; `tick` is a signed `int24`).

**Rule that follows.** The Swap `topic0` is not written from memory. It is a
constant with the event signature in a comment next to it, and a test verifies
it against the real logs in the fixtures.

**Revisit when.** I need more than a handful of methods, or ABI decoding for
many event types.

## 4. Two secrets files, split by who is allowed to read them

- Date: 2026-09-18
- Status: Accepted

**Context.** The first version of this setup had a single env file holding both
the ClickHouse credentials and the API keys. Autonomous agents work on this
repo over the weekend as an unprivileged user.

**Decision.** Two files outside the repo, both mode 600:

- `clickhouse.env`, owned by the unprivileged user: `CLICKHOUSE_*` and `CH_*`.
  It is the compose `env_file` and what the tests use.
- `api-keys.env`, owned by root: `ALCHEMY_API_KEY` and `NANSEN_API_KEY`. Only
  interactive sessions and the backfill I launch myself can read it.

The config module loads both paths. The API keys file is optional: it is read
only when a key is requested, and only then does it fail loudly.

**Why.** The agents must not be able to read the API keys. A rule telling them
not to is weaker than a file permission that stops them. Nansen gives me 10
credits a day; one careless loop would burn them.

**Tradeoff.** Two files and two path pointers instead of one. Anything that
needs an API key has to run as a user who can read the second file, so the
backfill cannot be delegated to an agent.

**Revisit when.** A job that needs a key has to run unattended. Then: a
dedicated key with its own quota for that job, not a wider file permission.

## 5. Pinned versions: ClickHouse 26.3 LTS and Python 3.12

- Date: 2026-09-18
- Status: Accepted

**Context.** The repo must behave the same next month as today.

**Decision.** `clickhouse/clickhouse-server:26.3.33.24`, an exact patch of the
26.3 LTS line, never `:latest`. Python 3.12 via `.python-version`, dependencies
locked in `uv.lock`.

**Why.** On the day of the decision there were two live LTS lines. 26.3 had
six months of patches behind it; 26.8 was a month old and had shipped four
patch releases in four days. For watching parts and merges I need stability,
not the newest features. Python 3.12 is the version the whole planned stack
declares: dbt-core 1.12 lists 3.10 to 3.14, but dbt-clickhouse 1.10.3 only
lists up to 3.13, and 3.12 is the most exercised with dbt.

**Tradeoff.** I do not get 26.8 features. Found while checking: dbt-clickhouse
1.10.3 requires `dbt-adapters<1.25` and dbt-core 1.12.5 requires
`dbt-adapters>=1.24.5`, so exactly one dbt-adapters version satisfies both.
That will need an explicit pin when dbt is added.

**Revisit when.** 26.3 stops receiving patches, or dbt-clickhouse declares a
newer Python.

## 6. A hard 3 GiB memory limit with no swap, and what ClickHouse does with it

- Date: 2026-09-18
- Status: Accepted

**Context.** The container shares an 11 GiB machine with other services. The
first compose file set only `mem_limit: 3g`. `docker inspect` showed
`MemorySwap` at 6 GiB: with `memswap_limit` unset, Docker allows as much swap
again on top of the RAM limit.

**Decision.** `mem_limit: 3g` and `memswap_limit: 3g`. `memswap_limit` is RAM
plus swap, so making both equal means no swap at all. Verified:
`HostConfig.MemorySwap` equals `HostConfig.Memory` and `memory.swap.max` is 0
inside the container.

**Why.** A database that swaps does not fail, it just gets slow in a way that
is hard to attribute. I would rather have a query die with a clear memory error
than have timings I cannot trust while I am learning what is expensive.

**What ClickHouse does with the limit.** The server reads the cgroup limit, not
the host RAM, and applies `max_server_memory_usage_to_ram_ratio` (0.9) to it:
`max_server_memory_usage` comes out at 2.70 GiB, not 3. That is the number a
`MEMORY_LIMIT_EXCEEDED` error will refer to. The remaining 10% is headroom for
allocations the server does not track, so the kernel OOM killer stays out of it.

**Tradeoff.** Large merges or a careless `GROUP BY` over the whole backfill can
hit 2.70 GiB and fail. I will have to size inserts and queries with that in
mind, or use the external aggregation and sorting settings.

**Revisit when.** Merges or dbt models fail on memory with reasonable batch
sizes. First lever is the query, second is raising the limit.

## 7. dbt-adapters must be pinned to 1.24.5 when dbt is added

- Date: 2026-09-18
- Status: Accepted (applies from the session that adds dbt)

**Context.** Found while checking Python support for the dbt stack, before any
dbt code exists. dbt-clickhouse 1.10.3 requires `dbt-adapters>=1.22.0,<1.25.0`.
dbt-core 1.12.5 requires `dbt-adapters>=1.24.5,<2.0`. The intersection is a
single version.

**Decision.** When dbt goes into `pyproject.toml`, pin `dbt-adapters==1.24.5`
explicitly, next to dbt-core and dbt-clickhouse, and let `uv.lock` hold it.

**Why.** Today the resolver lands on 1.24.5 by itself, so the constraint is
invisible. The day dbt-core raises its floor, the resolver will quietly walk
dbt-core backwards instead of failing, and I would find out from a behaviour
change. An explicit pin turns that into a resolution error I can read. Related:
uv already resolves dbt-core to 1.12.0 rather than 1.12.5. My unverified guess
is that 1.12.5 requires `dbt-core-experimental-parser>=2.0.0b1`, a pre-release
that uv will not select by default. To be checked when dbt is added.

**Tradeoff.** One more pin to maintain by hand, and no newer dbt-core until
dbt-clickhouse widens its range.

**Revisit when.** dbt-clickhouse publishes a release that accepts
`dbt-adapters>=1.25`.

## 8. Pool addresses come from Orwee, and are trusted only after on-chain checks

- Date: 2026-09-18
- Status: Accepted

**Context.** I picked the three pools by filtering in the dashboard of Orwee's
discovery engine (orwee.io). Orwee is multi-chain and multi-protocol, so an
address coming out of it is not necessarily a Uniswap v3 pool, and not
necessarily on Ethereum mainnet.

**Decision.** `pools.yml` is filled in by hand and is the single source of
addresses, but an address only goes in after `scripts/verify_pools.py` has
checked it against mainnet: `eth_getCode`, then `factory()`, `token0()`,
`token1()`, `fee()`, and `symbol()` / `decimals()` of each token. A pool is
valid only if its `factory()` returns the official UniswapV3Factory. A pool
that fails is reported, never silently replaced.

**Where the factory address comes from.** Not from memory. It is the
`UniswapV3Factory` row, "Mainnet" column, of the official deployments page:
<https://docs.uniswap.org/contracts/v3/reference/deployments/ethereum-deployments>
(it redirects to
<https://developers.uniswap.org/docs/protocols/v3/deployments/v3-ethereum-deployments>).
Value read on 2026-09-18: `0x1F98431c8aD98523631AE4a59f267346ea31F984`.
**To be checked by me by hand against that page.**

**Why.** A discovery tool tells me a pool is interesting, not what it is.
Indexing a fork or a pool on another chain would produce numbers that look
fine and reconcile against nothing. The same goes for the function selectors
and the event `topic0`: they are constants in the code with the signature in a
comment, and a test recomputes each with keccak-256 (pycryptodome, a dev-only
dependency).

**One check beyond what I asked for.** A contract can return anything from its
own `factory()`. So the script also asks the factory itself,
`getPool(token0, token1, fee)`, and compares the answer with the candidate
address. That direction cannot be faked by the pool.

**Result on 2026-09-18, at block 26003980.** All three candidates valid, both
checks passing. Evidence in `docs/verification/pools-2026-09-18.json`.

| Pool | Pair | Fee |
|---|---|---|
| `0xE0554a476A092703abdB3Ef35c80e0D76d32939F` | USDC / WETH | 0.01% |
| `0x173821f6aD4c5324cd35753A9FD12D92f2eaAB29` | wstETH / USDC | 0.3% |
| `0x4622Df6fB2d9Bee0DCDaCF545aCDB6a2b2f4f863` | wstETH / USDC | 0.05% |

**Tradeoff.** The verification needs the Alchemy key, so it is a manual step
run by me, not something CI or an agent can repeat. `symbol()` is informative
only: anyone can deploy a token called USDC, which is why the token addresses
are recorded next to each pool.

**Revisit when.** A pool is added or replaced: run the script again and commit
the new evidence file.

## 9. A fourth pool, derived from the factory instead of typed

- Date: 2026-09-19
- Status: Accepted

**Context.** The first measurement showed a badly skewed data set: one pool
(USDC/WETH 0.01%) produced 99.5% of the rows and wstETH/USDC 0.3% hardly trades.
That makes every per-pool comparison degenerate, and it hides what an `ORDER BY`
starting with the pool actually prunes.

**Decision.** Add USDC/WETH 0.05% on Uniswap v3 mainnet, keeping the other
three. The same pair in two fee tiers is also the more interesting comparison.

**How the address was obtained.** Not from memory and not from a website: the
official factory was asked `getPool(USDC, WETH, 500)`, with the two token
addresses taken from the on-chain evidence of entry 8, and the answer went
through the same verification as the other pools
(`scripts/verify_pools.py --get-pool`). Result at block 26010777:
`0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640`, valid. Evidence in
`docs/verification/pools-2026-09-19.json`.

**Effect, measured.** ~4.08 swaps per block, ~881,000 rows for 30 days, split
73% / 26% / 1%. Backfill time does not change: all pools travel in one call.

**Tradeoff.** About 30% more rows and disk. A checkpoint written for three
pools cannot be resumed with four (the runner refuses, on purpose), so the pool
set has to be final before the backfill starts.

**Revisit when.** I want a pair that is not USDC/WETH to carry real volume.

## 10. Engine: MergeTree, with deduplication left to the load

- Date: 2026-09-19. Reasoning replaced on 2026-09-21, after measuring `FINAL` with the
  sorting key that was actually chosen; the decision itself did not change
- Status: Accepted

**Context.** The backfill ends at the block the node reports as finalised
(`eth_getBlockByNumber("finalized")`, since 2026-09-21; until then it ended 64
blocks behind the tip, which is deep but is not finality: the provider's finalised
block was 93 blocks behind its tip when this was checked). Finalised logs do not
change, so duplicates can only come from the pipeline itself: the backfill runner
delivers at least once. The choice was between letting the engine clean up
(ReplacingMergeTree) or making the load idempotent and keeping a plain MergeTree.

**Decision.** `ENGINE = MergeTree`. Deduplication is not the engine's job. The
landing zone is idempotent (a batch delivered twice rewrites the same file) and
the load is made idempotent on top of it: a full load rebuilds the table, and the
incremental load compares each file's row count with what the table holds for
that block range, then skips, inserts or repairs. What this does not cover is an
INSERT retried after the server had already applied it; `make load-verify`
(duplicates, counts, coverage) is what would catch that.

**Why (measured 2026-09-21 with the real key; `scripts/final_experiment.py`,
`docs/experiments/final-real-key-2026-09-21.json`).** The cost of `FINAL` is **not**
the argument. With `ORDER BY (pool_address, block_timestamp, block_number, log_index)`,
which is unique per log, a ReplacingMergeTree lost no row, and `FINAL` read exactly the
same rows as the query without it: pruning intact, 39,756 rows either way with 221
unmerged parts, 24,576 either way once merged. It cost 116 ms against 45 and 48 MB
against 9 on the whole-table aggregate while unmerged, 51 ms against 39 once merged,
and nothing measurable with `do_not_merge_across_partitions_select_final = 1`; the
filtered queries paid 0 to 4 ms. MergeTree stands on three other things:

- **(a) Every reader would have to remember `FINAL`.** With 10% of the files
  redelivered and the parts not yet merged, a Replacing table read a total **10.0%
  too high** and one day of the big pool read **28,179 swaps instead of 23,961** —
  no error, no warning. That discipline would have to hold in every ad-hoc query and
  every dbt model, forever, and the day it fails the number is quietly wrong.
- **(b) The materialized view counts a redelivered row twice whatever the engine.**
  `swaps_daily_agg` is fed by an insert trigger, which sees rows as they are inserted
  and knows nothing about later deduplication. So the load has to be idempotent for the
  view to be right, and once it is, Replacing protects nothing that is not already
  protected.
- **(c) The cost accepted.** In a MergeTree a duplicate that does get in stays: the
  same experiment ends with **988,485 rows before and after the merge** against 898,404
  real ones. Nothing inside the table will ever remove it. That is why
  `sql/sanity/02_duplicates.sql` (`make sanity`) looks for any `(block_number, log_index)`
  stored more than once and fails on a single row, and why `make load`, `make load-full`
  and `make load-verify` all end by comparing the table with the landing zone.

**Tradeoff.** Nothing inside the table protects me. If the load ever inserts a
file twice, the duplicates stay until I reload. So the load verifies itself
(row count against the landing zone, zero duplicates by `(block_number,
log_index)`) and fails loudly.

**History: what this entry argued until 2026-09-21.** The original reasoning was
that "Replacing moves the cost of a pipeline defect onto every query, forever, and
makes the sorting key serve deduplication instead of queries", resting on an
experiment on 463,447 and then 863,587 real swaps
(`docs/SCHEMA_EXPERIMENTS.md`): a Replacing table whose sorting key was **not**
unique per swap lost 65.7% and then 64.4% of the rows, silently and at insert
time; without `FINAL` an unmerged table read 11.2% and then 10.5% too high; and
`FINAL` on unmerged parts cost 3x and then 2.8x on the main query. An earlier
version also said `FINAL` "removed index pruning". Two of those claims did not
survive scrutiny. The pruning one was never in the raw results: that query read
the whole table with and without `FINAL`, because the key tested there had no
time in it. And the lost-rows figure measures a key nobody proposed, so it is
evidence for "know your deduplication key", not for MergeTree over Replacing. The
key that was chosen is unique, so the second half of the original sentence — that
the key would have to serve deduplication instead of queries — is simply not true
here. The decision survives on (a), (b) and (c) above.

**Revisit when.** The data stops being append-only (for example ingesting
blocks that can still be reorganised), or the landing zone goes away.

## 11. ORDER BY (pool_address, block_timestamp, block_number, log_index), PRIMARY KEY on the first two

- Date: 2026-09-19
- Status: Accepted

**Context.** The sorting key decides what a filtered query has to read. The
main query (daily volume per pool) reads the whole table with any key, so the
key has to be chosen for the filtered queries around it: one pool, a date range.

**Decision.** `ORDER BY (pool_address, block_timestamp, block_number,
log_index)` with `PRIMARY KEY (pool_address, block_timestamp)`.

**Why.** Measured for one day of the biggest pool (74.5% of the rows), query
condition cache off:

- time in the key, `(pool, timestamp)`: **32,768 rows read** (4 of 57 granules);
- time not in the key, `(pool, block_number, log_index)`: **348,759 rows read**
  (43 of 57 granules), because a date filter cannot use an index that does not
  contain the date.

On the full 30 days the first figure does not move (**32,768 rows**, 4 of 106
granules) and the second grows with the table (**634,211 rows**, 78 of 106):
a query the key serves well reads the same as the data doubles, one it does
not serve reads in proportion.

Pool first because there are 4 distinct values: the small pools prune to a
single granule, and a filter on the date alone still prunes (8 of 57 granules)
since the index can skip inside each of the few pool values. `block_number,
log_index` at the end make the physical order deterministic and equal to chain
order inside a block, where every swap shares one timestamp. They are left out
of the PRIMARY KEY because they add nothing to pruning: the in-memory index
stays at two columns.

**Tradeoff.** A query for all pools on one day reads slightly more than with
the timestamp first (65,536 vs 49,152 rows). `block_timestamp` and
`block_number` carry the same information, so one of them is redundant in the
key; it costs nothing measurable.

**Revisit when.** There are hundreds of pools (then the first key column stops
being low-cardinality and date-only filters stop pruning), or the dominant
query stops filtering by pool.

## 12. PARTITION BY month, for management and not for speed

- Date: 2026-09-19
- Status: Accepted

**Context.** About 30 days and 860,000 rows. Options were no partitioning,
monthly or daily.

**Decision.** `PARTITION BY toYYYYMM(block_timestamp)`.

**Why.** Partitioning is a data-management unit, not a performance feature,
and the measurement agrees: with the same sorting key, monthly partitioning
**changed no read at all** (32,768 rows for the one-day query with and without
it; the partition was pruned, but the primary index had already skipped those
granules). What it gives is the ability to drop, detach or replace one month
as a unit, and it is the answer that does not have to be corrected if the
window grows from 30 days to a year (12 partitions). Daily would be one
partition per day — 43 of about 3 granules each with the data loaded today,
365 in a year — with one part per partition touched by every insert.

**Tradeoff.** One more part per month, and an insert that crosses a month
boundary creates two parts instead of one (seen in the experiment: 114 parts
instead of 113).

**Revisit when.** Retention or reloads need a finer unit than a month.

## 13. Types: lossless integers, and hashes and addresses in binary

- Date: 2026-09-19
- Status: Accepted

**Context.** Solidity types do not map one to one, and the choice decides both
correctness and most of the disk.

**Decision.** `amount0`, `amount1` `Int256`; `sqrt_price_x96` `UInt256` (uint160
on chain); `liquidity` `UInt128`; `tick` `Int32` (int24 on chain);
`block_number` `UInt64`; `log_index` `UInt32`; `block_timestamp`
`DateTime('UTC')`; `pool_address` `LowCardinality(String)`. `tx_hash` as
`FixedString(32)` and `sender`, `recipient` as `FixedString(20)`, **binary**.
Raw integers, never scaled by decimals in this table.

**Why.**

- A real swap of 1,136 WETH needs **70 bits**: `Int64` overflows on real data,
  by a factor of 123. (The largest `|amount1|` in the table today is 2,191 WETH,
  71 bits, a factor of 238.) `tick` reaches ±206,590, which does not fit `Int16`. The
  256-bit and 128-bit types round-trip through clickhouse-connect exactly, bit
  for bit, over their whole range; through `Float64` the same value loses
  55,221 wei without any error. Reconciliation needs exact equality.
- **`tx_hash` as hex text was 52.9% of the table on disk** (30.1 of 56.9 MB)
  and compressed 1.1x, because a hash is random. Binary halves the bytes of the
  single largest column. The three 256-bit columns together were 28%, and
  compress 2.0x to 4.3x. Measured afterwards on the real table, 863,587 rows:
  73.2 MB against 105.2 MB with text hashes (**-30%**, 84.8 bytes per row
  instead of 122). `tx_hash` is still the largest column: 36.8% of the 94.2 MB the table
  occupies today.
- `pool_address` stays readable text because `LowCardinality` with 4 values
  costs 2.4 KB in total.

**Tradeoff.** Hashes and addresses are unreadable in a plain `SELECT`: every
display needs `lower(hex(col))` and every filter `unhex('…')`, and any join
against an outside source that carries hex text needs the conversion. The
staging model in dbt is where that is done once. Arithmetic on 256-bit integers
is slower than on 64-bit; irrelevant at this size.

**Revisit when.** The conversions become a source of mistakes in ad-hoc
queries: then a readable alias column, not a change of storage type.

## 14. Nothing from pools.yml is denormalised into the raw table

- Date: 2026-09-19
- Status: Accepted

**Context.** Symbols, decimals, fee and label live in `pools.yml`. ClickHouse
culture is to denormalise, because joins load their right-hand side in memory
and wide tables are cheap in a columnar store.

**Decision.** The raw table carries only `pool_address`. `pools.yml` becomes a
dbt seed, and whatever needs denormalising is denormalised in the marts.

**Why.** The raw table is a faithful copy of the chain, and `pools.yml` stays
the single source for everything maintained by hand. A label is editorial: if
it were copied into 860,000 rows, fixing a typo would mean rewriting the table.
The cost of the join that this forces depends on the size of its right-hand
side, which is 4 rows.

**Tradeoff.** Every model that needs decimals or a label joins the seed. The
daily mart is where I denormalise label and fee on purpose, as the deliberate
example of the opposite choice.

**Revisit when.** The pool dimension grows to thousands of rows: then a
dictionary, or denormalising at load time.

---

## 15. The external comparison only looks at days that are whole on both sides

- Date: 2026-09-20
- Status: Accepted

**Context.** Two kinds of pool-day are not a day. On our side the backfill starts
and ends inside a day: 2026-08-20 begins at 07:10:59 UTC and showed -35.16%,
-23.84%, -22.40% and -7.60% against a source that reports the whole day. On the
source's side the newest candle is the day still in progress. The first load of
GeckoTerminal ran on 2026-09-19 at 23:12 UTC, so the 2026-09-19 candle was still
open; our data for that day ended at 22:53. USDC/WETH 0.01% showed **-2.14%**
and was listed beyond the threshold. Downloaded again on 2026-09-20, with the
day closed on both sides, the same pool-day is at **-0.55%**, inside 1%.

**Decision.** `make reconcile` compares a pool-day only if it is complete on our
side (not the first or last day of our window) and its external candle was closed
when downloaded (`date < UTC date of fetched_at`). The others are listed in their
own section with both values and the reason. `RECONCILE_DAYS=all`
(`--include-incomplete-days`) compares them too.

**Why.** A difference that disappears by waiting a day says nothing about either
source. Listing the excluded days, instead of dropping them, keeps the rule
auditable: 8 pool-days were excluded the day this was decided and 7 in the
current run; every one of them is in the report, with both values.

**Tradeoff.** The most recent day is never reconciled the day it happens. The
rule relies on `fetched_at` being stored per candle, and on the source's day
being the UTC day, which is observed and not documented (docs/EXTERNAL_SOURCE.md).

**Revisit when.** The pipeline runs continuously: then "complete on our side"
should come from the checkpoint, not from "first and last day of the window".

---

## 16. A pool-day is flagged beyond 1% AND beyond 1,000 USD

- Date: 2026-09-20
- Status: Accepted

**Context.** A relative threshold alone treats a 9 USD difference like a 900,000
USD one. wstETH/USDC 0.3% has 673 swaps in the whole window (610 when this was
first reconciled, 625 the next day) and days of
123 USD, where -9 USD is -6.75%. On 2026-09-19 one swap of 617.28 USD is 44% of
that pool's volume for the day (1,413 USD): at that size any rounding or
valuation detail of a single trade moves the day by more than 1%. Of the 24
compared pool-days beyond 1% on the day this was decided, 12 differ by less than
1,000 USD, and all 12 are
in the two wstETH pools.

**Decision.** A pool-day is flagged when it is beyond `RECONCILE_THRESHOLD`
(0.01) **and** beyond `RECONCILE_ABS_THRESHOLD` (1,000 USD). Beyond the relative
threshold only, it is listed under "below the absolute threshold" and not
flagged. Both are parameters of `make reconcile`, with those defaults. The
absolute threshold alone flags nothing.

**Why.** Attention is the scarce thing: 12 flagged pool-days that carry money
are investigated; the other 12, which add up to 2,098 USD, stay in sight in their
own section. Nothing is removed from the report or the CSV. The split holds as the
window grows: over the 43 days loaded today, 35 compared pool-days are beyond 1%
and 18 of them, 3,682 USD in total, are below the absolute threshold, all in the two
wstETH pools.

**Tradeoff.** 1,000 USD is a judgement, not a measurement, and it is the same
for a pool that trades 80 million a day and for one that trades 2,000. A small
pool can be wrong by 17% for a month and never be flagged if each day stays
under 1,000 USD; the per-pool total difference in the summary is what would show
it.

**Revisit when.** Pools of very different size are added: then the absolute
threshold should scale with the pool (for example a fraction of its median day).

---

## 17. The external check is GeckoTerminal, not the subgraph

- Date: 2026-09-20
- Status: Accepted. Supersedes the external-check half of #2

**Context.** #2 planned to reconcile against the Uniswap subgraph. When the
external check was built, the requirement was a second source that needs no API
key, so that the reconciliation can be reproduced by anyone who clones the repo.

**Decision.** Daily USD volume per pool from the public GeckoTerminal API
(`src/univ3_indexer/external.py`, docs/EXTERNAL_SOURCE.md). No subgraph code was
ever written.

**Why.** The principle of #2 stands: the check is only worth something if the two
paths are independent, and someone else's indexer is. GeckoTerminal needs no key
and serves six months of daily candles per pool in one call.

**Tradeoff.** It publishes no methodology: not the day boundary, not how a swap
is valued, not whether anything is filtered. The first was observed; the second
is what findings 7 and 9 of docs/RECONCILIATION_FINDINGS.md run into. The
subgraph would have given per-swap rows to join on, and a documented schema.

**Revisit when.** A difference has to be explained swap by swap: then a source
with per-swap rows (the subgraph, or a second indexer) is the next step.

---

## 18. Round trips are measured, not removed

- Date: 2026-09-25
- Status: Accepted

**Context.** Finding 7 of docs/RECONCILIATION_FINDINGS.md turned on swaps that the
same sender undid in the same block. Applied to the whole dataset
(docs/ROUND_TRIPS.md), the same definition covers 9.8% of all USD volume and 24.4%
of one pool's. Either the volume keeps them or it drops them.

**Decision.** Measure them and leave the volume as it is.
`fct_round_trip_legs` holds one row per swap that is a leg of a round trip, and
`fct_pool_daily_round_trips` has one row per pool-day of `fct_pool_daily`, with
`volume_usd` (gross, as in `fct_pool_daily`) and `net_volume_usd` (without the legs)
side by side. Both are MergeTree tables in `onchain_dbt`, configured like
`fct_pool_daily`. `fct_pool_daily.volume_usd` is unchanged.

**Why.** The gross figure is what an external source reports and what the
reconciliation compares; removing the legs would open a difference with every
source. The net figure is what a comparison of fees or market share needs. Keeping
both lets each question use its own figure, and the difference is the measurement.

**Tradeoff.** Two volume columns that a reader can confuse. The definition (same
pool, block and `sender`, reversal within 10%) is a choice: the pair count depends
heavily on the tolerance, the USD share much less (table in docs/ROUND_TRIPS.md).
Round trips split across pools or protocols are not seen.

**Revisit when.** A consumer needs net volume as the default, or a second source
with per-swap rows shows how it treats these swaps.

---

## 19. A read-only user limited to the marts, for readers and agents

- Date: 2026-10-10
- Status: Accepted

**Context.** There is one ClickHouse user, `indexer`, and it can create, alter and drop
anything. `AGENTS.md` says `onchain` is read-only for agents and admits that nothing
enforces it. An agent that turns questions into SQL is coming, and it will run queries
nobody has read first. No account on the server can create a user with SQL: `indexer` has
no access management, on purpose.

**Decision.** A second user, `agent_reader`, declared in
`clickhouse/users.d/agent_reader.xml`. The demo always mounts the file; the real server
mounts it only when started with `make up-reader`, so the reader is opt-in there.
`readonly = 1`. `SELECT` on five tables of the dbt database, by name, and on nothing else:
`dim_pools`, `fct_pool_daily`, `fct_pool_daily_round_trips`,
`fct_pool_daily_smart_money`, `fct_round_trip_legs`. No grant on the database, on
`stg_swaps`, on the seed, or on the raw database. Three limits: `max_execution_time`
10 s, `max_result_rows` 10,000 with `result_overflow_mode = 'throw'`,
`max_memory_usage` 500,000,000 bytes. The password hash reaches the server through
`clickhouse.env`; the password lives in a third file, `agent-reader.env`, with
variable names of its own.

**Why.** A rule the server enforces does not depend on the agent following it.
Declarative, not `CREATE USER`, because giving any account the right to create users
would give the agents' own user a way to grant itself anything. The definition is
versioned and reviewed like code, and the demo mounts the very same file, so every
refusal, the destructive ones included, is tried on a throw-away server before the real
one sees the file. Opt-in on the real server because a mounted file without its hash
stops the server from starting, and `make up` must not depend on that. Grants per table
mean a new model is invisible until somebody decides otherwise. The limits are fixed
because a query written by a model can be a full scan or a cross join, and the server
has 3 GB.

**Tradeoff.** Two ways to start the server, and the wrong one silently removes the
reader: after `make up-reader`, a plain `make up` recreates the container without it.
With the mount, the server does not start if the hash variable is missing. Changing the
user means editing a file and recreating the container. Every new mart needs a line. The
grants name `onchain_dbt` literally, so the demo had to build into that name. The reader
cannot see `stg_swaps` or the raw table, so some questions have no answer for it, and a
legitimate large result fails instead of being cut. `max_result_rows` cannot go below
the row count of `system.settings`, or clickhouse-connect cannot connect.

**Revisit when.** A reader needs swap-level rows, more than one kind of reader exists
(then one profile and several users, not copies of the grants), a mart outgrows the row
limit, the limits reject queries that should have run, or the reader becomes something
other work depends on (then the mount moves into `docker-compose.yml`).

---

## 20. The fixture carries no smart-money rows

- Date: 2026-10-11
- Status: Accepted

**Context.** The five marts are committed under `evals/fixture/` so that the evaluation
and CI run on the data the warehouse serves. One of them, `fct_pool_daily_smart_money`,
holds per pool-day figures derived from Nansen's classification of the signer. Five of
its 140 pool-days hold exactly one smart-money swap, with its USD amount to six decimals.
Until now this repository published totals per pool only.

**Decision.** The per pool-day rows of `fct_pool_daily_smart_money` are not published.
The fixture carries that table as a schema and no rows: the two header lines of its file
and its `CREATE TABLE`. The export never selects its rows, the fingerprint says rows 0
and why, and a test fails if the file ever gets a data row. The other four marts are
committed whole.

The read-only user keeps `SELECT` on `fct_pool_daily_smart_money`. On a server where that
table has rows the agent can read and return them, so the results of a run against such a
server are not published. The evaluation runs on the fixture, where the table is empty.

**Why.** The swaps are public on chain, so a pool, a day and an amount identify the
transaction, and through it the wallet Nansen classifies. Nansen's redistribution
guidelines require that published output cannot be reverse-engineered to their
classification. A total per pool over the whole period does not allow that; a pool-day
with a single swap does.

**Tradeoff.** The evaluation cannot ask anything about smart money: on the fixture the
table exists and is empty, so the honest answer to such a question is a refusal. The
fixture is no longer the warehouse table for table, and the test that compares them
checks that mart by its schema only.

**Revisit when.** The rows can be published in a form that cannot be traced back, for
example only pool-days above a minimum number of swaps and with amounts rounded, or Nansen
agrees in writing to the per pool-day figures.

---

## 21. The agent's guardrails: what the server enforces and what is code

- Date: 2026-10-11
- Status: Accepted

**Context.** `python -m agent` lets a model write SQL against the warehouse and report
an answer. Nobody reads the SQL before it runs, and nobody checks the answer before it is
printed. Some of what keeps this safe is enforced by ClickHouse whatever the code does;
the rest is code in `src/agent/`, which a bug or a later change can weaken. The two kinds
should not be confused.

**Decision.** Enforced by the server, for the user `agent_reader` (entry 19):

- it cannot write, create, alter or drop anything (`readonly = 1`);
- it can read five tables and no others (grants by name);
- it cannot change a setting, so a query stops at 10 s, at 10,000 result rows and at
  500,000,000 bytes of memory;
- it cannot read from outside the database (no grant on any source).

Enforced by code only:

- the agent connects as `agent_reader` and as nobody else, and stops when that user is
  not available;
- the SQL guard: one statement, `SELECT` only, no `SETTINGS`, `FORMAT` or `INTO OUTFILE`,
  no table function that reads outside. It gives the model a clear sentence early; every
  one of its refusals that matters is also a refusal of the server;
- at most 200 rows of a result reach the model, and the same failed SQL is not sent twice;
- at most 6 model calls per question, and at the cap the result is `no_answer`;
- a dollar budget per question, checked against the worst case before each model call,
  with a ledger; no automatic retry;
- the answer must be a cell of the last result, or it is marked `ungrounded`;
- the prompt's rules (arithmetic in SQL, refuse instead of guessing) are instructions,
  not enforcement: only the grounding check and the cap catch a model that ignores them.

**Why.** A guard that parses SQL can be wrong, and an instruction can be ignored. What
must never happen (a write, a read outside the five tables, a query that takes the
server down) is therefore the server's job, tested against a real server in `make demo`.
The code handles what the server cannot know: what the question was, what it may cost,
and whether the answer came out of the data.

**Tradeoff.** The agent cannot run where the reader does not exist, which today includes
the real server. A correct answer that is not literally a cell of the last result is
reported as ungrounded. The budget's worst case is a loose bound, so a question can be
stopped with money left. A grounded answer can still be the wrong query: grounding shows
the number came from the data, not that it answers the question. That is what the
evaluation is for.

**Revisit when.** The evaluation shows how often the model breaks a rule that only the
prompt states, the budget bound stops questions that would have fitted, or the agent
gets a tool that does more than read.

---

## 22. The judge is shown every query of the question

Written by the agent at the owner's request on 2026-10-13. The owner asked for this entry to
be written for him, for this phase only; the choice between the two options is his.

- Date: 2026-10-13
- Status: Accepted

**Context.** The judge reads the explanation that comes with an answer and says whether the
query and its result support it. It was shown the final query and the rows of its result,
and the rubric told it to judge against those. On the calibration sheet of 2026-10-12 it
called 3 of the 15 untouched explanations unfaithful
(`evals/calibration/2026-10-12_agree_model-labels.md`, rows 3, 7 and 16). Each of the three
cited something an earlier query of the same question had returned: two daily volumes
behind a difference, two weekly shares behind a change, a lookup in `dim_pools`. The
explanations were true to what the agent had seen. The judge had seen less.

**Options.**

1. The judge is given every query the agent ran for the question and every result, in
   order, with the last one marked as the final one.
2. The judge keeps the final query only, and the agent's prompt asks it to explain only
   from its last result.

**Decision.** Option 1. The fault was in what the judge was shown, not in what the agent
wrote, so the measurement is corrected and the thing measured stays untouched. This is what
was done for the grounding check when it marked right answers as ungrounded.

**What it costs.**

- A result now keeps every query that ran and the first 50 rows of each, not only of the
  last. Results files are larger.
- The judge's prompt grows with every query of the question.
- A run made before this change kept only its last result. Its explanations can be judged
  this way only from its transcripts, which are artifacts of the run and expire.

**What it does not change.** The grounding check still refuses a value taken from an
earlier turn: the value submitted has to come from the last step. The two are consistent.
The value must be in the final result; the words may describe how the agent got there.

**Not chosen.** Option 2 would have changed the agent's prompt, so the baseline would no
longer be the agent that runs, and it would have made explanations say less ("a fall of
35.05 million" without "from 85.4 to 50.4") so that the judge could stay simple.

## 23. A second provider, only when a variant names it

Written by the agent at the owner's request on 2026-10-13. The owner asked for this entry to
be written for him, for this phase only; the decision is his.

- Date: 2026-10-13
- Status: Accepted

**Context.** Every model call so far went to Anthropic, with a key held in the `agent-eval`
environment. CheaperInference is a gateway with an endpoint that speaks the same protocol
and lists some of the same models at lower prices
(<https://www.cheaperinference.com/docs> and its catalog, read on 2026-10-13). The owner
opened an account and put its key, `CHEAPERINFERENCE_API_KEY`, in the same environment.
The question a gateway raises is not only price: a request goes through a third party, to a
provider the gateway chooses, under an id that is the gateway's own.

**Decision.**

- CheaperInference may be used as a second provider, and only through a variant file that
  names it: `provider: cheaperinference`. The default is Anthropic and does not change.
  Nothing uses the gateway unless a run was started with such a variant.
- **No fallback, ever, in either direction.** A run talks to one provider. If that provider
  refuses, fails or has no funds, the question is an error and the run says so. It is
  never sent to the other one: a result that mixed two providers could not be attributed
  to either.
- A model id belongs to one provider. The gateway's ids are its own (`claude-sonnet-5.5`,
  not `claude-sonnet-5-5`), and an id is refused for the provider it is not of, before
  anything is sent.
- The key comes through `config.require_api_key("CHEAPERINFERENCE_API_KEY")` and its
  absence stops the run with a message. A workflow gives that key to the one step that
  already has the model key, and only when the run asks for that provider.
- Every results file records the provider, the model id sent, the `model` field the
  responses returned, the cost computed from the price table and the cost the gateway
  reported as billed, per question and in total.
- "The same model, cheaper" is claimed only when the response says it is the same model.
  Another version is another model and is reported as one.

**What goes through the third party.** The prompts and the results of the questions: the
system prompt, the tool definitions, the questions of the golden set, the SQL the model
writes and the rows the warehouse returns. All of it is already public in this repository:
the marts fixture holds public on-chain data, and the smart-money table is published empty
(entry 20). No key of the warehouse, no address label from a paid source and no private
data is in a prompt. The gateway's documentation says it does not store prompt or response
bodies in its own database and that the request goes to a serving provider under that
provider's terms. That is its statement, not something this project can check, and it is
the reason the rule above is about what is sent, not about what is promised.

**What the gateway does that Anthropic does not, and what is done about it.**

- By default it caches the prefix of requests that ask for no cache. The client sends
  `x-ci-prompt-cache: off` with every request, so that a request is as close as it can be
  to the one sent direct. Its documentation says this does not turn off a provider's own
  implicit caching, so cache reads may still appear; they are recorded.
- It has optional techniques that can change a request or reuse a response (minification,
  trimming, an exact-match response cache, routing a simple request to a cheaper model).
  Its documentation says they stay off unless enabled in the account. They are a setting
  of the owner's account, outside this repository. What the gateway reports about each
  call (`x-ci-techniques`, `x-ci-cache` and four more headers) is kept in the results.
- Its prices follow capacity. The price table has the catalog's price on the day it was
  read; the billed cost is what the gateway says, and the two are kept side by side.

**Consequences.** A second key lives in the environment that needs the owner's approval to
be used. A 402 from the gateway means its wallet is empty: the run stops there, and the
questions it did not ask are recorded as not asked, never as wrong.

## 24. A regression check of the agent on pull requests

Written by the agent at the owner's request on 2026-10-13. The owner asked for this entry to
be written for him, for this phase only; the decision is his.

- Date: 2026-10-13
- Status: Accepted

**Context.** An evaluation was started by hand, on `main`, after the owner's approval. A
change to the agent could be merged without anyone asking the agent a question. The
owner's original request included a check on pull requests: about 30 fixed cases, a cap on
what it spends, and a failure when the agent gets worse. The environment that holds the
model key, `agent-eval`, allows only `main`, so a pull request's job cannot use it.

**Decision.**

- **The trigger** is `pull_request`, on changes under `src/agent/**`, `src/evalkit/**`,
  `evals/**` and the prompt files (`src/agent/prompts/**`). Never `pull_request_target`,
  which would run a pull request's code with the repository's own rights. A pull request
  from a fork gets no secret: the job that asks the agent is skipped, and another job says
  why in its summary.
- **The job runs in a second environment, `agent-eval-pr`**, which has the owner as
  required reviewer, no branch restriction and its own copy of the model key. Every run
  waits for his approval. The key reaches one step, the one that asks the questions.
  `agent-eval` and `eval.yml` are not changed.
- **What a run may spend**: 0.25 USD in all, and six model calls per question, as in every
  other run. The variant `ci` lowers the ceiling per question to 0.05 USD, because the
  runner asks that a whole question's ceiling fits in what is left before it asks, and
  with the default the run would stop after its first question.
- **The cases** are 30, picked by code with a fixed seed from the three baseline runs:
  20 from templates, 5 written by hand, 5 with no answer, all of them right in all three
  runs, spread over the families of each kind, all from `dev`
  (`evals/ci_cases.json`).
- **What the job fails on**:
  - a case that was not asked, for any reason. A run that stops on its budget is a failed
    run, not a score;
  - a question that ended in an error;
  - more cases wrong than the noise allows. Six runs sent the model the baseline's text:
    the three baseline runs, right on all 30 by construction, and the three runs with the
    prompt cached, which got 2, 1 and 0 of the 30 wrong. The limit is the worst of the six
    plus one: **more than 3 wrong fails**;
  - a mean cost per question over 1.5 times the baseline's on the same 30 cases.
- **A score is never asked for twice.** The workflow runs the agent once. A run that fails
  is not run again to see whether it passes: a check that is retried until it is green
  measures patience. A new push is a new change and gets its own run.

**What the check can and cannot catch.** With the limit at 3 of 30 it catches an agent
that broke: a prompt that makes it stop refusing, a tool that returns nothing, a model
that no longer follows the format. It does not catch a small loss. The spread between
identical runs is two cases in thirty, so a change that costs one or two cases passes.
That is the price of a check that does not fail by chance, and the full evaluation with
its three runs is still what a claim about quality needs.

**What still has no barrier.** The code a pull request changes is the code that runs with
the key. A pull request can change the agent, the runner, the rule that judges the run and
the workflow file itself, and all of it runs in the job once the run is approved. Nothing
in the repository stands between a change that prints the key, or spends the budget on
something else, and the key: the approval click is the barrier, and it is only as good as
the reading that comes before it. The run cap limits what one approved run can spend
through this code, not what a leaked key could. Two more things hold today and are not
enforced: the environment allows the owner to approve his own run, and the credential the
agent sessions push with is the owner's account, so a session could approve the run of its
own pull request. Only the written rule stops it.

**Consequences.** A pull request that touches the agent or the evaluation waits for an
approval before its check runs, and costs about 0.05 USD when it does. A pull request that
touches neither does not start the check.

## 25. Airflow runs the daily pipeline, in a compose file of its own and outside the main dependencies

Written by the agent at the owner's request on 2026-10-19. The owner asked for this entry to
be written for him, for this run only; the decision is his.

- Date: 2026-10-19
- Status: Accepted

**Context.** Every step of the pipeline is a `make` target run by hand: fetch, load, dbt,
reconcile. Nothing runs them in order, retries a step that failed on the network, remembers
which day was done, or shows what failed. The owner also wants to learn Airflow by building
this (README, roadmap item 7).

**Decision.**

- **Airflow, not cron.** One DAG, `univ3_daily` (`airflow/dags/univ3_daily.py`), five
  `BashOperator` tasks in a line: `fetch_day`, `load_swaps`, `dbt_run`, `dbt_test`,
  `reconcile`. Each is one command that already exists. The loading logic and the dbt models
  are unchanged. What cron cannot do and Airflow does: a task runs only if the one before
  it succeeded; a failed task is retried (2 times, 5 minutes apart) without running the
  ones that passed; every run is tied to a day (`{{ ds }}`), so a past range is run again
  with `airflow dags backfill`; the state and the logs of each attempt are kept and shown.
  What it costs: a scheduler, an API server, a DAG processor and a Postgres to run, for five
  commands.
- **Version 3.3.2, not 2.x.** The owner asked for 2.x. The support page of the Airflow
  documentation (https://airflow.apache.org/docs/apache-airflow/stable/installation/supported-versions.html,
  read 2026-10-19) lists 2.x at 2.11.2 with status EOL, limited maintenance from
  2025-10-22 and end of life on 2026-04-22; 3.x is at 3.3.2. A new pipeline on a series
  without security fixes would be the wrong thing to learn on. The DAG is the same idea in
  both; the differences in this file are the imports (`airflow.sdk`, the standard provider)
  and that the scheduler no longer runs tasks itself: tasks report to the API server.
- **The schedule is a data interval.** `CronDataIntervalTimetable("@daily", "UTC")`, so the
  run with `ds = 2026-10-01` starts at 2026-10-02 00:00 UTC, when that day is over. Airflow
  3 reads the plain string `"@daily"` as a trigger at 00:00 of the day it names, and `ds`
  would be a day that has just begun. `catchup=False`, `max_active_runs=1`.
- **`max_active_runs=1`** because every run appends to one landing zone, which has to be a
  single range without gaps or overlaps (`landing.check_coverage`). Two days fetched at the
  same time could leave a gap, and the load would refuse it.
- **`fetch_day` needs `cli --date`.** The backfill takes `--days` or block numbers, not a
  date. `--date YYYY-MM-DD` looks up the day's first and last block on the node (a binary
  search over block timestamps, about 25 calls per end), then takes the existing
  `--from-block/--to-block` path. Two additions follow from the landing zone, not from taste:
  the plan and the checkpoint are per day (`<data dir>/days/<date>/`), because a plan fixes
  one window; and what the landing zone already has is not fetched again, because files are
  named after their block range and two windows cut at different blocks would overlap. A
  day the zone has in full is a no-op (so a backfill over the days already loaded is
  harmless); a day after a partly landed one starts at the next block; a day that would
  leave a gap is refused.
- **A compose file of its own**, `docker-compose.airflow.yml`, used with the main one, as
  `docker-compose.reader.yml` is. `docker-compose.yml` is not touched, a plain `make up` does
  not start Airflow, and the stack can be deleted without a trace in the database's file.
  It is the official file cut to LocalExecutor: no Celery, Redis, workers or triggerer.
- **Airflow is not in the main dependencies.** It pins hundreds of packages
  (https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt)
  and would be resolved together with dbt and clickhouse-connect in `uv.lock`, for a test
  that loads one file. In the image, the project has its own virtualenv from `uv.lock` and
  Airflow keeps the base image's. In CI, one job installs Airflow with the constraints file
  into a virtualenv outside the working copy and runs `tests/test_airflow_dag.py` alone;
  `make test` skips that file when Airflow is not importable.
- **Secrets.** From the environment only: `clickhouse.env` as always, and an
  `airflow.env` outside the repository (names in `airflow/airflow.env.example`) with the
  database password, Fernet key, JWT secret, the admin password and `ALCHEMY_API_KEY`
  only. The Nansen and model keys are not given to the tasks.

**What this does not do.** The `docker compose up` of this stack was not run when it was
written: the agent has no Docker. Its parts were checked as far as they can be without it
(the DAG loads in Airflow 3.3.2 and its test passes; the YAML parses; the tests of `--date`
run on a scripted chain). `fetch_day` at midnight asks for a block that is not finalized yet
(finality trails the tip by about 13 to 19 minutes), which `cli` refuses; the two retries
5 minutes apart may not be enough on the first nights. If so, the schedule should move to
00:30 or the retry delay grow: not decided here.

**Tradeoff.** Four always-on containers and a Postgres for one daily job. `BashOperator` makes
each task opaque: Airflow sees an exit code, not rows or blocks.

**Revisit when.** A step needs to pass data to the next one (TaskFlow), a second DAG appears,
or the checks should be assets with their own freshness (Dagster, roadmap item 7).

## 26. Golden set v2 is a second, harder file, and v1 stays as it is

Written by the agent at the owner's request on 2026-10-19. The owner asked for this entry to
be written for him, for this run only; the decision is his.

- Date: 2026-10-19
- Status: Accepted

**Context.** On golden set v1 (180 cases) the baseline is right in about 97% of its answers
(523 of 540 over three runs, `evals/results/2026-10-12_baseline.md`), so no change to the
agent can be measured: the refusal paragraph fixed 1 case and broke 1 of the 21 held-out
questions with no answer. Rewriting v1 would change the baseline, the regression check
(`evals/ci_cases.json`, `evals/results/ci_baseline.json`) and every earlier result.

**Decision.**

- **A second file, `evals/golden_v2.jsonl`, 240 cases, and v1 untouched.** Same fields, same
  scoring, same tolerance rules, answers computed by SQL on `evals/fixture/` in a throw-away
  `test_*` database (`make golden-v2`). `tests/test_golden_v2.py` pins the SHA-256 of v1.
  100 template cases (ten families), 60 written by hand, 80 with no answer; ids start with
  `v2-`. Hard in the ways the data allows: partial days, pool-days with no row (the answer
  is 0), the units of the fee, token0 being USDC in one pool family and wstETH in the other,
  gross against net volume, joins and two-query questions; and near misses for the questions
  with no answer (intraday, outside the window, pools and chains the data lacks, smart money,
  prices the marts do not hold, forecasts).
- **The split is 30/70, stratified by kind and family** (`evalkit.golden --dev-fraction
  0.3`; the default stays one third, so v1 regenerates byte for byte): 70 `dev`, 170 `test`,
  of which 60 `test` cases have no answer, where v1 has 21.
- **The `eval` workflow takes the golden file as an input** (`golden`, default
  `evals/golden.jsonl`), checked to be a `.jsonl` under `evals/`. The regression check on
  pull requests still asks v1.

**Why.** The first runs on v2 (`evals/results/2026-10-19_baseline_*.json`) answer right in
92.7% of the answerable cases, 148, 149 and 148 of 160, against 445 of 450 = 98.9% on v1's
answerable cases (`evals/results/2026-10-12_baseline-regrounded.md`), and the misses are concentrated: the agent refuses a pool-day without a row 25 times of
30 where the answer is 0. A set the agent can fail is the condition for measuring a change.

**Tradeoff.** v2 was designed after seeing v1's results and after reading the failure
analysis of v1, so it is aimed at known weak spots (refusal, absent rows), not at a random
sample of questions. Its numbers are for this model and this fixture only. Two of the ten
families of hand cases have six cases each, so a per-family figure is a count, not a rate.

**Revisit when.** The agent scores above 97% on v2 as well, or the fixture changes.

## 27. Questions about what the data means are answered from the documentation, by search and with citations

Written by the agent at the owner's request on 2026-10-19. The owner asked for this entry to
be written for him, for this run only; the decision is his.

- Date: 2026-10-20
- Status: Accepted

**Context.** The agent answers questions about the data with SQL. Questions about what the
data means ("what is net volume?", "why are 2026-08-09 and 2026-09-25 partial?") are not in
any table: they are in `README.md`, `DECISIONS.md` and `docs/`. The agent had no way to read
them, and nothing measured whether a search over them finds the right passage.

**Decision.**

- **Retrieval, no model.** `src/agent/docs_index.py` splits the three kinds of file at their
  headings (id `file#heading`; a section over 1,000 characters is cut at paragraph breaks and
  the pieces share the section) and ranks with BM25 in plain Python. No dependency, no
  embeddings, no service. The words of a heading count 8 times. 1,000 and 8 were the best of
  25 settings by MRR on `dev`; the margin over the next was one case of 15, so they are a
  choice and not a finding (`python -m evalkit.retrieval evals/rag_cases.jsonl --tune`).
- **The cases.** `evals/rag_cases.jsonl`: 44 questions, each with the sections that answer it
  and 2 to 4 key facts. **A model wrote the labels, not a person**, and the file says so in
  its first line. `dev` and `test` are drawn with a fixed seed (a third to `dev`). Tuning
  reads `dev` only; `test` is read once, at the end. recall@1, recall@3, recall@5 and MRR
  run in `make test` (`tests/test_docs_retrieval.py`) at no cost, and are in
  [docs/EVALS.md](docs/EVALS.md).
- **A tool behind a variant.** `search_docs(query, k)` returns the best chunks with their ids
  and text. It is offered only when a variant sets `docs_tool: true`; the baseline is exactly
  what it was (a test compares the tool list and the result). With it, `submit_answer` takes
  the type `text` and `citations`. An answer in words whose citations are not all chunks
  that `search_docs` returned in that question is `ungrounded`, as an answer that is not a
  cell of the last result is.
- **Measured by a second suite.** `python -m evalkit.rag_run` asks each case once. Correct
  means every key fact is in the answer, by a plain substring test on lower-cased text.
  Grounded means the judge, with `evals/judge_rubric_docs.md`, finds every key statement
  supported by a cited chunk. One budget: 40% to the agent, 60% to the judge.
- **A change to a workflow.** `eval.yml` gets an input `suite` (`sql`, the default, or
  `docs`) and a branch in the step that already holds the model key. Nothing else in the
  file changed, and the default run is the one it was. `evalkit.report` renders the docs
  results, so the Report step is word for word the one `eval-pr.yml` copies.

**Why.** Retrieval can be measured without a model, so it is measured first and for free;
only then is a model paid to use it. Citing chunk ids makes "where did that come from"
checkable by code before any judge is paid, the same idea as the grounding check of
decision 21. BM25 over headings is the smallest thing that can work on 5,600 lines of
Markdown, and if it is not enough the numbers will say so.

**Tradeoff.**

- The labels are one model's reading of the documents. A score against them is agreement with
  that reading. They are small: 15 `dev` cases move recall by 6.7 points per case.
- The key-fact test cannot tell a fact that is stated from one that is denied, and misses a
  fact stated in other words. The judge's rubric for documents has not been calibrated
  against a person, as the first one has not.
- The index covers `README.md`, `DECISIONS.md` and `docs/*.md` and nothing else. Some things a
  reader would ask about are written only elsewhere: that fee 500 means 0.05% is in the dbt
  column descriptions (`dbt/models/*/schema.yml`), not in a document, so the agent cannot
  find it by this tool.
- A run of the suite is one draw of a model. One run does not measure the tool.

**Revisit when.** The labels are checked by a person; `test` recall@5 is low enough that
a better ranker would matter (then try embeddings, and measure them the same way); the
questions people really ask are not in the documents (then write the documents, not the
search); or the dbt descriptions should be searchable.


## 28. A pool-day with no row is zero by default, and the dates come from the data

Written by the agent at the owner's request on 2026-10-20. The owner asked for this entry to
be written for him; the decision is his.

- Date: 2026-10-20
- Status: Accepted, **not in force**: the fifth entry's rule failed on refusal recall, so
  the default did not change (see "Outcome" at the end of this entry)

**Context.** On golden set v2 the variant `zero-day` fixed all 8 `test` cases with an answer
that the baseline got wrong, with every guard holding (fourth entry of
[EVAL_PREREGISTRATION.md](docs/EVAL_PREREGISTRATION.md), runs 39407607316, 39407618600 and
39407628909). Its paragraph (`evals/variants/zero-day.md`) writes the dates the data covers,
2026-08-09 to 2026-09-25. The Airflow DAG (decision 25) loads one more day every day, so
that text goes stale: once a day after 2026-09-25 is loaded, the agent would be told to
refuse a day that is in the data.

**Decision.**

- **The coverage is computed, not written.** `evals/warehouse.yml` says where to read it:
  the first and the last `block_date` of `fct_pool_daily`, whose keys are listed in
  `dim_pools`. `describe_schema` asks the server for them each time it is called and returns
  them as `coverage`, whatever tables were asked for. `src/agent/` still names no table: the
  names come from the YAML.
- **Partial days are not detected.** The marts hold dates, not times; the only one with the
  time of a swap, `fct_round_trip_legs`, holds a subset of the swaps. So the code cannot
  tell which day is whole.
  `coverage` says that the first and the last day may hold only part of the day, which is
  what the paragraph said, without saying which.
- **The rule is in the default prompt.** `src/agent/prompts/system.md` gets a section
  "Days with no row" with the meaning of the zero-day paragraph, written against `coverage`
  (its `table`, `first`, `last` and `keys_from`) instead of table names and dates: within the
  coverage and for a listed key, a missing row is 0; one key's first or last row is not the
  edge of the data; outside the coverage or for an unlisted key, refuse. The description of
  `describe_schema` in the tool list says it also returns the dates the data covers.
- **The default prompt changed at this commit.** Its SHA-256 went from
  `9df22d15d8e9ee4b8e6061646085ef7e917ad487e3ab7ca835ab92519ccbb39b` (the v2 baseline runs)
  to `89acfeae828e400166a35423d9682b34a275e57886f2b61ea5f7ac825ca9bca4`. Every earlier
  results file records the SHA-256 of the prompt it was asked with, so each stays valid for
  what it measured: the prompt of its day, which is no longer the default. A variant named
  `baseline` after this commit is not the `baseline` of the runs before it. `evalkit.runs`
  refuses to pool runs whose prompts differ, and `evalkit.compare` lists the prompt's
  SHA-256 among what differs between two variants.
- **What measured the change, and what checks it.** The zero-day measurement is the fourth
  pre-registration entry. The prompt text is not the one that entry froze, so the fifth
  entry checks, before any run of it, that the new default is not worse than `zero-day` on
  golden set v2, and the regression check of decision 24 runs on the pull request. If either
  fails, the default does not change.

**Why.** The paragraph fixed a real weakness, measured on cases that were not read to write
it. A rule with dates in it is right for one fixture and wrong the day after the next load;
reading the dates from the data at call time keeps the rule true as the table grows, and
costs one aggregate per call to `describe_schema`.

**Tradeoff.**

- The prompt is longer for every question, including those that never touch a missing day.
- The rule assumes that a day inside the coverage was loaded. A day the pipeline failed to
  load, inside the coverage, would be answered 0. `landing.check_coverage` keeps the landing
  zone one range without gaps, so this needs a failure that also defeats that check.
- `evals/variants/zero-day.yml` is left as it was, because its SHA-256 is part of the fourth
  entry. Run after this commit it would send the new default plus the old paragraph, which
  is not what its runs were asked; to repeat them, check out `812fc7f`.
- The coverage is one table's. The other daily mart, `fct_pool_daily_round_trips`, has its own
  rows and the rule says nothing about it, as the paragraph did not.

**Revisit when.** The data stops being one range without gaps; a mart with times makes
partial days computable; or a second daily table needs the same rule.

**Outcome.** The three runs of the fifth entry
(39415287455, 39415291174, 39415294685, at `3a9c978`) asked all 240 questions, and 142, 139
and 135 of them ended in an error: the model API refused further calls ("You have reached
your specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC"). The
rule is not applied to an incomplete set, and then the default does not change. #87 had been
merged at 11:53Z, two minutes after the runs ended and before their results were read, so
the new default reached `main`; a follow-up pull request from `main` takes the section out
of the prompt, the sentence out of the tool's description and the `coverage` block out of
`evals/warehouse.yml` (`5296cfe`), and the default prompt is again `9df22d15…`. The code
that computes the coverage stays, unused. The regression check of #87 passed (30 of 30). Reverting `5296cfe` restores the default the fifth entry
froze; its runs can be repeated only with the owner's word and after the API limit allows it.

**Outcome, completed (#90).** The owner raised the limit, and a dated note on the fifth entry,
pushed first, replaced the three runs by three with the same inputs: 39422763149,
39422770533 and 39422777052, at `5ce46f1` with the prompt `89acfeae…`, each 240 of 240 with
no error. By majority on `test`: 110 of 110 with an answer right (at least 109 needed), 0
with an answer refused (at most 2), and 54 of 60 with no answer refused, where at least 55
were needed. The rule fails on refusal recall, so the default does not change: #90 reverts
its own revert, and the prompt stays `9df22d15…`. Per run the two prompts refused the same
on average (91.1%); only the per-case majority differs, by two cases, which is within the
spread of identical runs. The rule was written before the runs and is applied as written.

## 29. Guards on a change compare per-run means, with a margin from the baseline's spread

Written by the agent at the owner's request on 2026-10-27 (Inbox #94, R13). The owner asked for
this entry to be written for him; the decision is his.

- Date: 2026-10-27
- Status: Accepted

**Context.** Two pre-registered rules failed on a one-case margin applied to counts by
majority of three runs, where the runs themselves did not differ: the `cache` runs refused
15, 17 and 16 of 21 against the baseline's 16, 19 and 17 (`docs/EVALS.md`, prompt caching),
and the coverage default refused 55, 54 and 55 of 60 against `zero-day`'s 55, 54 and 55
(decision 28, outcome). A majority turns a case that three runs split 2 to 1 into a whole
case, so two sets of runs that differ by nothing can sit on either side of a threshold.

**Decision.**

- Guards on a change compare per-run means. For each measure (right on cases with an answer,
  refusal recall, cases with an answer refused), the variant's mean over its runs may be
  worse than the baseline's mean by at most `max(1, highest minus lowest of the baseline's
  runs)` cases. Better never fails a guard.
- The margin comes from the baseline's runs alone and is written in the pre-registration,
  with its numbers, before the variant runs.
- The computation is `evalkit.means.compare` (#97); its docstring states the rule.
  `spread.guards` stays, and what it says may be reported, deciding nothing.
- **From now on only.** Decision 28 and the caching result were reached under the earlier
  rule and stay as they were decided. Applying this rule to their runs, as the tests of #97
  do, is not a result and changes neither. A question already answered is asked again only
  with new runs, under a new pre-registration (the sixth entry is the first).

**Why.** The noise between identical runs is a property of the runs, and a per-run mean
keeps it, where a majority hides it. A margin read from the baseline's spread fails on a
drop larger than what identical runs already differ by, and not on less; reading it from the
baseline alone lets it be written down before the variant exists.

**Tradeoff.**

- The spread of three runs is a rough estimate of the noise. A baseline whose three runs
  happen to agree gives a margin of 1; one whose runs happen to scatter gives a wide margin
  (3 cases of 21 for the cache's refusal recall), and a real drop smaller than that is not
  seen.
- Per case, a guard on means says nothing: a variant can break some cases and fix others
  and keep its mean. The case-by-case comparison is still reported.

**Revisit when.** A pre-registration has more than three runs a side, so the spread can be
estimated better; or a guard on means passes a change that the case-by-case comparison shows
breaking a family of cases.

## Agent corrections

Things an agent got wrong and I had to redirect, one line each, with where it was fixed.
The list is kept because the mistakes are part of the record, not in spite of it.

- 2026-09-18: The repo and the clone directory carried a company's brand name.
  Renamed to `univ3-clickhouse-indexer`; using a company's brand on a public
  repo that is not theirs is not appropriate. The seeded README title was
  replaced too.
- 2026-09-18: The agent proposed installing `python3-venv` and building on the
  system Python (3.14). Redirected to uv with a pinned interpreter, chosen only
  after checking which versions dbt-core and dbt-clickhouse support.
- 2026-09-18: The single secrets file let the unprivileged agent user read the
  API keys. Split in two before any code depended on it (entry 4).
- 2026-09-19: A `| tail` pipe in a check swallowed the exit code, so a lint
  failure passed as green and a commit went out on top of it. Fixed by an
  amend before pushing; from then on every commit was gated on `$?` from
  `make lint` and `make test` with no pipe in between.
- 2026-09-19: A pull request body claimed 247 tests when the suite had 238.
  Corrected with `gh pr edit` on PR #22, and test counts are now read from the
  run rather than written from memory.
- 2026-09-19 onwards, four times: an alias that shadows a column
  (`sum(volume_usd) AS volume_usd`, `max(fetched_at) AS fetched_at`) made
  ClickHouse substitute the alias inside another aggregate and raise
  `ILLEGAL_AGGREGATION`, and once inside a `WHERE` it silently selected no
  rows. Each occurrence was fixed where it happened; the last one is commented
  in `scripts/prove_dbt_tests_can_fail.py`, which needs
  `prefer_column_name_to_alias = 1` to work at all.
- 2026-09-20: Entry 10 and the README said `FINAL` "removed index pruning".
  The raw results never showed that: the one-day query read the whole table
  with and without `FINAL`, because the key tested there had no time in it.
  Retracted in PR #29 and measured properly with the real key in PR #32, which
  also records what is left of the argument for MergeTree.
- 2026-09-20: The reconciliation's only pass/fail query compared an unmatched
  join side with `''` and `0`, which is a comparison with NULL under
  `join_use_nulls = 1`: a day missing from the materialized view would have
  been reported as "0 differences". Fixed in PR #29 by pinning
  `SETTINGS join_use_nulls = 0` in the four outer-join queries, with a test
  that runs the check in a hostile session.
- 2026-09-20: `raw_swaps` had no reorg story beyond staying 64 blocks behind
  the tip, which the text called "finalised". It is not: the provider's
  finalised block was 93 blocks behind its tip when measured. PR #34 moved the
  window to `eth_getBlockByNumber("finalized")` with a documented fallback,
  and checked the 680 block hashes already landed against the chain.
- 2026-09-21: About 30 of the 55 dbt tests could not fail on ClickHouse
  (`not_null` on columns that are not `Nullable`, `relationships` to a table
  the model already inner-joins, `non_negative` on unsigned integers). PR #31
  replaced them with 24 that can, and added `make dbt-prove`, which breaks the
  data on purpose in throw-away databases and fails unless every test fails at
  least once.
- 2026-09-21: A findings draft called one difference "larger than every other
  difference in the project put together". It was not. Corrected to "by far the
  largest single difference" before PR #33 was opened.
- 2026-10-10: The docs and the AGENTS.md row of PR #45 said the checks ran "as
  the agent user" with "no Docker", while the session ran as root with Docker
  available. Corrected in the same pull request before it was merged.
- 2026-10-20: The three baseline runs on golden set v2 were dispatched with `max_usd` 0.66, to
  keep six runs inside the 4.00 USD of the night. The runner asks, before every question,
  whether that question's whole ceiling (0.25) still fits in what is left, so a run stops when
  it has spent more than the budget minus 0.25: all three stopped at about 0.41 USD with 29,
  30 and 35 cases not asked, all of them questions with no answer at the end of the file.
  The report says "complete" for such a run; the cases are `not_run` records. The estimate
  that led to 0.66 (0.44 to 0.58 USD per run) was right, and the reserve of 0.25 was left out
  of it. The runs are kept and labelled partial; they were not repeated, because the rules
  of the night allowed no more than six runs.

## Owner mistakes

Mine, for symmetry.

- 2026-09-20: I merged 21 stacked pull requests from the web in numerical
  order, each into its own parent branch instead of into `main`. Nothing was
  lost, but `main` ended up with only 3 of them and was missing 67 commits.
  Fixed with PR #23, a single consolidation pull request from the tip of the
  stack into `main`, after checking with `git merge-tree` that it applied
  cleanly. The lesson is in the lists above: merge a stack bottom-up and delete
  each branch so the next pull request is retargeted, or open every pull
  request against `main` from the start.
