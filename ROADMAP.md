# Roadmap

The tasks the night runs take, highest priority first. The rules for using this file are in
[AGENTS.md, "Night runs"](AGENTS.md#9-night-runs); what the tasks are for is
[GOAL.md](GOAL.md).

- **The owner** orders the list, edits any task, and answers `needs-decision` tasks in the
  Inbox issue.
- **An agent** changes only the `Status` line of a task, in the pull request that works on
  it, and adds tasks it discovers at the bottom, numbered after the last one, with
  `Added by` saying which pull request found it. It never reorders, deletes or rewrites a
  task, and never changes a tag.

**Tags.** `ready`: a night may take it. `needs-decision`: the owner must answer in the
Inbox first; a night never takes it, and when the answer is in, the owner changes the tag.
`needs-run`: it needs paid model runs; a night prepares it up to a pre-registration and a
pull request, and never dispatches.

**Status.** `todo`, `in progress: <pull request>`, `in review: <pull request>`,
`done: <pull request>`, or `blocked: <why>`. A task is `done` when its pull request is
merged, not when it is opened.

Each task is small enough for one night and for a review of 15 minutes. One that turns out
bigger is split: the night does the first part and adds the rest at the bottom.

---

## R01. Guards from per-run means in evalkit

- Tags: `ready`
- Status: todo
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

- Tags: `ready`
- Status: todo
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
- Status: todo (after R01 is merged)
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

- Tags: `ready`
- Status: todo
- **Why.** `docs/overview.html` is the page for readers who do not read code, and the
  dashboard (`docs/index.html`, built by `scripts/build_dashboard.py`) does not link to it.
- **Done when.** `scripts/build_dashboard.py` writes a link to `overview.html` in the
  header, a test in `tests/test_dashboard.py` checks it on the rendered output without a
  server, and the pull request says that `docs/index.html` was not regenerated: building it
  needs ClickHouse, so regenerating is the owner's step.

## R05. Airflow: the schedule after midnight finality, and an alert on failure

- Tags: `needs-decision`
- Status: todo
- **Why.** Decision 25: at 00:00 UTC the day's last block is not finalized yet (finality
  trails the tip by about 13 to 19 minutes), `cli` refuses it, and two retries 5 minutes
  apart may not be enough. Nothing tells anyone that a run failed.
- **The owner decides.** (a) Move the schedule to 00:30 UTC, or keep 00:00 with a longer
  `retry_delay`. (b) Where an alert goes (e-mail, a GitHub issue comment, a webhook) and
  whether it needs a secret. Then the task becomes `ready`: the DAG change, a test in
  `tests/test_airflow_dag.py`, and a proposed text for a DECISIONS entry.

## R06. A labelling kit for the owner

- Tags: `ready`
- Status: todo
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

## R07. Serve the agent over HTTP, with traces

- Tags: `needs-decision`
- Status: todo
- **Why.** GOAL.md, criterion 3.
- **The owner decides.** New dependencies (FastAPI and an ASGI server; OpenTelemetry's SDK
  and an exporter) need his approval (AGENTS.md, section 7), and where the traces go. Also
  whether the service may run anywhere but a test: AGENTS.md forbids an agent to start a
  server.

## R08. Dense retrieval against BM25

- Tags: `needs-decision`
- Status: todo
- **Why.** Decision 27 says to try embeddings when BM25's recall is low enough to matter, and
  to measure them the same way. `test` recall@5 is 27 of 29 on model-written labels.
- **The owner decides.** A local embedding model (a dependency, and a download) or a
  provider (a key, and a cost), and whether this is worth doing before R06 gives labels a
  person has checked.

## R09. The walkthrough covers the agent, the evaluation, Airflow and the overview

- Tags: `ready`
- Status: todo
- **Why.** `docs/WALKTHROUGH.md` was written for the pipeline. A reviewer with ten minutes
  does not find the agent, the evaluation, the Airflow DAG or `docs/overview.html` from it.
- **Done when.** Sections for those four, each with the file to open and the question it
  answers, in the walkthrough's style; every figure taken from a committed file and every
  link resolving; `make test` green, which includes the retrieval tests, since
  `docs/WALKTHROUGH.md` is indexed by `search_docs`.

## R10. The barrier rows proposed in #92, in AGENTS.md

- Tags: `ready`
- Status: done: #96
- **Why.** #92 checked the environments, the ruleset and the cloud sessions' account on
  2026-10-20 and proposed three rows; the barrier table still said the environment had no
  protection rule.
- **Done when.** The rows are in the table, dated, and say what was not checked again.

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

- Tags: `needs-decision`
- Status: todo
- Added by: #96, from the report of #92
- **Why.** #92 listed 53 remote branches whose pull requests are merged or closed.
  `feat/marts-fixture` (#48) holds `98b204a`, the smart-money rows per pool-day that
  decision 20 keeps unpublished, and the pull request's ref keeps it even if the branch is
  deleted.
- **The owner decides.** Whether to delete the branches (deleting is his, not a night's) and
  whether to ask GitHub support to purge `98b204a`.
