# A ten-minute walkthrough

For someone reviewing this repository with little time. What to open, in what order, and the
question each piece answers. Times are for reading, not running.

**Even shorter:** the [dashboard](https://orwee.github.io/univ3-clickhouse-indexer/) has the
whole result on one page, with a link from each chart to the document or query behind it,
and the [project overview](overview.html) says what the project is without any code
(section 10).

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
pool-days flagged; 17 of 163 after ten more days were added; 18 of 183 after five more, on
2026-09-25), and what was done about each difference?* Read finding 7: a hypothesis that was tested so that it could fail, and did, next
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
one of the 29 dbt tests failing, because a test that cannot fail checks nothing
([scripts/prove_dbt_tests_can_fail.py](../scripts/prove_dbt_tests_can_fail.py)).

## 7. The agent (2 minutes)

[docs/AGENT.md](AGENT.md), the table under "How a question ends", then "Guardrails: what the
server enforces and what is code". *Question answered: what stops an agent that writes SQL
from doing harm or from making things up?* The database refuses what must never happen: a
write, a read outside five tables, a query that runs too long. The code checks that the
answer is a cell of the last result, and an answer that is not is kept and marked
ungrounded. The loop is [src/agent/loop.py](../src/agent/loop.py), what the model is told is
[src/agent/prompts/system.md](../src/agent/prompts/system.md), and all it is told about this
warehouse is [evals/warehouse.yml](../evals/warehouse.yml).

## 8. How the agent is graded (2 minutes)

[docs/EVALS.md](EVALS.md), "How the answers are computed", then "Golden set v2: a harder test
the agent can fail". *Questions answered: how do you know how often it is right, and whether
a change made it better?* The right answer to each of the 180 questions of
[evals/golden.jsonl](../evals/golden.jsonl) is computed by a reference query on a committed
copy of the marts, never typed; 30 have no answer and must be refused. On that set the agent
was right in 445 of 450 answerable cases
([evals/results/2026-10-12_baseline-regrounded.md](../evals/results/2026-10-12_baseline-regrounded.md)),
too close to the ceiling to measure a change, so
[evals/golden_v2.jsonl](../evals/golden_v2.jsonl) has 240 harder ones, 80 of them with no
answer. Every change to the agent is judged by a rule written down before it runs:
[docs/EVAL_PREREGISTRATION.md](EVAL_PREREGISTRATION.md), one entry per change, with what
happened to it. Open one case of each golden file, then one entry. What has been measured,
and what has not, is in the section "The agent and its evaluation" of the
[README](../README.md#the-agent-and-its-evaluation).

## 9. The daily pipeline in Airflow (1 minute)

[airflow/dags/univ3_daily.py](../airflow/dags/univ3_daily.py), then
[airflow/README.md](../airflow/README.md), "Know before you run it". *Question answered: what
runs the pipeline every day, in what order, and what happens when a step fails?* Five tasks
in a line, `fetch_day`, `load_swaps`, `dbt_run`, `dbt_test` and `reconcile`, each a command
that already exists; one run at a time, because every day appends to one landing zone; at
00:30 UTC, after the day's last block is finalized; two retries, and after the last one a
comment on an issue. Why Airflow, and why this version, is
[DECISIONS.md](../DECISIONS.md) 25. The DAG has not run on a server yet
([README.md, Limitations](../README.md#limitations)).

## 10. The project overview (1 minute)

[docs/overview.html](overview.html), served at
<https://orwee.github.io/univ3-clickhouse-indexer/overview.html>. *Question answered: what is
this project, for someone who does not read code?* How the data flows in six steps, what was
built and how it scored, what did not work and what is not done yet, on one page. Every
figure on it is checked against the file it comes from by
[tests/test_overview.py](../tests/test_overview.py).

## 11. If there is time left

- The second week, in [CHANGELOG.md](../CHANGELOG.md): [docs/ROUND_TRIPS.md](ROUND_TRIPS.md)
  (how much of the volume is swaps undone in the same block, and how much that figure depends
  on its definition) and [docs/CROSS_POOL.md](CROSS_POOL.md) (the gap between two fee tiers of
  one pair, with an ASOF JOIN and what ClickHouse reads for it).
- [docs/NANSEN.md](NANSEN.md): what a Swap log cannot tell you (who signed), what 10 API
  credits bought, and the production design that was deliberately not run.
- [docs/EXTERNAL_SOURCE.md](EXTERNAL_SOURCE.md): what the external source documents, what was
  only observed, and what is unknown.
- [README.md, Limitations](../README.md#limitations): what this does not do.
- [AGENTS.md](../AGENTS.md) and "Agent corrections" at the end of
  [DECISIONS.md](../DECISIONS.md#agent-corrections): how the work was done, and where the
  coding agent had to be corrected.
