# The evaluation: questions whose answer is computed

The agent ([AGENT.md](AGENT.md)) answers questions about the marts by writing SQL. To say
how often it is right, each question needs a right answer that does not depend on anybody's
opinion, and above all not on a model's.

So the right answer to every question here is **computed by deterministic SQL on verified
data**. A case holds a question and a reference query; the answer is whatever that query
returns on the committed fixture ([`evals/fixture/`](../evals/fixture/fingerprint.json)),
which is the marts as the warehouse served them and which the reconciliation checks against
the raw table. Nobody types an answer, and no model takes part in producing one.

## What a case is

One case per line in [`evals/golden.jsonl`](../evals/golden.jsonl):

| Field | What it holds |
|---|---|
| `id` | stable and readable, for example `t-volume-day-007` |
| `question` | in English, as a person would ask it |
| `kind` | `template` (drawn from a template), `hand` (written by hand) or `unanswerable` |
| `family` | the template family, or the category for the other kinds |
| `split` | `dev` or `test` |
| `answer_type` | `number`, `label`, `date`, `list` or `refusal` |
| `expected` | the value; a number is text, so no digit is lost; null for a refusal |
| `accepted` | other values that are also right, for a question with more than one reasonable reading |
| `unit` | what a number is in |
| `tolerance` | `{"abs": "...", "rel": "..."}`: a number passes when it is within either; null for anything that is not a number |
| `reference_sql` | the query that produces `expected`: one statement, on the marts, table names without a database |
| `notes` | why the case exists and what it is meant to catch |

## How the answers are computed

`make golden` runs [`evalkit.golden`](../src/evalkit/golden.py):

1. It collects the cases without their answers. The template cases are drawn by
   [`evals/golden_templates.py`](../evals/golden_templates.py) with a fixed seed. Drawing
   needs no server: which pools and which days exist is read from the fixture files.
2. It creates a database named `test_<random>`, loads the fixture into it, and runs every
   `reference_sql` there. **Never against the live marts**: the answers have to be the same
   for anyone who clones the repository.
3. It writes the file and drops the database, also when something fails.

A reference query has to give exactly one answer: one row of one column for a number, a
label or a date, one column for a list. `NULL`, no rows or two rows stop the generator. The
same seed and the same fixture give the same file, byte for byte; a test regenerates it and
compares.

`src/evalkit/` is generic: it names no table, column or token of this warehouse, and a
test keeps it that way. Everything that does lives under `evals/`.

## The split

Stratified by family: within each family `round(n / 3)` cases go to `dev` and the rest to
`test`, drawn with a fixed seed that depends on the family alone. With ten cases per
family that is 3 and 7: 36 `dev` and 84 `test` of the 120 template cases. `dev` is for
working on the prompt; `test` is for the number that gets reported.

## The tolerances, and why

A number passes when it is within the absolute bound **or** within the relative one.

| Kind of number | `abs` | `rel` | Why |
|---|---|---|---|
| a count | 0 | 0 | A count is an integer. One swap off is wrong |
| a sum in dollars | 0.01 | 0.001 | A cent covers rounding to two decimals. A tenth of a percent covers a sum done in floating point over many rows, and nothing else: an off-by-one day on a range moves a sum by far more |
| an amount of a token | 0 | 0.001 | A token has no cent. One unit of one token is worth a dollar and one unit of another thousands, so an absolute bound that suits the first accepts almost any number for the second. Relative only |
| a ratio, a share or a price | 0 | 0.005 | A ratio has no natural absolute scale. Half a percent accepts a price computed from rounded volumes and rejects a different definition, such as an average that is not weighted |

The second row was one row with the first until 2026-10-11, and that was a defect: three
cases (`t-token-volume-day-001`, `-002` and `-004`) expect less than 0.2 of a token, and
with a bound of 0.01 two of them accepted any number between 0 and 0.01, zero included. Now
every case whose unit is a token has no absolute bound, and a test checks it.

A case may override the defaults, and then its `notes` say why. A test holds every case to
one rule: **no absolute bound may be larger than 0.1% of the expected value**, unless the
expected value is 0 (where a relative bound accepts nothing but 0) or the `notes` of the
case explain the tolerance. Today that leaves one case at 0 and three with a reason: two
fees of a few dollars, where the cent is kept because a dollar amount given to the cent is
right, and one difference of two shares that can be close to zero.

