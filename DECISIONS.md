# Decisions

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
**Why.** The reasoning, in my own words.
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

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

- Date: 2026-09-19
- Status: Accepted

**Context.** The backfill ends at the block the node reports as finalised
(`eth_getBlockByNumber("finalized")`, since 2026-09-21; until then it ended 64
blocks behind the tip, which is deep but is not finality: the provider's finalised
block was 93 blocks behind its tip when this was checked). Finalised logs do not
change, so duplicates can only come from my own pipeline: the backfill runner delivers at least once. The choice
was between letting the engine clean up (ReplacingMergeTree) or making the load
idempotent and keeping a plain MergeTree.

**Decision.** `ENGINE = MergeTree`. Deduplication is not the engine's job. The
landing zone is idempotent (a batch delivered twice rewrites the same file) and
the load is made idempotent on top of it: a full load rebuilds the table, and the
incremental load compares each file's row count with what the table holds for
that block range, then skips, inserts or repairs. What this does not cover is an
INSERT retried after the server had already applied it; `make load-verify`
(duplicates, counts, coverage) is what would catch that.

**Why.** Measured on 463,447 real swaps (docs/SCHEMA_EXPERIMENTS.md):

- A ReplacingMergeTree whose sorting key is not unique per swap **lost 65.7% of
  the rows** (463,447 loaded, 159,151 kept), with no error, already at insert
  time and before any merge.
- With a correct key, and 10% of the files redelivered, the table total read
  **11.2% too high** (515,330 instead of 463,447) for as long as the merge had
  not happened and the query did not say `FINAL`. Nothing warns about it.
- `FINAL` on unmerged parts cost **3x** on the main query (69 ms vs 23 ms). (An
  earlier version of this entry added that it "removed index pruning". The raw
  results do not show that: the one-day query read the whole table with and
  without `FINAL`, because the key tested there had no time in it.)

Replacing moves the cost of a pipeline defect onto every query, forever, and
makes the sorting key serve deduplication instead of queries.

> **Correction, 2026-09-21 (agent draft, for Roberto to weigh).** The two sentences
> above do not survive a measurement with the key that was finally chosen
> (docs/SCHEMA_EXPERIMENTS.md, first section; `scripts/final_experiment.py`). That key,
> `(pool_address, block_timestamp, block_number, log_index)`, is unique per log, so it
> serves queries AND deduplication: a Replacing table with it lost no row. `FINAL` read
> exactly the same rows as the query without it, pruning intact. Its cost was 2.6x time
> and 5x memory on the whole-table aggregate while 221 parts were unmerged, 1.3x once
> merged, and nothing measurable with `do_not_merge_across_partitions_select_final = 1`;
> filtered queries paid 0 to 4 ms. The figures quoted above came from a key without
> time in it.
>
> What is left of the case for MergeTree, stated as it now stands: (1) every reader, dbt
> model included, would have to say `FINAL`, and one that forgets reads a total 10% too
> high with no error (a day of the big pool read 28,179 swaps instead of 23,961); (2) the
> materialized view is an insert trigger, so a row delivered twice is counted twice in
> `swaps_daily_agg` whatever the engine of the source table: with the view in place the
> load has to be idempotent anyway, and once it is, Replacing protects nothing more.
> Against it: with MergeTree a duplicate that does get in stays forever (988,485 rows
> before and after the merge), and the only defence is `make load-verify`.

Repeated on the full 30 days (863,587 swaps) the picture is the same: 64.4%
lost with a non-unique key, the total 10.5% too high without `FINAL`, and
`FINAL` on unmerged parts 2.8x slower (114 ms vs 41 ms).

**Tradeoff.** Nothing inside the table protects me. If the load ever inserts a
file twice, the duplicates stay until I reload. So the load verifies itself
(row count against the landing zone, zero duplicates by `(block_number,
log_index)`) and fails loudly.

**Revisit when.** The data stops being append-only (for example ingesting
blocks that can still be reorganised), or the landing zone goes away.

## 11. ORDER BY (pool_address, block_timestamp, block_number, log_index), PRIMARY KEY on the first two

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

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

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

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
window grows from 30 days to a year (12 partitions). Daily would be 30
partitions of 3 granules each today and 365 in a year, with one part per
partition touched by every insert.

