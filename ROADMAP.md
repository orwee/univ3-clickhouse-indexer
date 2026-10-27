# Roadmap

The tasks the night runs take, highest priority first. The rules for using this file are in
[AGENTS.md, "Night runs"](AGENTS.md#9-night-runs); what the tasks are for is
[GOAL.md](GOAL.md).

- **The owner** orders the list, edits any task, and answers `needs-decision` and
  `proposed` tasks in the Inbox issue (#94).
- **An agent** changes a task's tag, status and notes only as section 9 of AGENTS.md says
  ("Keeping the roadmap alive"), always in a pull request, and adds tasks at the bottom,
  numbered after the last one, with `Added by` linking the pull request that found them.
  It never reorders, deletes or rewrites a task.

**Tags.**

- `ready`: a night may take it.
- `needs-decision`: the owner must answer in the Inbox first; a night never takes it.
- `needs-run`: it needs paid model runs; a night prepares it up to a pre-registration and a
  pull request, and never dispatches.
- `proposed`: proposed by a night when no `ready` task was left; a night never takes it
  until the owner makes it `ready` in the Inbox.
- `done`: finished. The night marks its task `done` in its own pull request, so the mark
  reaches `main` with the merge; if the owner closes that pull request without merging,
  the next night puts the task back to `ready` with a note.

**Status.** `todo`, `done: <link to the pull request>`, or `blocked: <why>`, and any
number of `Note:` lines under it.

A night takes up to four `ready` tasks in order, each done completely, up to its
done-when, in one pull request that the owner reviews the next day and merges before the
next night's work. One that cannot be finished in one night is split: the night finishes a
part that stands on its own and adds the rest at the bottom. A pull request waiting for the
owner's paid runs is labelled `waiting-runs` and does not hold the nights back (AGENTS.md,
section 9).

---

## R01. Guards from per-run means in evalkit

- Tags: `done`
- Status: done: https://github.com/orwee/univ3-clickhouse-indexer/pull/97
- Note: the task says the coverage default refused 55, 54 and 55 of 60 "against `zero-day`'s
  55, 55, 55". The committed `zero-day` files give 55, 54 and 55 as well
  (`evals/results/2026-10-20_zero-day.md`; `DECISIONS.md` decision 28 says the same), so the
  two sides are equal per run.
- **Why.** Two rules failed on a one-case margin applied to per-case majorities, where the
  runs themselves did not differ. The `cache` runs sent the model the baseline's text and
  refused 15, 17 and 16 of 21 against the baseline's 16, 19 and 17, and failed a guard of
  "at least 16 by majority" (`docs/EVALS.md`, prompt caching). The coverage default refused
  55, 54 and 55 of 60 per run against `zero-day`'s 55, 55 and 55, a mean of 91.1% each, and
  failed "at least 55 by majority" with 54 (decision 28, outcome). A guard that compares
  per-run means, with a margin read from the spread between identical runs, would not have
  flagged either, and would still catch a real drop.
- **Done when.**
  - A function in `src/evalkit/` (next to `spread.guards`, which stays as it is) takes the
    baseline's and the variant's results files and returns, per measure (right on cases with
    an answer, refusal recall, cases with an answer refused): each run's count, the mean of
    each side, the spread of each side, the margin, and whether the guard holds. The margin
    rule is stated in its docstring.
  - Tests with small synthetic files, plus one test that reads the committed results files
    of the `cache` and coverage-default comparisons and prints what the new rule says. It
    asserts what the function returns, not what anyone would like it to say.
  - `src/evalkit/` still names no table, column or token (the existing test).
  - The pull request description carries the text of a proposed DECISIONS entry for the
    owner. It does not edit `DECISIONS.md`, and it does not reopen decisions 28 or the
    caching result: rules already applied stay applied.
  - Touching `src/evalkit/` starts the regression check (`eval-pr`), which waits for the
    owner's approval. That is not part of done.

## R02. Which questions with no answer still get a number, on golden set v2

- Tags: `done`
- Status: done: https://github.com/orwee/univ3-clickhouse-indexer/pull/98
- **Why.** The README's "Still open": refusals are the weak spot. On `test`, 4 cases with no
  answer were wrong by majority under `zero-day` (2 forecasts, 1 other source, 1 other
  chain), and the coverage default refused 54 of 60. Nobody has looked at them by family.
- **Done when.**
  - A report under `evals/failures/`, written by `evalkit.failures --refusals` (or a small
    addition to it) on the stored v2 runs (baseline, `zero-day`, coverage default): on
    `dev`, each case with no answer that got a value, with its family and how it ended; on
    `test`, **counts by family only, computed by code**: no `test` question, answer or
    transcript is read (`docs/EVALS.md`, "Reading the failures, on `dev` only").
  - A draft pre-registration for one change aimed at the `dev` failures, in the pull
    request description and **not** in `docs/EVAL_PREREGISTRATION.md`: the change, the
    metric, the guards (from R01 if merged), the rule, and the runs it would need. Nothing
    is run.

## R03. Re-test the coverage-based default with the new guards

- Tags: `needs-run`
- Status: blocked: waiting for the owner's three runs on https://github.com/orwee/univ3-clickhouse-indexer/pull/100 (`waiting-runs`)
- Note: the owner decided on 2026-10-27: #100 is not merged before the runs are fetched and
  the rule is applied on it; the reference stays `zero-day`, as the sixth entry says.
- Note: prepared on 2026-10-27 at the owner's request (Inbox #94): the sixth entry and the
  prompt change are in https://github.com/orwee/univ3-clickhouse-indexer/pull/100; nothing dispatched. The three runs are the owner's, and the
  rule is applied on that pull request once they are fetched.
- **Why.** GOAL.md, criterion 1. The coverage default fixed every pool-day with no row and
  failed only on a one-case margin that R01 replaces.
- **Done when.**
  - A sixth entry in `docs/EVAL_PREREGISTRATION.md`, pushed before any run: the default as
    the fifth entry froze it (prompt `89acfeae…`, the text `5296cfe` took out; decision 28),
    the guards of R01 with their numbers filled in from the stored runs, the rule, and the
    three runs to dispatch (golden v2, split `all`, repetitions 1, `max_usd` 1.00).
  - A pull request with the entry and the prompt change, its description listing what the
    owner has to dispatch and approve. The night dispatches nothing. The regression check
    waits for the owner.

## R04. A link from the dashboard's header to the project overview

- Tags: `done`
- Status: done: https://github.com/orwee/univ3-clickhouse-indexer/pull/103
- **Why.** `docs/overview.html` is the page for readers who do not read code, and the
  dashboard (`docs/index.html`, built by `scripts/build_dashboard.py`) does not link to it.
- **Done when.** `scripts/build_dashboard.py` writes a link to `overview.html` in the
  header, a test in `tests/test_dashboard.py` checks it on the rendered output without a
  server, and the pull request says that `docs/index.html` was not regenerated: building it
  needs ClickHouse, so regenerating is the owner's step.

## R05. Airflow: the schedule after midnight finality, and an alert on failure

- Tags: `done`
- Status: done: https://github.com/orwee/univ3-clickhouse-indexer/pull/103
- **Why.** Decision 25: at 00:00 UTC the day's last block is not finalized yet (finality
  trails the tip by about 13 to 19 minutes), `cli` refuses it, and two retries 5 minutes
  apart may not be enough. Nothing tells anyone that a run failed.
