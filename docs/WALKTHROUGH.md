# A ten-minute walkthrough

For someone reviewing this repository with little time. What to open, in what order, and the
question each piece answers. Times are for reading, not running.

**Even shorter:** the [dashboard](https://orwee.github.io/univ3-clickhouse-indexer/) has the
whole result on one page, with a link from each chart to the document or query behind it.

## 0. Run it while you read (1 minute of typing, no API key)

```
make demo
```

Starts a disposable ClickHouse, lands the 242 real Swap logs of the test fixtures, creates the
materialized view on the empty table, loads and verifies, loads twice more to show that
nothing changes, builds the dbt project with all its tests, reconciles internally and prints
a mart. It ends with
`DEMO OK` and leaves nothing behind. [scripts/demo.py](../scripts/demo.py) is the whole thing.

## 1. What it is and how the pieces connect (2 minutes)

[README.md](../README.md): the diagram, then the table under "Design decisions". *Question
answered: what does this pipeline do, and where does each stage live?*

## 2. Why the table looks the way it does (2 minutes)

[sql/001_raw_swaps.sql](../sql/001_raw_swaps.sql), 31 lines, then
[DECISIONS.md](../DECISIONS.md) entries 10 to 13. *Questions answered: why MergeTree and not
ReplacingMergeTree; why `ORDER BY (pool_address, block_timestamp, …)`; why partitions are for
management and not for speed; why 256-bit integers and binary hashes.* Every one of those has
a number measured on the real data; the measurements are in
[docs/SCHEMA_EXPERIMENTS.md](SCHEMA_EXPERIMENTS.md) and
[docs/QUERY_PERFORMANCE.md](QUERY_PERFORMANCE.md).

## 3. How data gets in without being counted twice (1 minute)

[src/univ3_indexer/landing.py](../src/univ3_indexer/landing.py) and the docstring of
[src/univ3_indexer/loader.py](../src/univ3_indexer/loader.py). *Question answered: the
provider delivers at least once and ClickHouse does not deduplicate; where does idempotency
live?* In files named by block range, written atomically, and a loader that compares each
file with what the table holds for that range: skip, insert or repair.

## 4. The materialized view, and the mistake it invites (1 minute)

[docs/MATERIALIZED_VIEW.md](MATERIALIZED_VIEW.md), first screen. *Question answered: what
does a ClickHouse materialized view actually do?* It is an insert trigger. Created over
863,587 existing rows, it held zero. The page lists six ways to get it wrong, each with the
test that pins it.

## 5. The centrepiece: reconciliation (3 minutes)

[docs/RECONCILIATION_FINDINGS.md](RECONCILIATION_FINDINGS.md). *Questions answered: does the
pipeline agree with itself (exactly), does it agree with an independent source (12 of 120
pool-days flagged; 17 of 163 after ten more days were added), and what was done about each
difference?* Read finding 7: a hypothesis that was tested so that it could fail, and did, next
to one that fits, which was then tested again on days it had not been fitted on, with the
protocol committed first ([docs/H2_PREREGISTRATION.md](H2_PREREGISTRATION.md)); the result is
mixed and is reported as such. The numbers behind every sentence are in
[docs/evidence/2026-09-20/](evidence/2026-09-20/reconciliation_evidence.md) and
[docs/evidence/2026-09-21/](evidence/2026-09-21/README.md);
the rules of what gets compared and flagged are [DECISIONS.md](../DECISIONS.md) 15 and 16;
the code is [src/univ3_indexer/reconcile.py](../src/univ3_indexer/reconcile.py) and
[sql/reconciliation/](../sql/reconciliation/03_external_b.sql).

## 6. The modelling layer (1 minute)

[dbt/models/staging/stg_swaps.sql](../dbt/models/staging/stg_swaps.sql) and
[dbt/models/marts/fct_pool_daily.sql](../dbt/models/marts/fct_pool_daily.sql). *Questions
answered: how does a raw Int256 become an exact decimal amount, and where is the single place
that says what counts as a dollar?* (`stablecoin_symbols` in
[dbt/dbt_project.yml](../dbt/dbt_project.yml).) The singular tests in
[dbt/tests/](../dbt/tests/assert_mart_accounts_for_every_raw_swap.sql) are worth a glance, and
so is `make dbt-prove`: it breaks the data on purpose in throw-away databases and shows every
one of the 24 dbt tests failing, because a test that cannot fail checks nothing
([scripts/prove_dbt_tests_can_fail.py](../scripts/prove_dbt_tests_can_fail.py)).

## 7. If there is time left

- [docs/NANSEN.md](NANSEN.md): what a Swap log cannot tell you (who signed), what 9 API
  credits bought, and the production design that was deliberately not run.
- [docs/EXTERNAL_SOURCE.md](EXTERNAL_SOURCE.md): what the external source documents, what was
  only observed, and what is unknown.
- [README.md, Limitations](../README.md#limitations): what this does not do.
- [AGENTS.md](../AGENTS.md) and "Agent corrections" at the end of
  [DECISIONS.md](../DECISIONS.md#agent-corrections): how the work was done, and where the
  coding agent had to be corrected.