**Tradeoff.** One more part per month, and an insert that crosses a month
boundary creates two parts instead of one (seen in the experiment: 114 parts
instead of 113).

**Revisit when.** Retention or reloads need a finer unit than a month.

## 13. Types: lossless integers, and hashes and addresses in binary

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

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
  by a factor of 123. `tick` reaches ±206,590, which does not fit `Int16`. The
  256-bit and 128-bit types round-trip through clickhouse-connect exactly, bit
  for bit, over their whole range; through `Float64` the same value loses
  55,221 wei without any error. Reconciliation needs exact equality.
- **`tx_hash` as hex text was 52.9% of the table on disk** (30.1 of 56.9 MB)
  and compressed 1.1x, because a hash is random. Binary halves the bytes of the
  single largest column. The three 256-bit columns together were 28%, and
  compress 2.0x to 4.3x. Measured afterwards on the real table, 863,587 rows:
  73.2 MB against 105.2 MB with text hashes (**-30%**, 84.8 bytes per row
  instead of 122). `tx_hash` is still the largest column at 35.7%.
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

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

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

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

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
auditable: 8 pool-days are excluded today and all 8 are in the report.

**Tradeoff.** The most recent day is never reconciled the day it happens. The
rule relies on `fetched_at` being stored per candle, and on the source's day
being the UTC day, which is observed and not documented (docs/EXTERNAL_SOURCE.md).

**Revisit when.** The pipeline runs continuously: then "complete on our side"
should come from the checkpoint, not from "first and last day of the window".

---

## 16. A pool-day is flagged beyond 1% AND beyond 1,000 USD

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

- Date: 2026-09-20
- Status: Accepted

**Context.** A relative threshold alone treats a 9 USD difference like a 900,000
USD one. wstETH/USDC 0.3% has 625 swaps in the whole window (610 when first reconciled) and days of
123 USD, where -9 USD is -6.75%. On 2026-09-19 one swap of 617.28 USD is 44% of
that pool's volume for the day (1,413 USD): at that size any rounding or
valuation detail of a single trade moves the day by more than 1%. Of the 24
compared pool-days beyond 1%, 12 differ by less than 1,000 USD, and all 12 are
in the two wstETH pools.

**Decision.** A pool-day is flagged when it is beyond `RECONCILE_THRESHOLD`
(0.01) **and** beyond `RECONCILE_ABS_THRESHOLD` (1,000 USD). Beyond the relative
threshold only, it is listed under "below the absolute threshold" and not
flagged. Both are parameters of `make reconcile`, with those defaults. The
absolute threshold alone flags nothing.

**Why.** Attention is the scarce thing: 12 flagged pool-days that carry money
are investigated; the other 12, which add up to 2,098 USD, stay in sight in their
own section. Nothing is removed from the report or the CSV.

**Tradeoff.** 1,000 USD is a judgement, not a measurement, and it is the same
for a pool that trades 80 million a day and for one that trades 2,000. A small
pool can be wrong by 17% for a month and never be flagged if each day stays
under 1,000 USD; the per-pool total difference in the summary is what would show
it.

**Revisit when.** Pools of very different size are added: then the absolute
threshold should scale with the pool (for example a fraction of its median day).

---

## 17. The external check is GeckoTerminal, not the subgraph

> **BORRADOR — pendiente de que Roberto la reescriba con sus palabras**

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

## Agent corrections

Things the coding agent got wrong or that I had to redirect, one line each.

- 2026-09-18: The repo and the clone directory carried a company's brand name.
  Renamed to `univ3-clickhouse-indexer`; using a company's brand on a public
  repo that is not theirs is not appropriate. The seeded README title was
  replaced too.
- 2026-09-18: The agent proposed installing `python3-venv` and building on the
  system Python (3.14). Redirected to uv with a pinned interpreter, chosen only
  after checking which versions dbt-core and dbt-clickhouse support.
- 2026-09-18: The single secrets file let the unprivileged agent user read the
  API keys. Split in two before any code depended on it (entry 4).
