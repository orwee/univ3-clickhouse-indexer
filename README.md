# univ3-clickhouse-indexer

Uniswap v3 `Swap` events from an Ethereum JSON-RPC node, landed as raw JSONL, loaded into
ClickHouse, modelled with dbt, and reconciled against an independent source. 1,240,618 swaps,
4 pools, 48 days (2026-08-09 to 2026-09-25, up to the node's finalized block).

- **The pipeline agrees with itself exactly.** A recomputation from `raw_swaps` and the
  materialized view match on all 188 pool-days, in raw integer units: 0 differences.
- **It does not agree with the outside, and the gap is measured.** Of those 188 pool-days,
  183 are compared (18 differ by more than 1% *and* 1,000 USD, 19 more by over 1% but less
  than 1,000 USD) and 5 are excluded as incomplete; 2 more exist only in the external source. Each difference
  is located to a pool, a day and usually an hour; [the findings](docs/RECONCILIATION_FINDINGS.md)
  say which are explained and which are not.
- **Main limitation:** the external source publishes no methodology, so a difference can be
  located but not settled. Closing that needs a second source with per-swap rows.

**[Dashboard](https://orwee.github.io/univ3-clickhouse-indexer/)** — the whole result on one page, three minutes ·
**Run it: `make demo`** — Docker only, no API key, no network data ·
**[10-minute walkthrough](docs/WALKTHROUGH.md)** — what to open and in what order

> Built over one weekend (18–21 September 2026) as a hands-on way to learn
> ClickHouse on real on-chain data. It is tested and reconciled, but it has
> never run in production and it may contain mistakes. Issues and
> corrections are welcome.

A third source, the Nansen API, adds what a Swap log cannot carry: a classification of the
account that signed the transaction. **Smart-money data: Powered by Nansen API** — the repository publishes only
aggregates per pool and day derived from their classification, never an address, a label or a
transaction hash from their responses, following their
[redistribution guidelines](https://docs.nansen.ai/mcp/redistribution-guidelines.md). See
[docs/NANSEN.md](docs/NANSEN.md).

Every design choice is in [DECISIONS.md](DECISIONS.md) with the number that was measured for
it, and what went wrong is kept where it happened instead of being cleaned up: the double count
in [docs/MATERIALIZED_VIEW.md](docs/MATERIALIZED_VIEW.md), the measurements spoiled by a cache
in [docs/SCHEMA_EXPERIMENTS.md](docs/SCHEMA_EXPERIMENTS.md), and a dated list of every
correction in [Agent corrections](DECISIONS.md#agent-corrections). Figures above are of
2026-09-25; some documents were measured on earlier states of the same table (863,587, 881,187,
898,404 and 1,110,676 rows) and say which. What changed and when is in
[CHANGELOG.md](CHANGELOG.md); the second week added [round trips](docs/ROUND_TRIPS.md), [the
gap between two fee tiers](docs/CROSS_POOL.md) and the receipts of the largest open case.

## Architecture

```mermaid
flowchart TD
    pools["pools.yml"]
    verify["scripts/verify_pools.py"]
    rpc["src/univ3_indexer/rpc.py"]
    swap["src/univ3_indexer/swap.py"]
    backfill["src/univ3_indexer/backfill.py<br/>src/univ3_indexer/cli.py"]
    landing["src/univ3_indexer/landing.py<br/>JSONL files, one per 1,000 blocks"]
    loader["src/univ3_indexer/loader.py"]
    raw["sql/001_raw_swaps.sql<br/>raw_swaps"]
    mv["sql/mv/002_swaps_daily_mv.sql<br/>sql/mv/001_swaps_daily_agg.sql"]
    daily["sql/mv/003_swaps_daily_view.sql<br/>swaps_daily"]
    seedgen["scripts/generate_pools_seed.py"]
    seed["dbt/seeds/pools.csv"]
    stg["dbt/models/staging/stg_swaps.sql"]
    mart["dbt/models/marts/fct_pool_daily.sql"]
    ext["src/univ3_indexer/external.py"]
    exttable["sql/002_external_daily_volume.sql<br/>external_daily_volume"]
    exthourly["sql/004_external_hourly_volume.sql<br/>external_hourly_volume"]
    nansen["src/univ3_indexer/nansen.py"]
    nansentable["sql/003_nansen_smart_money_daily.sql<br/>nansen_smart_money_daily"]
    smartmart["dbt/models/marts/fct_pool_daily_smart_money.sql"]
    findings["docs/RECONCILIATION_FINDINGS.md"]
    recompute["sql/reconciliation/01_recompute_daily_raw.sql"]
    reconcile["src/univ3_indexer/reconcile.py"]
    sanity["src/univ3_indexer/sanity.py<br/>sql/sanity/"]

    verify --> pools
    pools --> backfill
    rpc --> backfill
    swap --> backfill
    backfill --> landing
    landing --> loader
    loader --> raw
    raw -- "insert trigger" --> mv
    mv --> daily
    pools --> seedgen --> seed
    raw --> stg
    seed --> stg
    stg --> mart
    ext --> exttable
    ext --> exthourly
    raw --> recompute
    recompute --> reconcile
    daily --> reconcile
    exttable --> reconcile
    exthourly -- "evidence only" --> reconcile
    reconcile --> findings
    raw -- "cross by tx_hash" --> nansen
    nansen --> nansentable
    nansentable --> smartmart
    mart --> smartmart
    raw --> sanity
```

The JSONL landing zone sits between the node and the database on purpose: the backfill
costs about 22,000 provider calls, and with the raw logs on disk ClickHouse can be dropped
and reloaded as often as the schema changes without making another call. Each file is
named after its block range, which makes a repeated delivery rewrite the same file.

## How to run it

### The demo: Docker only, no API key

```
make demo
```

Runs the whole pipeline on the 242 real Swap logs committed as test fixtures, inside a
throw-away ClickHouse: land, create the materialized view, load and verify, reload twice,
`dbt build` (seed, models and every dbt test), internal reconciliation. About a minute once the images are
pulled. It removes its containers, network and volumes when it ends, and returns a
non-zero exit code if any step does not hold.

### The full path

Requirements: Docker with the compose plugin, [uv](https://docs.astral.sh/uv/), `make`.
uv downloads Python 3.12 by itself.

| Step | Command | Needs an API key? |
|---|---|---|
| Secrets files, outside the repo (names in `.env.example`) | by hand | |
| Start ClickHouse | `make up` | no |
| Check pool addresses on chain | `scripts/verify_pools.py` | **Alchemy** |
| Backfill Swap logs to the landing zone | `PYTHONPATH=src uv run python -m univ3_indexer.cli --days 30` | **Alchemy** |
| Load the landing zone, idempotent, self-verifying | `make load` | no |
| Create and backfill the materialized view, once | `make mv-setup` | no |
| Sanity queries, report in `reports/sanity.md` | `make sanity` | no |
| dbt: seed, staging, marts, tests | `make dbt-build` | no |
| Show that every dbt test can fail (breaks data in throw-away databases) | `make dbt-prove` | no |
| Daily volume from the external source | `make fetch-external` | no (public API) |
| Hourly candles, to see in which hours a day differs (optional) | `make fetch-external-hourly` | no (public API) |
| Reconcile, reports in `reports/` | `make reconcile` | no |
| Smart-money trades, 1 credit per page, cached outside the repo (optional) | `PYTHONPATH=src uv run python -m univ3_indexer.nansen --fetch-tgm USDC --from … --to …` | **Nansen** |
| Cross them with `raw_swaps`, store the aggregate (optional) | `PYTHONPATH=src uv run python -m univ3_indexer.nansen --daily USDC --from … --to …` | no |
| Tests and lint | `make test`, `make lint` | no |

`make reconcile` compares only days that are complete on our side and closed on the
source's, and flags a pool-day beyond 1% **and** 1,000 USD; both thresholds and the day rule
are parameters (`RECONCILE_THRESHOLD`, `RECONCILE_ABS_THRESHOLD`, `RECONCILE_DAYS=all`). Its
exit code reflects the internal check only. `make load` reads the landing zone from the same
data directory the backfill writes to; when the two run as different users, pass
`LANDING=/path/to/landing`. Without a Nansen key nothing breaks: the aggregate table is
created empty and its mart builds with no rows.

`make test` needs neither the network nor a key. Tests that need ClickHouse skip with an
explicit reason when the server is not reachable.

ClickHouse listens on `127.0.0.1` only (8123 HTTP, 9000 native). `make ch-client` opens a
SQL shell; `make down` stops the server and keeps the data in a named volume.

### Backfill

```
PYTHONPATH=src uv run python -m univ3_indexer.cli --days 30 --dry-run    # the plan, nothing fetched
tmux new-session -d -s backfill \
  'PYTHONPATH=src .venv/bin/python -m univ3_indexer.cli --days 30 --rps 5 \
     --log-file /var/lib/univ3-indexer/backfill.log'
tail -f /var/lib/univ3-indexer/backfill.log
```

The provider's free tier accepts `eth_getLogs` over at most 10 blocks: 21,600 calls for 30
days, about 72 minutes at 5 calls per second. Data and checkpoint live outside the repo
(`/var/lib/univ3-indexer` as root, `~/.local/share/univ3-indexer` otherwise, or
`UNIV3_DATA_DIR`). Stop it with Ctrl-C; run the same command to resume: the block window
is fixed in `plan.json` on the first run, and the checkpoint only ever points at files that
are completely on disk. Exit codes: `0` done, `2` arguments, `3` the provider rejected the
request (not retried), `4` network, `5` too many retries (aborted to protect the quota),
`130` interrupted.

## Design decisions

One or two sentences each; the reasoning is in [DECISIONS.md](DECISIONS.md).

| Decision | In short | Measured |
|---|---|---|
| Local Docker, not ClickHouse Cloud [#1](DECISIONS.md#1-local-docker-instead-of-the-clickhouse-cloud-trial) | To watch the real MergeTree engine; one command to reproduce. | |
| RPC as the source, another source only to check [#2](DECISIONS.md#2-rpc-as-the-raw-source-the-subgraph-only-as-an-external-check) | Reconciling against what you ingested from proves nothing. | 10-block limit on `eth_getLogs`: 11 blocks is an HTTP 400, [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) |
| Plain JSON-RPC, no web3.py [#3](DECISIONS.md#3-plain-json-rpc-over-requests-not-web3py) | Two methods; chunking, retries and signed int256 decoding under my control. | Decoding checked against protocol invariants on real logs |
| Two secrets files [#4](DECISIONS.md#4-two-secrets-files-split-by-who-is-allowed-to-read-them) | Unattended processes get database access without being able to read the API keys. | |
| Pinned ClickHouse 26.3 LTS, Python 3.12 [#5](DECISIONS.md#5-pinned-versions-clickhouse-263-lts-and-python-312) | Same behaviour next month. | |
| Hard 3 GiB memory limit, no swap [#6](DECISIONS.md#6-a-hard-3-gib-memory-limit-with-no-swap-and-what-clickhouse-does-with-it) | A database that swaps gets slow in a way that is hard to attribute. | ClickHouse derives 2.70 GiB from the cgroup |
| `dbt-adapters==1.24.5` [#7](DECISIONS.md#7-dbt-adapters-must-be-pinned-to-1245-when-dbt-is-added) | The only version dbt-core 1.12 and dbt-clickhouse 1.10.3 both accept. | |
| Pool addresses verified on chain [#8](DECISIONS.md#8-pool-addresses-come-from-orwee-and-are-trusted-only-after-on-chain-checks), fourth pool derived from the factory [#9](DECISIONS.md#9-a-fourth-pool-derived-from-the-factory-instead-of-typed) | An address is trusted after `factory()` and `getPool()` agree, never typed from memory. | 4 of 4 pools valid |
| MergeTree; deduplication belongs to the load [#10](DECISIONS.md#10-engine-mergetree-with-deduplication-left-to-the-load) | Not for the cost of `FINAL`: with the real key it kept pruning intact. Because every reader would have to remember it, and because the materialized view counts a redelivered row twice whatever the engine, so the load has to be idempotent anyway. | Unmerged and without `FINAL`, a Replacing table read a total 10.0% high and one pool-day 28,179 swaps instead of 23,961; `FINAL` read the same rows either way and cost 116 ms against 45 unmerged, 51 against 39 merged. Accepted cost: a duplicate in a MergeTree stays (988,485 rows before and after the merge). [docs/SCHEMA_EXPERIMENTS.md](docs/SCHEMA_EXPERIMENTS.md) |
| `ORDER BY (pool_address, block_timestamp, block_number, log_index)` [#11](DECISIONS.md#11-order-by-pool_address-block_timestamp-block_number-log_index-primary-key-on-the-first-two) | Chosen for filtered queries; the whole-table aggregate is a full scan with any key. | One pool, one day: 32,768 rows read against 634,211 with a key that lacks the time |
| Monthly partitions [#12](DECISIONS.md#12-partition-by-month-for-management-and-not-for-speed) | A management unit, not a speed feature. | No read changed with or without it |
| Int256 / UInt256 / UInt128, hashes in binary [#13](DECISIONS.md#13-types-lossless-integers-and-hashes-and-addresses-in-binary) | Lossless, and the largest column halved. | A real 1,136 WETH swap needs 70 bits; binary hashes made the table 30% smaller (84.8 bytes per row) |
| Only whole, closed days are compared [#15](DECISIONS.md#15-the-external-comparison-only-looks-at-days-that-are-whole-on-both-sides) | A difference that disappears by waiting a day says nothing about either source. | A candle compared while open read -2.14%; closed, -0.55% |
| Flagged means beyond 1% and beyond 1,000 USD [#16](DECISIONS.md#16-a-pool-day-is-flagged-beyond-1-and-beyond-1000-usd) | In a thin pool a percentage alone does not discriminate. | One 617 USD swap is 44% of a day; on the day it was decided, 12 of the 24 pool-days beyond 1% added up to 2,098 USD (today 18 of 35, 3,682 USD) |
| GeckoTerminal, not the subgraph, as the external check [#17](DECISIONS.md#17-the-external-check-is-geckoterminal-not-the-subgraph) | A source anyone can query without a key; it publishes no methodology. | |
| Nothing denormalised into the raw table [#14](DECISIONS.md#14-nothing-from-poolsyml-is-denormalised-into-the-raw-table) | `pools.yml` stays the single source; the daily mart denormalises on purpose, as the counter-example. | |

Two more things that were measured and are worth reading:
[docs/MATERIALIZED_VIEW.md](docs/MATERIALIZED_VIEW.md) (a view created over 863,587
existing rows had an empty target; 17,600 later rows reached it through the trigger alone)
and [docs/QUERY_PERFORMANCE.md](docs/QUERY_PERFORMANCE.md) (the same 50,000 rows in one
insert took 0.14 s and in a thousand inserts 74.6 s, with 491 merges rewriting the data 92
times).

## How this was built

A written brief with explicit non-goals, options measured before choosing, the decision
written down, implementation by agents, verification, and a human merge. One branch and one
pull request per block of work.

```mermaid
flowchart LR
    brief["Brief<br/>goals and non-goals"]
    measure["Options measured<br/>docs/SCHEMA_EXPERIMENTS.md"]
    decide["Decision written<br/>DECISIONS.md"]
    build["Claude Code agents<br/>unattended, 1 branch + 1 PR per block"]
    verify["Verification<br/>tests, lint, make demo, adversarial review"]
    merge["Owner merges the PR"]
    record["Corrections recorded<br/>DECISIONS.md"]

    brief --> measure --> decide --> build --> verify --> merge
    verify -- "something is wrong" --> record --> build
```

**Rigour.** A decision is only written down once a number from this repository supports it, and
when a measurement later contradicted one, the entry was corrected in place and the retraction
kept (entry 10 is the clearest case). Tests are held to the same standard: `make dbt-prove`
breaks the data on purpose in throw-away databases and fails unless each of the 29 dbt tests
fails at least once, because about 30 of the previous 55 could not fail at all on ClickHouse.
`make demo` runs the whole pipeline from a clean clone with no API key. An independent review
pass, given only the repository and no history, found 14 objective errors and 10 claims the
repo did not support; all of them are fixed and listed. The central hypothesis was
[pre-registered](docs/H2_PREREGISTRATION.md) before the hold-out data was fetched, then
evaluated out of sample and against a placebo — and the result, which weakened it on one
criterion, is reported as it came out. What is not explained is labelled UNEXPLAINED.

**Systems.** The agents run as a separate system user that cannot read the secrets directory
and is not in the `docker` group. Their GitHub token is scoped to these repositories and is
granted per session by the owner, who can withdraw it; they never hold it directly. A ruleset
on `main` is the barrier that matters, because local hooks are a convention an agent could
skip with one flag, not a barrier — [AGENTS.md](AGENTS.md) ends with a table saying, rule by
rule, which is which, and it is honest about the ones that have no barrier at all.

**Numbers of the process.** 42 pull requests merged, none by an agent. 422 Python tests and 29
dbt tests, each of the latter demonstrated capable of failing. 33,256 provider calls for the
whole backfill (10 blocks per call is the free tier's limit). 10 Nansen credits spent of 100,
with a hard budget check before every call and no retries.

> Drafted with AI assistance from the measurements in this repo and checked by an independent review pass. Design decisions were proposed with AI assistance, tested by measurement and approved by Roberto. Where an agent got something wrong it is in
> [Agent corrections](DECISIONS.md#agent-corrections); where the owner did, in
> [Owner mistakes](DECISIONS.md#owner-mistakes).

## Reconciliation findings

Three runs, each kept as a snapshot:

| Run | Swaps | Pool-days compared | Flagged | Used for |
|---|---|---|---|---|
| [2026-09-20](docs/evidence/2026-09-20/reconciliation.md) | 898,404 | 120 | 12 | every finding below, whose text quotes this run |
| [2026-09-21](docs/evidence/2026-09-21/README.md) | 1,110,676 | 163 | 17 | the out-of-sample test of finding 7 |
| [2026-09-25](docs/evidence/2026-09-25/README.md) | 1,240,618 | 183 | 18 | the current state; none of the pool-days compared before changed |

Each finding was made on the run of 2026-09-20 (898,404 swaps, 128 pool-days on both sides,
120 compared) and quotes it, so that the number in the text is the number that produced the
conclusion; where a later run changes the picture, the finding says so, dated. The full text, each figure linked to the evidence
behind it, is [docs/RECONCILIATION_FINDINGS.md](docs/RECONCILIATION_FINDINGS.md).

| # | Finding | State |
|---|---|---|
| [1](docs/RECONCILIATION_FINDINGS.md#1-the-pipeline-agrees-with-itself-exactly--explained) | `raw_swaps` and the materialized view agree exactly: 0 differences on the 128 pool-days of that run, and on the 188 of the current one | EXPLAINED |
| [2](docs/RECONCILIATION_FINDINGS.md#2-partial-days-and-open-candles--explained) | Partial days (-22% to -35% on 2026-08-20) and a candle compared while still open (-2.14%, then -0.55%). Only whole, closed days are compared, and the excluded ones are listed with their reason | EXPLAINED |
| [3](docs/RECONCILIATION_FINDINGS.md#3-the-day-boundary-is-not-the-cause--explained-a-negative-result) | The day boundary is not the cause: the distance is smallest at a shift of 0 h in all four pools; one hour either way gives 1.8% to 13% in three of them | EXPLAINED |
| [4](docs/RECONCILIATION_FINDINGS.md#4-which-leg-is-valued-does-not-matter-in-the-liquid-pools--explained) | Which leg is valued changes the liquid pools by -0.004% and +0.02%. It does not test whether USDC was worth 1 USD | EXPLAINED |
| [5](docs/RECONCILIATION_FINDINGS.md#5-in-the-liquid-pools-the-30-day-totals-agree-and-the-daily-noise-is-centred--explained) | Liquid pools: 30-day totals at +0.10% and +0.24%; daily noise 15 up / 15 down in one, 19 / 11 in the other | EXPLAINED |
| [6](docs/RECONCILIATION_FINDINGS.md#6-2026-08-27-two-pools-of-the-same-pair-off-in-opposite-directions--partly-explained) | 2026-08-27: the two USDC/WETH pools at -1.65% and +1.35%, the pair at +0.16%. Not a misattribution: the two differences sit in different hours, and one of them is unexplained | PARTLY EXPLAINED |
| [7](docs/RECONCILIATION_FINDINGS.md#7-round-trips-inside-one-block-valued-differently--partly-explained) | Same-block round trips valued differently: brings 6 of 10 hold-out days beyond 1% inside, but its pre-registered correlation falls from +0.72 to +0.05; a placebo brings 0 of 24; the largest gap is not explained by it | PARTLY EXPLAINED |
| [8](docs/RECONCILIATION_FINDINGS.md#8-2026-08-29-three-pools-high-on-a-quiet-saturday--partly-explained) | 2026-08-29: three pools high on a quiet Saturday. Not one effect: one pool is covered by finding 7, one is 18 USD, one stays at +1.44% | PARTLY EXPLAINED |
| [9](docs/RECONCILIATION_FINDINGS.md#9-days-on-which-the-source-reports-more-than-the-chain--partly-explained) | Days on which the source reports more than the chain (-2.04%, -1.27%): +0.02% and -0.02% under the valuation reading, 85% of each in one hour. The source publishes no methodology | PARTLY EXPLAINED |
| [10](docs/RECONCILIATION_FINDINGS.md#10-in-thin-pools-a-percentage-alone-does-not-discriminate--explained) | In thin pools a percentage does not discriminate: one 617 USD swap is 44% of a day. Flagging needs 1% and 1,000 USD | EXPLAINED |

Still open: eight pool-days (four found in sample, four in the hold-out), most of them
located to one to three hours, listed at the end of the draft.

## Limitations

- **One protocol, one chain.** Uniswap v3 on Ethereum mainnet, four pools.
- **No reorg handling, by staying out of their reach.** A backfill ends at the block the
  node reports as finalised (`eth_getBlockByNumber("finalized")`); if the provider does not
  know that tag it falls back to 64 blocks behind the tip and says in the log and in
  `plan.json` that the window is not finalised. It never revisits a block. The data loaded
  before 2026-09-21 was fetched with the 64-block rule; on that day
  `scripts/verify_landing_is_canonical.py` compared the block hash kept in the landing zone
  with the chain for 680 blocks (the end of every file and the last 100 blocks of every
  window) and all of them matched. `raw_swaps` has no `block_hash` and no
  `tx_index`; the landing zone keeps the whole raw log, so both can be recovered without
  calling the provider again.
- **No `tx.from` in `raw_swaps`.** A Swap log carries `sender` and `recipient`, which are mostly
  routers. The account that signed was read only for the 820 transactions of the largest open
  case, from receipts kept outside the repository
  ([findings](docs/RECONCILIATION_FINDINGS.md#what-is-still-open)), and Nansen classifies it
  for the transactions it returns ([docs/NANSEN.md](docs/NANSEN.md)).
- **A stablecoin is taken at exactly 1 USD**, and a pool without one gets `volume_usd = NULL`.
  Nothing in the pipeline checks the first assumption, although the external source's
  `close_usd` for USDC/WETH 0.01% is a USDC price and is stored (0.9990 to 1.0008 over the
  window): it is never read.
- **One external source, with no published methodology.** Finding 7 is a reading that fits the
  numbers, not a fact about GeckoTerminal.
- **Batch backfill.** No continuous ingestion, no orchestration, no alerting: `make` targets
  run by hand.
- **"`onchain` is read-only for agents" is a rule without a barrier**: there is one ClickHouse
  user and it can drop anything.
- **Weekend scale.** 1,240,618 rows. What [DECISIONS.md](DECISIONS.md) and
  [docs/QUERY_PERFORMANCE.md](docs/QUERY_PERFORMANCE.md) conclude about `ORDER BY`,
  partitions, projections and indexes was measured at 863,587 to 1,110,676 rows, before the
  last five days were added.
- **Nansen on the free tier.** Labels for the main counterparties exist only as a design.

## What I would build next

This is a batch pipeline on one chain, at weekend scale. What it is missing, in the order I
would build it.

**Status on 2026-09-25:** none of the nine is built yet. The second week went into depth on
the data rather than into infrastructure: more days up to the finalized block, round trips
([docs/ROUND_TRIPS.md](docs/ROUND_TRIPS.md)), the gap between two fee tiers
([docs/CROSS_POOL.md](docs/CROSS_POOL.md)) and the receipts of the largest open case; see
[CHANGELOG.md](CHANGELOG.md).

1. **Streaming ingestion.** A tailing ingester at the finalized head
   ([`safe_head`](src/univ3_indexer/cli.py) already resolves it) writing to Kafka or
   Redpanda, consumed by ClickHouse through the Kafka engine and a materialized view, with
   the raw landing kept in object storage for replay. The natural key
   `(block_number, log_index)` already makes a reload idempotent, so a replay is safe.
2. **Reorgs at the tip.** Keep `block_hash` in the raw table (the landing zone already
   carries it, which is how the 680 landed hashes were checked against the chain), hold
   unfinalized blocks in a provisional zone, and rewrite a block range when a parent hash
   stops matching.
3. **Multi-chain and more protocols.** `chain` first in the sorting key, and a decoder
   registry keyed by event signature instead of the single `Swap` decoder in
   [`swap.py`](src/univ3_indexer/swap.py).
4. **Postgres as the system of record** for pools, tokens and labels, served to ClickHouse
   through a dictionary with a PostgreSQL source, replacing the hand-kept
   [`pools.yml`](pools.yml) and its generated seed.
5. **Labels.** Counterparty labels from the Nansen API behind a dictionary, refreshed in
   batches ([docs/NANSEN.md](docs/NANSEN.md) has the design and the credit arithmetic), and
   the point-in-time question stated explicitly: a label is current, a swap is historical,
   and joining them silently answers "who is this wallet today", not "what was it then".
6. **Data quality as a running service.** The reconciliation scheduled daily instead of run
   by hand, freshness and volume checks against their own history rather than fixed
   thresholds, alerting on the result, and a second external source with per-swap rows to
   close the [open findings](docs/RECONCILIATION_FINDINGS.md#what-is-still-open).
7. **Orchestration and CI.** An orchestrator with asset checks (Dagster or Airflow) in place
   of `make` targets run by hand, and CI running lint, tests and `make demo` on every pull
   request.
8. **Access.** A read-only ClickHouse user for readers and agents; today there is one user
   and it can drop anything, which [AGENTS.md](AGENTS.md) admits is a rule without a barrier.
9. **Scale.** Redo the measurements at production size, where the answers may change, and
   move cold partitions to object storage with a TTL.

**What I would do first at production scale:** streaming ingestion, because a daily batch
cannot answer "what happened in the last five minutes"; reorg handling, because streaming at
the tip without it silently serves wrong numbers; and multi-chain, because the sorting key is
the one decision that is expensive to change once the table is large.

## Where things are

| Path | What |
|---|---|
| [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) | Ten minutes: what to open, in what order, and the question each piece answers |
| [DECISIONS.md](DECISIONS.md) | Why things are the way they are, and what each choice cost |
| [pools.yml](pools.yml) | The only source of pool addresses, each verified on chain |
| [sql/](sql/001_raw_swaps.sql) | Plain SQL: tables, the materialized view, sanity, reconciliation, examples |
| [dbt/](dbt/dbt_project.yml) | Seed, `stg_swaps`, `dim_pools`, `fct_pool_daily`, `fct_pool_daily_smart_money`, tests |
| [docs/RECONCILIATION_FINDINGS.md](docs/RECONCILIATION_FINDINGS.md) | The ten findings of the reconciliation, each marked explained, partly explained or unexplained |
| [docs/evidence/2026-09-20/](docs/evidence/2026-09-20/reconciliation_evidence.md) | Snapshot of one run: report, evidence (12 sections of numbers) and the per-day CSV |
| [docs/H2_PREREGISTRATION.md](docs/H2_PREREGISTRATION.md) | What was going to be tested out of sample, committed before the data was fetched |
| [docs/evidence/2026-09-21/](docs/evidence/2026-09-21/README.md) | Snapshot of the run with ten more days: the out-of-sample test and placebo, and the reconciliation over 43 days |
| [docs/evidence/2026-09-25/](docs/evidence/2026-09-25/README.md) | Snapshot of the run with five more days, up to the finalized block: reconciliation over 48 days, the analysis report, the receipts of the largest open case |
| [docs/ROUND_TRIPS.md](docs/ROUND_TRIPS.md) | How much of the volume is swaps undone in the same block by the same sender, and how much that depends on the definition |
| [docs/CROSS_POOL.md](docs/CROSS_POOL.md) | The price gap between the two USDC/WETH fee tiers, with ASOF JOIN: how wide, how long, who crosses first, and what ClickHouse reads |
| [CHANGELOG.md](CHANGELOG.md) | What changed, by date |
| [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) | The provider's limits and the size of the data, measured |
| [docs/SCHEMA_EXPERIMENTS.md](docs/SCHEMA_EXPERIMENTS.md) | Candidate schemas measured on the real data, before the decision |
| [docs/MATERIALIZED_VIEW.md](docs/MATERIALIZED_VIEW.md) | A materialized view is an insert trigger: procedure and observations |
| [docs/EXTERNAL_SOURCE.md](docs/EXTERNAL_SOURCE.md) | The external source: documented, observed, unknown |
| [docs/NANSEN.md](docs/NANSEN.md) | What Nansen adds to a Swap log (the signer and its classification), what runs on the free tier with the credits spent, and the production design that was not run |
| [docs/QUERY_PERFORMANCE.md](docs/QUERY_PERFORMANCE.md) | Projection, bloom filter, one insert against a thousand |

## About the author

Roberto Fajardo Duro, data engineer based in Madrid, statistician by training. Data scientist
at a Spanish bank, validating credit risk models. Co-founder of Orwee, a DeFi analytics
platform covering liquidity pools, positions and opportunities across chains, where he built
the data pipelines and is now a technical adviser. Previously a data analyst at a crypto fund
investing in DeFi.

Why this repository: preparing for a Senior Data Engineer role on an on-chain analytics team
whose stack is ClickHouse, dbt, Python and Postgres. He had not run ClickHouse in production,
and building something real against live chain data was the way to close that gap.

[robertofajardoduro.com](https://robertofajardoduro.com) · [github.com/robertofd31](https://github.com/robertofd31)

## License

[MIT](LICENSE).