A label is compared exactly, after trimming and case-folding. A date is compared as a
date. A list is compared element by element, in order.

## The twelve template families

Ten cases each, 120 in all. Each family has two or three wordings, and every question
states its unit.

| Family | Question | Answer |
|---|---|---|
| `volume-day` | dollar volume of one pool on one day | number, USD |
| `swaps-day` | number of swaps of one pool on one day | number, exact |
| `token-volume-day` | volume of one named token in one pool on one day | number, in that token |
| `volume-all-day` | dollar volume of all pools together on one day | number, USD |
| `volume-range` | dollar volume of one pool over a range of days | number, USD |
| `swaps-all-range` | number of swaps of all pools over a range of days | number, exact |
| `vwap-day` | volume-weighted average price of the non-stable token on one day in one pool: the stable token's volume divided by the other token's volume. The question says "volume-weighted" | number, stable per token |
| `top-pool-day` | which pool had the most swaps, or the most dollar volume, on one day, among all pools or among the fee tiers of one pair | label |
| `peak-day-range` | on which day of a range one pool had its highest dollar volume | date |
| `volume-change` | the change in dollar volume of one pool between two days, absolute or in percent; the question says which | number, USD or percent |
| `fees` | estimated fees of one pool on one day or over a range | number, USD |
| `share` | the share of a pair's volume that went through one fee tier on a day; the share of a pool's volume that is round trips; or its volume without them | number, percent or USD |

What the draws respect, checked on the fixture and by tests:

- **Complete days only**, 2026-08-10 to 2026-09-24. The first and the last day of the
  data, 2026-08-09 and 2026-09-25, hold part of a day.
- **Never a pool on a day it has no row for.** Four pool-days have none: `wstETH/USDC
  0.3%` on 2026-08-09, 2026-08-15 and 2026-09-25, and `wstETH/USDC 0.05%` on 2026-09-25. A
  range for one pool is only drawn where the pool has a row on every day of it.
- **One answer.** A question whose answer is a pool or a day is only drawn where the
  maximum is not tied.

Two independent checks on the answers themselves:

- every case of `volume-day` and `swaps-day` agrees with
  [`docs/evidence/2026-09-25/reconciliation.csv`](evidence/2026-09-25/reconciliation.csv),
  which `make reconcile` computes from the raw table, by another path;
- every reference query, run again on the fixture, returns exactly the stored answer.

## The cases written by hand

Sixty more cases come from [`evals/hand_cases.yml`](../evals/hand_cases.yml), thirty of
each kind. The file holds questions and queries, never answers: a case that carries
`expected` is refused, and the generator computes the answer of a hand case exactly as it
does for a template.

- **`hand`, thirty hard cases**, in eight categories: several steps in one question; units
  (a token, basis points, millions); a pool named the other way round from its label; gross
  against net volume; more than one reasonable reading; a list in order; a pool-day inside
  the window with no row, where the answer is 0 and a refusal is wrong; dates.
- **`unanswerable`, thirty cases with no answer**, in seven categories: a pool or pair that
  is not in the data; another chain or protocol; a date outside the data; a forecast;
  something the marts do not hold; smart money, where the table has no rows and no rows is
  not zero; and a question that sounds answerable from a column that looks right and is
  not. Their `answer_type` is `refusal`, they have no query, and their `notes` say what a
  wrong answer would look like.

For a question with more than one reasonable reading the file gives one query per reading
(`accepted_sql`). When a reading gives another value, that value goes into `accepted`; when
it gives the same value, nothing is added and the second query is the proof that the
readings agree.

## What is deliberately left out of the templates

- **Partial days and missing pool-days.** They are the interesting cases (is a missing
  row zero swaps, or no data?), and that is exactly why they are not drawn at random: they
  are written by hand, one by one.