- **The owner decides.** (a) Move the schedule to 00:30 UTC, or keep 00:00 with a longer
  `retry_delay`. (b) Where an alert goes (e-mail, a GitHub issue comment, a webhook) and
  whether it needs a secret. Then the task becomes `ready`: the DAG change, a test in
  `tests/test_airflow_dag.py`, and a proposed text for a DECISIONS entry.
- Note: (a) answered on 2026-10-27 in the Inbox (#94): 00:30 UTC.
- Note: (b) decided by the owner on 2026-10-27: an `on_failure_callback` posts a comment on
  the GitHub issue "Pipeline alerts" (#101) of this repository. The token is a
  fine-grained token with write access to this repository's issues only, read from the
  environment (`GITHUB_ALERT_TOKEN`, from the owner's env file passed to the Airflow
  containers; never committed, never printed). Without it the callback logs that no alert
  was sent and does not fail the task. The issue number comes from the environment too
  (`GITHUB_ALERT_ISSUE`). The test uses a fake HTTP client: no network, no token.

## R06. A labelling kit for the owner

- Tags: `done`
- Status: done: https://github.com/orwee/univ3-clickhouse-indexer/pull/103
- **Why.** GOAL.md, criterion 2. No person has labelled anything. The judge's sheet
  (`evals/calibration/sheet.csv`) has a `label` column that a model filled, and the
  retrieval cases (`evals/rag_cases.jsonl`) were labelled by a model.
- **Done when.**
  - A script writes one CSV for the owner, under the data directory and not in the working
    copy: the 30 judge rows with an empty label column, and 20 retrieval cases drawn with a
    fixed seed from `dev` and `test`, each with the question, the sections the model chose
    and their text, and empty columns for the owner's verdict. Nothing in it shows the
    model's labels or which judge rows were altered.
  - A short guide (`evals/calibration/LABELLING.md`) says what each column means and how to
    decide, in a few minutes per row.
  - The script that, once the CSV is filled and committed, computes the judge's kappa
    (reusing `evalkit.calibration agree`) and the retrieval agreement with the model's
    labels. Tested on a synthetic filled CSV. Nothing is labelled by the agent.
  - The guide says that the "altered rows caught" figure is **computed by the owner on his
    server**, because it needs the key, `<data dir>/calibration/key.json`, which never
    leaves that machine; a night cannot compute it. Once the owner's labels are in
    `evals/calibration/sheet.csv` and `sheet.labels.json` says `person`, as the user who
    built the sheet (so that `config.data_dir()` resolves to the same directory), from the
    working copy:

    ```sh
    PYTHONPATH=src uv run python -m evalkit.calibration agree \
        evals/calibration/sheet.csv \
        evals/calibration/2026-10-13_judge-verdicts_38434632537.json \
        --key "$(PYTHONPATH=src uv run python -c 'from univ3_indexer import config; print(config.data_dir())')/calibration/key.json" \
        > evals/calibration/YYYY-MM-DD_agree_person-labels.md
    ```

    `--key` has no default in `agree`, so it is given explicitly. The verdicts file is the
    judge's latest run on this sheet, shown every query (decision 22).

## R07. Serve the agent over HTTP, with traces

- Tags: `ready`
- Status: todo
- **Why.** GOAL.md, criterion 3.
- **The owner decides.** New dependencies (FastAPI and an ASGI server; OpenTelemetry's SDK
  and an exporter) need his approval (AGENTS.md, section 7), and where the traces go. Also
  whether the service may run anywhere but a test: AGENTS.md forbids an agent to start a
  server.
- Note: decided by the owner on 2026-10-27. Approved dependencies: `fastapi` and `uvicorn`
  (main), `opentelemetry-api` and `opentelemetry-sdk` (main), `httpx` (dev, for FastAPI's
  `TestClient`); no other. Traces go to a JSON Lines file under `config.data_dir()`, through
  a small exporter in this repository: no collector, no external backend. The service runs
  only inside tests (`TestClient`, scripted model, no key, no network); the owner starts it
  himself, and `README.md` gives him the command. One endpoint, `POST /ask`, returns the
  answer, the SQL, the explanation and the trace id. Split if it does not fit one night: the
  service with its tests first, the traces second.

## R08. Dense retrieval against BM25

- Tags: `needs-decision`
- Status: todo
- **Why.** Decision 27 says to try embeddings when BM25's recall is low enough to matter, and
  to measure them the same way. `test` recall@5 is 27 of 29 on model-written labels.
- **The owner decides.** A local embedding model (a dependency, and a download) or a
  provider (a key, and a cost), and whether this is worth doing before R06 gives labels a
  person has checked.
- Note: the owner decided on 2026-10-27 to wait for R06's labels; it stays `needs-decision`.

## R09. The walkthrough covers the agent, the evaluation, Airflow and the overview

- Tags: `done`
- Status: done: https://github.com/orwee/univ3-clickhouse-indexer/pull/103
- **Why.** `docs/WALKTHROUGH.md` was written for the pipeline. A reviewer with ten minutes
  does not find the agent, the evaluation, the Airflow DAG or `docs/overview.html` from it.
- **Done when.** Sections for those four, each with the file to open and the question it
  answers, in the walkthrough's style; every figure taken from a committed file and every
  link resolving; `make test` green, which includes the retrieval tests, since
  `docs/WALKTHROUGH.md` is indexed by `search_docs`.

## R10. The barrier rows proposed in #92, in AGENTS.md

- Tags: `done`
- Status: done: #96
- **Why.** #92 checked the environments, the ruleset and the cloud sessions' account on
  2026-10-20 and proposed three rows; the barrier table still said the environment had no
  protection rule.
- **Done when.** The rows are in the table, dated, and say what was not checked again.
- Note: #96 also records that `main` now requires one approving review (the owner's
  statement, and what #93 and #96 show), which #92 had found at 0.

---

## Added by the night runs

## R11. A golden-set test that counts every `test_*` database on the server

- Tags: `ready`
- Status: todo
- Added by: #96, from the report of #92
- **Why.** #92 reports that `tests/test_golden*.py::test_regenerating_gives_the_same_bytes`
  failed twice while another session ran `make test` on the same server: the test counts
  every `test_*` database, so another run's databases change the count.
- **Done when.** The test checks only the databases its own run created (for example by
  name, or by comparing the set before and after), with a test that would have failed the
  old way; it still skips with its reason when no server is reachable.

## R12. Stale branches, and the commit #48 still holds

- Tags: `done`
- Status: done: by the owner on 2026-10-20, outside a pull request
- Note: the owner deleted the 53 branches and `feat/marts-fixture` on 2026-10-20, and the
  cached ref of #48 is with GitHub Support (his statement; the request cannot be seen from
  here). Checked on 2026-10-26 with `git ls-remote --heads origin`: `main`,
  `chore/night-loop` (#96) and `docs/overview` (#93, merged on 2026-10-26); none of the 53
  and no `feat/marts-fixture`.
- Added by: #96, from the report of #92
- **Why.** #92 listed 53 remote branches whose pull requests are merged or closed.
  `feat/marts-fixture` (#48) holds `98b204a`, the smart-money rows per pool-day that
  decision 20 keeps unpublished, and the pull request's ref keeps it even if the branch is
  deleted.
- **The owner decides.** Whether to delete the branches (deleting is his, not a night's) and
  whether to ask GitHub support to purge `98b204a`.

## R13. Adopt the per-run-means guards: the DECISIONS entry and the pre-registration rule

- Tags: `done`
- Status: done: decision 29 in `DECISIONS.md`, written at the owner's request on 2026-10-27
  from the text proposed in #100, under the exception added to AGENTS.md section 2 the same day
- Note: the owner adopted the rule on 2026-10-27 in the Inbox (#94), from now on only, and
  asked the agent to write the entry. Section 2 does not let an agent add one, so the text is
  proposed in the description of https://github.com/orwee/univ3-clickhouse-indexer/pull/100
  for the owner to paste. The sixth pre-registration entry (R03) already uses the rule.
- Added by: https://github.com/orwee/univ3-clickhouse-indexer/pull/97
- **Why.** R01 adds `evalkit.means` but adopts nothing: rules already applied stay applied
  (decisions 28 and the caching result). Whether the next pre-registration uses its rule, and
  with which margin (`max(1, spread of the baseline's runs)`), is the owner's.
- **The owner decides.** The text proposed in the description of https://github.com/orwee/univ3-clickhouse-indexer/pull/97, or another. Then
  R03 can use it.

## R14. Pre-register a refusal paragraph for other sources and other protocol versions

- Tags: `needs-run`
- Status: blocked: waits for R03's result (#100)
- Note: the owner said yes on 2026-10-27 in the Inbox (#94): the paragraph drafted in #98's
  description, with the per-run-means guards of R13. Tag changed to `needs-run` in https://github.com/orwee/univ3-clickhouse-indexer/pull/100.
- Added by: https://github.com/orwee/univ3-clickhouse-indexer/pull/98
- **Why.** On `dev`, `v2-u-other-sources-004` (what Dune showed) is answered with the
  warehouse's figure in all runs of all three variants, and `v2-u-other-chain-005` (Uniswap v4)
  in most; the draft is in the description of #98 (R02).
- **The owner decides.** Whether to pre-register it, and whether the guards use the per-run
  means of R01 (#97, R13). Then the task becomes `needs-run`: the entry in
  `docs/EVAL_PREREGISTRATION.md` and the prompt paragraph, in one pull request, nothing
  dispatched.
- Note: the owner decided on 2026-10-27 that R14's entry waits for R03's result, so that its
  baseline is whichever default wins. Status `blocked` until #100 is merged or closed.

## R15. The coverage default leaves `other-pool` questions without an answer at the 6-call cap

- Tags: `needs-decision`
- Status: todo
- Added by: https://github.com/orwee/univ3-clickhouse-indexer/pull/100, at the owner's request in the Inbox (#94)
- **Why.** In R02 (#98), on `dev`, the coverage default (fifth entry's runs) ended
  `v2-u-other-pool-005` without an answer in 2 of 3 runs and `v2-u-other-pool-003` in 1 of 3,
  each after 6 model calls (`iteration_cap`), spending them on SQL that lists the pools
  (`evals/failures/2026-10-27_coverage-default_v2_dev.csv`, `..._dev_unstable.csv`). Under
  the baseline both were refused in all 3 runs; under `zero-day`, 005 ended once without an
  answer (`..._dev_refusals.csv` of each variant). On `test`, counts only: `other-pool` runs
  not refused were 4 of 18 under the baseline, 0 under `zero-day` and 2 under the coverage
  default (`*_test_family_counts.csv`).
- **The owner decides.** Raise the cap of model calls for that variant (a change to the
  agent, measured by its own pre-registration, which costs runs), or accept it as it is.
  Also whether to wait for the sixth entry's runs (R03), which will show whether it happens
  again.
