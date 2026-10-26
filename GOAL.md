# Goal

> **The owner writes and changes this file. An agent never edits it**, night runs
> included. If an agent thinks a criterion is wrong, unreachable or already met, it says so
> in the Night log or in its pull request, and the owner decides. This text is a draft,
> written by an agent on 2026-10-26 from the README, for the owner to rewrite.

## What the project is for

1.24 million Uniswap v3 swaps on Ethereum, loaded into ClickHouse, modelled with dbt and
verified against the chain and against an independent source; on top of them, an agent that
answers questions about the data by writing SQL, and an evaluation that measures how often it
is right, how often it refuses when the data cannot answer, and what an answer costs. It is
a learning project and a portfolio piece: every claim is backed by a file in the repository,
every change to the agent is judged by a rule written before it runs, and what went wrong is
kept where it happened.

## What "done" means for the next version

Each criterion is checkable: it names the file, test or run that shows it. A criterion is
met when the evidence exists in `main`, not when a pull request says so.

1. **The zero-day behaviour is the default.** A pool-day with no row, inside the dates the
   data covers and for a listed pool, is answered 0 by the default prompt, with the dates
   read from the data (decision 28). It is adopted by a pre-registered rule in
   `docs/EVAL_PREREGISTRATION.md` whose guards are computed from per-run means and the spread
   between runs, not from a one-case margin on per-case majorities. Evidence: the entry, its
   three complete runs in `evals/results/`, and a DECISIONS entry written by the owner.
2. **A person has labelled.** The judge's 30 calibration rows
   (`evals/calibration/sheet.csv`) and at least 20 retrieval cases are labelled by the owner,
   `sheet.labels.json` says `person`, and Cohen's kappa (judge) and the agreement with the
   model-written labels (retrieval) are reported in `docs/EVALS.md` with the file they come
   from.
3. **The agent is a small HTTP service with traces.** One endpoint asks the agent a
   question and returns the answer, the SQL and the explanation, with a trace per question.
   Its tests run in `make test` with a scripted model: no key, no network.
4. **The daily pipeline runs.** The Airflow DAG `univ3_daily` has run on the real server for
   7 consecutive days with `reconcile` green on each, and the read-only user `agent_reader`
   is in force there. Evidence: the DAG's run history and the reconciliation reports for
   those days, summarised in a dated note, and the barrier table of `AGENTS.md` updated.
5. **The front pages match the results.** Every figure in `README.md` and
   `docs/overview.html` is checked by a test against the committed results file it comes
   from (`tests/test_readme.py`, `tests/test_overview.py` or their successors).

## Out of scope for this version

Streaming ingestion, reorg handling, more chains or protocols, Postgres as system of record,
and production-scale measurements: the README's "What I would build next", items 1 to 5
and 9. A task that needs one of them is not taken without the owner's word.