- **Smart money.** `fct_pool_daily_smart_money` is empty in the fixture
  ([decision 20](../DECISIONS.md#20-the-fixture-carries-no-smart-money-rows)). A question
  about it has no answer here, and belongs with the questions that must be refused.
- **Questions with no answer.** A template always has one. Refusing is tested with cases
  written for it.
- **The legs table.** `fct_round_trip_legs` holds only the legs of round trips, so most
  questions that sound answerable from it are not. That is a trap to set on purpose, not
  to draw.
- **Ambiguity.** A template question has one reading. "The last week" with a partial last
  day does not.
- **Fee units.** The fee tier appears only inside a pool's label. A question that asks for
  a fee in basis points or in percent is written by hand.
- **Anything a model would have to compute outside SQL.** Every template answer is one
  query.

## Running an evaluation

```sh
PYTHONPATH=src uv run --group agent python -m evalkit.run evals/golden.jsonl \
    --variant baseline [--split dev|test|all] [--ids FILE] [--limit N] [--model ID] \
    [--repetitions N] [--max-usd 5] [--out results.json]
PYTHONPATH=src uv run --group agent python -m evalkit.run evals/golden.jsonl \
    --only-errors results.json [--max-usd 5] [--out merged.json]
PYTHONPATH=src uv run python -m evalkit.report results.json [--out report.md] [--top]
PYTHONPATH=src uv run python -m evalkit.rescore results.json [--out rescored.json]
```

[`evalkit.run`](../src/evalkit/run.py) asks the agent every selected case and writes one
results file. What it holds to:

- **It connects as the read-only user**, as `python -m agent` does, and as nobody else.
- **A variant is a file.** `--variant NAME` loads `evals/variants/NAME.yml`; a name with no
  file stops the run. See [Variants](#variants).
- **One budget for the whole run.** Before every question it checks that the question's own
  ceiling (0.25 USD by default) still fits in what is left. When it does not, the run stops
  and every case left is recorded as `not_run`. A partial run is never reported as a whole
  one: the file says how many were not asked, and the report opens with it.
- **The results file is written after every question**, and replaced in one step: it is
  written to a temporary file next to it and moved over the old one, so a reader finds the
  old file or the new one and never half of one. While the run is going the file says
  `"state": "unfinished"` and lists under `not_reached` the cases it has not got to. A job
  that is killed leaves exactly that file, and its report opens with `UNFINISHED RUN`. The
  last write sets `"state": "complete"`.
- **A question is asked once, and a request is sent again in one case only.** When the API
  answers 429 or 529 the request was not served and nothing was billed. The agent waits
  what the `retry-after` header says, at most 60 seconds, and sends the same request again,
  at most three times for one call ([AGENT.md](AGENT.md#how-a-question-ends)). Every wait
  is in the result of the question, under `waits`, and the report adds them up.
- **An error is not a wrong answer.** A question that ended because of the API or the
  network after those waits, or because the budget refused a call, has the status `error`.
  It is counted apart and is in no accuracy and no cost figure. A question that ended at
  the cap of model calls, or because the model stopped, is the model's outcome and counts
  as wrong. A run with any error says so at the top of its report, with the reasons.
- **`--only-errors RESULTS` asks again the cases that ended in error** in an earlier file,
  and only those, and writes the earlier file with those records replaced. It refuses to
  merge two different things: the golden file, the files of the variant and the system
  prompt must be what they were. The merged file keeps the run it came from and adds an
  entry under `reruns` with the new commit, what was asked again and what it cost; each
  replaced record carries the reason of the error it replaces.
- **The results file says what was run**: the commit, the model, the variant with the
  SHA-256 of its file and of every file it points at, the SHA-256 of the system prompt and
  of the golden file, the fixture's fingerprint, start and end, the budget and what was
  spent, and for every case and repetition the agent's whole result and its score.
- **The last result is in the file.** For every question, `last_result` holds the column
  names and the first 50 rows of the last query that ran: what the answer was checked
  against. The fixture is public data, so these rows can be published with the results.
- **Full transcripts stay out of the repository.** Every turn, with every row the model
  saw, is written under the data directory, `<data directory>/evals/<run>/transcripts/`,
  next to the ledger.

[`evalkit.report`](../src/evalkit/report.py) turns a results file into Markdown: tables
only, and nothing in it that is not in the file.

[`evalkit.rescore`](../src/evalkit/rescore.py) scores a results file again against the
golden file as it is now. When a case is corrected (a tolerance, an accepted reading), the
runs already paid for are not paid for again: what the agent answered is in their file, and
only the judgement of it changes. It writes a new file, never over the old one, with every
score and every figure computed again. `golden_sha256` is then the golden file it is scored
against, and `rescored` has one entry per rescoring with both hashes, the old and the new,
and the cases whose verdict changed. No model and no database take part.

## Variants

A variant says what one run changes, in one file,
[`evals/variants/<name>.yml`](../evals/variants/baseline.yml). It may set four things, all
optional:

| Key | What it changes |
|---|---|
| `model` | the model, in place of the default in the code. It needs a price in `src/agent/llm.py` |
| `schema_notes` | a file of table and column descriptions. `describe_schema` then returns them next to the names and the types, and one sentence of the system prompt says so instead of saying there are none |
| `prompt_addendum` | a file of text, appended to the system prompt after a blank line |
| `max_usd_per_question` | dollars one question may cost, in place of the limit in `evals/warehouse.yml` |

`baseline.yml` sets none of them: it is the agent as the code has it. Any other key in a
variant file is refused, so a typo cannot pass for a setting. The two paths are relative
to `evals/variants/`.

A run is pinned to the content of these files, not to their names: `variant_files` in the
results holds the SHA-256 of the variant file and of every file it points at.

`src/agent/` knows nothing of this. The loop takes an addendum and the tools take
descriptions, both as plain arguments; reading the files is
[`evalkit.variants`](../src/evalkit/variants.py). `python -m agent` passes neither.

## Running an evaluation from GitHub

The workflow [`eval`](../.github/workflows/eval.yml) runs the same command on GitHub's
runner, against the fixture, with the model key of the `agent-eval` environment. It is
started by hand and by nothing else.

1. On GitHub, open the **Actions** tab, choose the workflow **eval** on the left, and press
   **Run workflow**.
2. Leave the branch on `main` and fill in the form:
   - `variant`: the name of a file in `evals/variants/`, without `.yml`, for example
     `baseline`. Required; it goes into the results file and into its name.
   - `split`: `dev` (the default), `test` or `all`.
   - `model`: empty for the default in the code.
   - `repetitions`: how many times each case is asked, 1 unless changed.
   - `max_usd`: dollars for the whole run, 5 unless changed.
   - `limit`: only the first N cases. **For a first run, put 5 here**: it shows that the
     whole chain works for a few cents before a full run is paid for.
   - `only_errors`: empty for a normal run. With the path of a results file in the
     repository, for example `evals/results/2026-10-11_baseline_123.json`, only the cases
     that ended in error in that file are asked again, and the artifact is the merged file.
     `split`, `model`, `repetitions` and `limit` are then ignored.
3. **Approve the run** if the environment asks for it: **Review deployments**, then
   **Approve and deploy**.
4. **Read the result** on the page of the run. Under **Summary**: what was run, the headline
   metrics with their intervals, the refusal table and the costs. At the bottom of the
   page there are two artifacts. **`eval-results`** holds the whole results file and the
   whole report. **`eval-transcripts`** holds every turn of every question, with the rows
   the model saw.

The job is red only when the evaluation could not execute: no read-only user, no key, a
bad argument, or a run that took longer than the 50 minutes the step is given. A low score
is a result, not a failure, and the job is green. So is a run that stopped on its budget:
the summary then opens with `PARTIAL RUN`. A run stopped by the time limit is red, and
what it had written is still reported and uploaded: the summary opens with `UNFINISHED
RUN`.

To keep a result in the repository, for a later pull request:

```sh
scripts/fetch_eval_results.sh RUN_ID    # the number in the run's URL
```

It downloads the artifact `eval-results` with `gh` into `evals/results/`, as
`<date>_<variant>_<RUN_ID>.json` and `<date>_<variant>_<RUN_ID>.md`, never overwrites a
file, and commits nothing. The run's number is in the name because one variant is run
several times on one day. It then downloads `eval-transcripts` into the data directory, as
`<data directory>/evals/github-run-<RUN_ID>/`, which is never inside the working copy: the
transcripts are not for the repository.

**First run on 2026-10-12.** The owner started the `eval` workflow by hand on `main` at
`b6befdc`: a smoke run of five `dev` cases
([38242270322](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38242270322))
and then the baseline three times. The script above brought the three baseline runs into
`evals/results/`. A fifth run, 38244959690, stopped before asking anything because the
variant name was mistyped; it has no results and is in no figure.

### What a run costs: measured

Three runs of the baseline variant, all 180 cases, one repetition, `claude-haiku-5-5`, budget
1.50 USD each. Dollars are `spent_usd` of each results file; minutes are from `started` to
`ended` of the same file, so they leave out the runner's set-up.

| Run | Results file | Asked | Errors | Spent, USD | Time |
|---|---|---|---|---|---|
| [38242644460](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38242644460) | `evals/results/2026-10-12_baseline_38242644460.json` | 180 of 180 | 0 | 0.3085183 | 16 min 50 s |
| [38245003388](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38245003388) | `evals/results/2026-10-12_baseline_38245003388.json` | 180 of 180 | 0 | 0.3104654 | 17 min 28 s |
| [38247610883](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38247610883) | `evals/results/2026-10-12_baseline_38247610883.json` | 180 of 180 | 0 | 0.3061546 | 17 min 1 s |

Together 0.9251383 USD. No run waited for a 429 or a 529, none stopped on its budget, and
no question ended in an error. A question cost 0.00171 USD and 5.68 seconds on average over
the three runs (`evals/results/2026-10-12_baseline.md`, the report of
[`evalkit.runs`](../src/evalkit/runs.py) over the three files). The estimate this paragraph
replaces, one question of the `agent` workflow multiplied by 180, was 0.22 USD and 12
minutes: the measurement is about 0.31 USD and 17 minutes.

## The metrics

[`evalkit.score`](../src/evalkit/score.py) is deterministic and uses no model. A case that
was not run is in none of these figures, and neither is a question that ended in an error.

**Error.** A question that ended because of the API or the network, after the waits the
agent allows, or because the budget refused a call. Nothing was learned about the model, so
it is not a wrong answer: it is counted apart, with its reason and its cost, and it is in
none of the figures below. The report says how many there were before it says anything
else.

**Correct.** For a case with an answer, the submitted value equals `expected` or one of
`accepted`: within the tolerance for numbers, exactly after trimming and case-folding for
labels, as a date for dates, element by element and in order for lists. Refusing such a
case is wrong. For a case with no answer, refusing is right.

**Execution accuracy.** Correct cases over cases that have an answer.

**Valid SQL.** `run_sql` calls that ran over all `run_sql` calls; and, separately,
questions with at least one failed query.

**Refusals.** The two-by-two table: should refuse or not, did or did not. Precision is the
share of the refusals made that were due; recall is the share of the refusals due that
were made.

**Hallucination rate.** Answered when it should have refused, plus answers marked
`ungrounded`, over all cases. A value that is right and ungrounded counts in both places:
accuracy says what was answered, this says where it came from.

**Cost, tokens and seconds per question.** Mean, median and 95th percentile (by nearest
rank: the smallest value with 95% of the questions at or below it). Cost per correct
answer is the whole cost of the run over the number of correct cases.

**Intervals and breakdowns.** Every proportion is printed as `k of n = p% [low, high]`,
where the bracket is the 95% Wilson interval. With a few dozen cases the interval is wide,
and it is there so that two runs are not read as different when they are not. Every figure
is also broken down by split (`dev` and `test` apart), by kind and by family.

**Repetitions.** With `--repetitions N` every case is asked N times. The file then says,
per case, how many of the runs passed, how many cases passed every run, some runs or none,
and the spread between runs: the lowest and the highest share of correct cases among the
N runs, and their difference.

Details that the definitions above leave open, and how the scorer settles them:

- A submitted number may be JSON text or a JSON number. Anything that is not a finite
  number is wrong, not an error.
- A date is compared as a date: an ISO date, or an ISO timestamp at midnight. `22 August
  2026` is wrong.
- In a list, an element is compared as a date when both sides are dates, as a number
  (exactly) when both are numbers, and otherwise as a label.
- `no_answer` is wrong for every case, and is not a hallucination: nothing was made up.
- `error` is neither right nor wrong. With repetitions, a case that ended in an error in one
  run has one run fewer, not one failed run.
- A case with no answer that got a value counts once in the hallucination rate, even when
  that value was also ungrounded.

## The grounding check was too strict

The three baseline runs marked 33, 26 and 31 of 180 answers as ungrounded
(`evals/results/2026-10-12_baseline.md`). On `dev` that is 14, 9 and 16 of 53: 39 answers.
Every one of the 39 was a right answer, and every one of the 39 values is in a result the
model was shown. Where each was found is in
`evals/failures/2026-10-12_baseline_dev_ungrounded_<RUN_ID>.csv`, one file per run:

| Where the value was | Answers, `dev`, three runs | Still ungrounded |
|---|---|---|
| The same number as a cell of the last turn, read as a double | 20 | no |
| A cell of another query of the last turn | 15 | no |
| A cell of an earlier turn | 4 | yes |
| In no result | 0 | |

- **20 were digits lost in a JSON number.** The model sent the value as a number. A
  `Decimal(76, 18)` cell has more digits than a double holds, so `17961.320063199079530937`
  arrived as `17961.32006319908` and was not "the same cell". The transcript holds the
  value after it was read, so it cannot say whether the model wrote every digit.
- **15 were two queries sent in one turn.** The value was in one, and the check looked only
  at the one written second.
- **4 were a value read, then another query run** (a count to check the first), and the
  answer given from the first. The prompt asks for the last result, so these stay
  ungrounded.
- **None was arithmetic done outside SQL, and none was a value from nowhere.**

So the 18% was the check and not the agent, and this is a correction of the measurement,
not an improvement of the agent. The check in [`src/agent/loop.py`](../src/agent/loop.py)
now compares a number sent as a number as a double, and counts every query of the last
turn ([AGENT.md](AGENT.md#3-an-ungrounded-answer-is-kept-and-marked)). Nothing the model is
sent changed: not the prompt, not the tools.

```sh
PYTHONPATH=src uv run python -m evalkit.reground RESULTS --transcripts DIR --out FILE \
    [--causes FILE.csv]
```

[`evalkit.reground`](../src/evalkit/reground.py) applies the check as it is now to a run
already paid for, from its transcripts, and writes the results again. Right and wrong do not
change. The three baseline runs, checked again, are
`evals/results/2026-10-12_baseline-regrounded_<RUN_ID>.json`, and their report over the
three is `evals/results/2026-10-12_baseline-regrounded.md`:

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| Ungrounded answers, as first measured | 33 of 180 | 26 of 180 | 31 of 180 |
| Ungrounded answers, checked again | 4 of 180 | 3 of 180 | 3 of 180 |
| Hallucination rate, as first measured | 34 of 180 | 28 of 180 | 33 of 180 |
| Hallucination rate, checked again | 6 of 180 | 5 of 180 | 5 of 180 |
| Correct, all cases, both | 172 of 180 | 176 of 180 | 175 of 180 |

**A run of a variant made after this change is compared with the files checked again, not
with the first ones**: both then use the same check. The files as first measured stay in
the repository, untouched.

## Several runs of one variant

One run is one draw: the model does not answer the same question the same way twice. So a
variant is run several times, and the runs are read together.

```sh
PYTHONPATH=src uv run python -m evalkit.runs evals/results/A.json evals/results/B.json \
    evals/results/C.json --out evals/results/report.md
```

[`evalkit.runs`](../src/evalkit/runs.py) puts the results files side by side. For every
metric it prints each run, the mean, the lowest and the highest, and the spread between
runs, three times: over all cases, over `dev` and over `test`. Over the runs together it
adds a 95% interval that resamples cases, not answers: a case the agent gets wrong it tends
to get wrong every time, so three runs of one case are not three independent draws. It also
counts how many cases were right in every run, in some and in none. Errors are in a table
of their own and in no figure.

The files must be runs of the same thing (the same variant files, model, golden file,
system prompt, limits and cases), or nothing is written and the command says what differs.
The report names no case: it can be read without learning which `test` case failed.

## Reading the failures, on `dev` only

A change to the agent is designed from what it gets wrong. That reading is done on `dev`
and on nothing else: once a `test` case has been looked at to choose a change, its result
is no longer a test of that change.

```sh
PYTHONPATH=src uv run python -m evalkit.failures evals/results/A.json evals/results/B.json \
    evals/results/C.json --out failures.csv --unstable unstable.csv
```

[`evalkit.failures`](../src/evalkit/failures.py) writes one row for every `dev` case that
was wrong in at least two of the runs: its id, kind and family, what happened in each run,
an empty `category` and `note` to fill in by hand, and one line of evidence (the final SQL
of the first run that was wrong, or the reason it gave for refusing). Cases wrong in exactly
one run go to a second file, listed and not classified: one failure in three is as likely
to be the draw as the agent. A question that ended in an error is in neither. With the
default split, no `test` case is listed, counted or printed.

## Comparing two variants

```sh
PYTHONPATH=src uv run python -m evalkit.compare --baseline B1.json B2.json B3.json \
    --variant V1.json V2.json V3.json [--failures failures.csv] --out report.md
```

[`evalkit.compare`](../src/evalkit/compare.py) takes the runs of two variants. The number
it reports is execution accuracy on `test`, the cases the change was not designed on: each
run, the mean, the lowest and the highest, and a 95% interval for each variant; then the
difference, with an interval of its own from a paired resampling of the cases. Case by
case, by majority of the runs, it counts how many cases the change fixed, how many it broke
and how many stayed as they were. Refusals, hallucination rate, valid SQL, dollars and
seconds are printed for both. `dev` is in a table of its own, labelled as the cases the
change was designed on: a gain there is expected and is not evidence.

One sentence then says whether the difference on `test` is larger than the spread between
runs of the same variant, which is the largest gap between the best and the worst run of
either variant. When it is not larger, the sentence says so: these runs do not show that
the change did anything.

The two variants must have been run on the same golden file and the same cases, or nothing
is written. `--failures` is the classified failures of the variant on `dev`; its counts per
category are printed as they are, with the largest named.

## The judge: what code cannot check

The scorer decides whether an answer is right, and no model takes part in that. One thing
is left that code cannot read: the explanation in words that comes with every answer.
Whether those words say only what the query and its result support is a question for a
reader, and here the reader is a model. It is the only place in the evaluation where a
model judges anything, and its verdict never changes a score.

- **The rubric** is [`evals/judge_rubric.md`](../evals/judge_rubric.md), and its text is
  the judge's system prompt, word for word. One verdict, `faithful` or `unfaithful`, and one
  sentence of reason. Unfaithful: the explanation states a number, a unit, a pool, a table
  or a period that the query or its result does not support, or claims more than the query
  measured. A wrong answer can have a faithful explanation, and the rubric says so.
- **[`evalkit.judge`](../src/evalkit/judge.py)** makes one call per case. It is given the
  question, the final SQL, the rows of the last result as the results file kept them, and
  the explanation. The verdict comes back through a tool, `submit_verdict`; a response with
  no well-formed call of it is recorded as `no_verdict`, and free text is never read for a
  verdict. It has its own budget (2 USD unless changed), checked before every call, and the
  cases that do not fit are recorded as `not_judged`. Its default model is
  `claude-opus-5-5`, the strongest of the price table in `src/agent/llm.py`, because it
  reads the words of the smaller model the agent runs on.
- **The workflow [`judge`](../.github/workflows/judge.yml)** runs it on GitHub, in the image
  of `eval`: started by hand only, in the `agent-eval` environment, the key in one step. Its
  input `source` is a file already in the repository: a results file, or the calibration
  sheet. It needs no warehouse, because it runs no query.

```sh
PYTHONPATH=src uv run --group agent python -m evalkit.judge evals/results/FILE.json \
    [--model ID] [--max-usd 2] [--limit N] [--out verdicts.json]
```

### Calibration: the judge against a person

A judge is only worth what its agreement with a person is worth, so that is measured before
any verdict is used.

```sh
PYTHONPATH=src uv run python -m evalkit.calibration build evals/results/*_baseline_*.json
PYTHONPATH=src uv run python -m evalkit.calibration agree evals/calibration/sheet.csv verdicts.json
```

`build` writes [`evals/calibration/sheet.csv`](../evals/calibration/sheet.csv): thirty answered
questions, each a different case, drawn with a fixed seed and stratified by the kind of
case, from the `dev` split only. Fifteen keep the explanation the agent wrote. The other
fifteen have an explanation altered on purpose, by code and not by a model: a number
changed, the unit changed, a date moved or a name replaced, or a claim added that no query
supports. The rows are in random order, with an empty `label` column for the person, and
nothing in the sheet says which rows were altered. That is the key, a second file, which is
written under the data directory and stays out of the repository until the labels are
committed.

`agree` compares the labels with the judge's verdicts on the same sheet: percent agreement,
Cohen's kappa and the two-by-two table. A test checks the kappa against two values worked
out by hand in the test. With the key it also says how many of the altered rows each of the
two called unfaithful.

**The sheet is built and not labelled.** It was built on 2026-10-12 from the three baseline
results files, `evals/results/2026-10-12_baseline_*.json`, with the default seed: 30 rows, 15
of them altered (4 with a number changed, 8 with a date moved or a name replaced, 3 with a
claim added; none with the unit changed, because the draw gave none). Its `label` column is
empty: the owner fills it. No model has judged anything and there is no agreement figure.
Until there is one, a verdict of the judge is not a measurement, and no report in this
repository uses one.
