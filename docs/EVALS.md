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
  against. `queries` holds the same for every query that ran, in order, the last of them
  being that one: what the judge is shown. The fixture is public data, so these rows can be
  published with the results.
- **Full transcripts stay out of the repository.** Every turn, with every row the model
  saw, is written under the data directory, `<data directory>/evals/<run>/transcripts/`,
  next to the ledger.
  Each turn of the model also lists `block_types`: the type of every block it returned, in
  order. The content kept is the text and the tool calls; a reasoning block is named there
  and its content is not kept.

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
[`evals/variants/<name>.yml`](../evals/variants/baseline.yml). It may set six things, all
optional:

| Key | What it changes |
|---|---|
| `model` | the model, in place of the default in the code. It needs a price in `src/agent/llm.py` |
| `schema_notes` | a file of table and column descriptions. `describe_schema` then returns them next to the names and the types, and one sentence of the system prompt says so instead of saying there are none |
| `prompt_addendum` | a file of text, appended to the system prompt after a blank line |
| `max_usd_per_question` | dollars one question may cost, in place of the limit in `evals/warehouse.yml` |
| `provider` | where the requests go: `anthropic`, the default, or `cheaperinference`. A provider is used only when a variant names it, a run talks to that one and to no other, and `model` is then that provider's own id ([decision 23](../DECISIONS.md#23-a-second-provider-only-when-a-variant-names-it)) |
| `prompt_cache` | `true` sends the tool definitions and the system prompt as a cached prefix. The model is sent the same text; the input is billed differently. Off unless set |

`baseline.yml` sets none of them: it is the agent as the code has it. Any other key in a
variant file is refused, so a typo cannot pass for a setting. The two paths are relative
to `evals/variants/`.

With `prompt_cache`, the budget check before each call prices its input as a cache write,
which is the dearest it can be billed at. Whether caching lowers the cost of a run has not
been measured: the rule it will be judged by is the second entry of
[EVAL_PREREGISTRATION.md](EVAL_PREREGISTRATION.md).

With a provider other than the default, the results record what that provider itself
reported: `served_models` (the `model` field of the responses), `billed_usd` per question
and in total, and under `reports` the headers it sent about each call. `usd` and
`spent_usd` stay what they always were, the cost computed from the price table in
`src/agent/llm.py`, so the two can be set side by side. A response of status 402 means the
provider's wallet is empty: the run stops, and what it did not ask is recorded as not run.

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

With `--refusals FILE` it also writes every case of the split that has no answer, missed
or not: how each run ended and in how many model calls, in how many runs it was not
refused, and whether it was refused by majority. A case missed in one run of three is the
draw; a case missed in all three is a failure.

**The baseline, read on 2026-10-12**:
[evals/failures/2026-10-12_baseline_dev.md](../evals/failures/2026-10-12_baseline_dev.md).
No `dev` case is wrong in two runs of three, and one is wrong in one: a question with no
answer that used its six model calls without answering. The change that follows from it, and
the rule it will be judged by, were written before any run of it:
[EVAL_PREREGISTRATION.md](EVAL_PREREGISTRATION.md).

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

The cases with no answer have a table of their own, on `test` and on `dev`: how many each
variant refused by majority of its runs, with a 95% Wilson interval, and over all runs how
many answers ended without an answer and how many gave a value where a refusal was due.
The case-by-case table has a row for them too: fixed, broke, stayed.

### The one change measured: `refuse-early`, no measurable difference

Three runs of the variant on `main` at `5caae398c7147032adf61ba890f544430e6cea92`, which has
the corrected grounding check. Each results file records the two variant files with the
SHA-256 written in [EVAL_PREREGISTRATION.md](EVAL_PREREGISTRATION.md) before they ran.

| Run | Results file | Asked | Errors | Spent, USD | Time |
|---|---|---|---|---|---|
| [38255611726](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38255611726) | `evals/results/2026-10-12_refuse-early_38255611726.json` | 180 of 180 | 0 | 0.3133477 | 16 min 52 s |
| [38255631966](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38255631966) | `evals/results/2026-10-12_refuse-early_38255631966.json` | 180 of 180 | 0 | 0.3203692 | 17 min 3 s |
| [38255651233](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38255651233) | `evals/results/2026-10-12_refuse-early_38255651233.json` | 180 of 180 | 0 | 0.3179268 | 16 min 48 s |

Together 0.9516437 USD. These are all the runs of the variant that were dispatched; none is
left out. They are compared with the three baseline files checked again for grounding, in
`evals/results/2026-10-12_baseline_vs_refuse-early.md`.

**The rule, applied.** On the 21 `test` cases with no answer, by majority of three runs:

| | Baseline | `refuse-early` |
|---|---|---|
| Refused by majority | 17 of 21 = 81.0% [60.0%, 92.3%] | 17 of 21 = 81.0% [60.0%, 92.3%] |
| Fixed / broke | | 1 / 1 |
| Answers that ended without an answer, three runs | 4 of 63 | 5 of 63 |
| Answers that gave a value where a refusal was due, three runs | 7 of 63 | 6 of 63 |

Fixed minus broke is 0. The page said beforehand that -1, 0 or 1 is **no measurable
difference**, and that is the result. Both guards hold, on the 106 `test` cases that have an
answer: 105 are right by majority in both, none fixed and none broken; and 1 is refused by
majority in both (counted from the six results files with `evalkit.runs.majority`; the
report does not print that figure).

**What else the runs say, deciding nothing.**

- The change did what it was written for on `dev` and not on `test`. Answers to a question
  with no answer that used all six model calls went from 7 of 27 to 3 of 27 on `dev`
  (`evals/failures/2026-10-12_baseline_dev_refusals.csv` and
  `evals/failures/2026-10-12_refuse-early_dev_refusals.csv`), and from 10 of 63 to 13 of 63
  on `test` (`result.iterations` of the six results files). On `dev` the answer that ran out
  of calls is gone, and one answer of 27 now gives a value where a refusal was due, a
  forecast, in one run of three (`evals/failures/2026-10-12_refuse-early_dev_unstable.csv`).
  A gain on the cases a change was designed on is not evidence, and here it did not carry
  over.
- Execution accuracy on `test` went from 98.4% to 98.7%, a difference of +0.3 points with
  an interval of [-0.6, +1.6] points, inside the 0.9 points the runs of one variant differ
  by among themselves.
- A question cost 0.00171 USD with the baseline and 0.00177 USD with the variant, on
  `test`: the paragraph is sent with every call.

The variant file stays in `evals/variants/` as the record of what was run. The agent's
default is still the baseline.

### Prompt caching measured: cheaper, and not equivalent by the rule

The second entry of [EVAL_PREREGISTRATION.md](EVAL_PREREGISTRATION.md) was written before
these runs. Three runs of the variant `cache` on `main` at
`40fdcd8350b05f36532529cfd732e4269b135428`; each results file records
`evals/variants/cache.yml` with the SHA-256 written in that entry.

| Run | Results file | Asked | Errors | Cache reads, tokens | Cache writes, tokens | Spent, USD | Time |
|---|---|---|---|---|---|---|---|
| [38280945667](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38280945667) | `evals/results/2026-10-12_cache_38280945667.json` | 180 of 180 | 0 | 1,252,304 | 0 | 0.19844184 | 19 min 23 s |
| [38280964508](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38280964508) | `evals/results/2026-10-12_cache_38280964508.json` | 180 of 180 | 0 | 1,229,396 | 1,909 | 0.197682385 | 17 min 2 s |
| [38280989734](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38280989734) | `evals/results/2026-10-12_cache_38280989734.json` | 180 of 180 | 0 | 1,246,577 | 0 | 0.20236127 | 17 min 7 s |

Together 0.598485495 USD. These are all the runs of the variant that were dispatched. Every
one of the 180 questions of each run read from the cache. The prefix was written once, by
one of the three runs started together: 1,909 tokens, which is its measured length, against
the estimate of 1,700 to 2,200 and the minimum of 512.

**The rule, applied** (`evals/results/2026-10-12_baseline_vs_cache.md`; the cost per run is
`usd` of the `test` records of each file):

| | Baseline | `cache` | Rule | Holds |
|---|---|---|---|---|
| Mean USD per `test` question, the three runs | 0.00170, 0.00173, 0.00168 | 0.00109, 0.00109, 0.00110 | every `cache` run below every baseline run | yes |
| `test` cases right by majority | 122 of 127 | 119 of 127 | 116 to 124 | yes |
| `test` cases with no answer refused by majority | 17 of 21 | 15 of 21 | at least 16 | **no** |

The entry said what follows from this: **cheaper and not equivalent, and caching stays
off. No cost reduction is claimed.**

What can and cannot be said about the guard that failed:

- The text the model is sent is the same, so the entry expected the answers not to move
  beyond the spread between runs. The baseline's own three runs refused 16, 19 and 17 of
  those 21 cases; the `cache` runs refused 15, 17 and 16
  (`evals/results/2026-10-12_cache.md`). Two cases went from refused to missed by majority
  and none the other way, and answers that ended without one went from 4 of 63 to 8 of 63.
- That is small enough to be chance and consistent enough not to be waved away. These runs
  cannot tell which. The rule was written so that I would not choose, and it says no.
- What would settle it is more runs of both, not a second reading of these.

### One run of a larger model, and two routers simulated from it

**This is one run on `dev`, not a measurement of the model.** `dev` is the split the agent
was designed on, and one run cannot be told from the spread between runs.

The variant `sonnet` (`claude-sonnet-5-5`, 0.55 USD allowed per question), eval run
[38281028329](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38281028329)
on `main` at `40fdcd8`, file `evals/results/2026-10-12_sonnet_38281028329.json`: 53 of 53
questions asked, no error, 1.345966 USD, 4 min 57 s. The estimate made before it, from the
tokens Haiku used, was 1.84 USD.

All rows below are from `evals/results/2026-10-12_cost.md`, written by
[`evalkit.cost`](../src/evalkit/cost.py), which names the files of every row.

| On the 53 `dev` questions | Runs | USD per question | USD per correct answer | Seconds per question | Right |
|---|---|---|---|---|---|
| Baseline, `claude-haiku-5-5` | 3 | 0.00173 (0.00172 to 0.00174) | 0.00174 | 5.74 | 158 of 159 |
| `refuse-early` | 3 | 0.00174 (0.00170 to 0.00179) | 0.00176 | 5.55 | 158 of 159 |
| `cache` | 3 | 0.00114 (0.00111 to 0.00117) | 0.00117 | 6.01 | 155 of 159 |
| `sonnet`, one run | 1 | 0.02540 | 0.02540 | 5.59 | 53 of 53 |

The same for all cases and for `test` is in that file; the `test` rows are in the README.

**Two routers, simulated.** Nothing was run for this table. It replays the answers and the
costs already in the files: each of the three baseline runs against the one `sonnet` run.

- *Oracle*: for each case the cheaper model that was right. It knows beforehand who will
  be right, so it is a bound and not a design.
- *Cascade*: Haiku first, and Sonnet only when Haiku ended without an answer or with an
  answer that was not grounded. Then both are paid for.

| Baseline run paired with the `sonnet` run | Haiku alone | Oracle | Cascade | Sonnet alone |
|---|---|---|---|---|
| 38242644460: right | 52 of 53 | 53 of 53 | 53 of 53 | 53 of 53 |
| 38242644460: USD per question | 0.00174 | 0.00224 | 0.00295 | 0.02540 |
| 38242644460: sent to Sonnet | 0 | 1 | 2 | 53 |
| 38245003388: right | 53 of 53 | 53 of 53 | 53 of 53 | 53 of 53 |
| 38245003388: USD per question | 0.00172 | 0.00172 | 0.00214 | 0.02540 |
| 38245003388: sent to Sonnet | 0 | 0 | 1 | 53 |
| 38247610883: right | 53 of 53 | 53 of 53 | 53 of 53 | 53 of 53 |
| 38247610883: USD per question | 0.00174 | 0.00174 | 0.00257 | 0.02540 |
| 38247610883: sent to Sonnet | 0 | 0 | 2 | 53 |

What this shows is mostly the set: Haiku is already right on 52 or 53 of the 53, so a
router has one answer to gain at most, and the cascade spends most of its extra money
asking Sonnet about answers that were right and only not grounded. It says nothing about
`test`, where Haiku misses more, because Sonnet was not run there.

### The same model through a gateway: the run is incomplete, and nothing is claimed

The third entry of [EVAL_PREREGISTRATION.md](EVAL_PREREGISTRATION.md) was written before
this run. One run of the variant `sonnet-ci` on `main` at
`27dab382cd0c0f9d4f9b561e68d2ec1eecf80d21`, eval run
[38434773775](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38434773775),
file `evals/results/2026-10-13_sonnet-ci_38434773775.json`. It records
`evals/variants/sonnet-ci.yml` with the SHA-256 written in that entry. It is the only run
of the variant that was dispatched.

**The rule, applied.**

| Condition | What the run shows | Holds |
|---|---|---|
| 1. Every response names the same model | `claude-sonnet-5.5` on all 53 questions | yes |
| 2. 53 asked, 53 billed, 0 errors | 53 asked, 53 billed, **8 ended in an error** | **no** |
| 3. Billed total below 1.345966 USD | 0.965549 USD, for a run that did not finish 8 questions | not comparable |
| 4. Guards: at least 52 right, at least 8 refused | 44 right and 5 refused, of the 45 that finished | not comparable |

Condition 2 fails, and the entry said what follows: **the run is incomplete, its cost is
reported with the count it is over, and no claim is made.** Not "the same model, cheaper",
and not "not cheaper" either.

**Why it failed.** All 8 errors are the same answer from the gateway, on a later call of a
question: `HTTP 400, invalid_request_error: messages.1.content.N: Invalid signature in
thinking block`.

- The agent's loop sends the model's previous turn back exactly as it came, including any
  reasoning block and its signature. Anthropic's API requires that when a turn that used a
  tool is continued.
- The gateway's documentation, read again on 2026-10-13 at
  <https://www.cheaperinference.com/docs>, says under its Messages request: *"Anthropic-hosted
  server tools, Message Batches, Files, and signed thinking-block replay are not
  compatibility targets."* And: *"Thinking settings can guide an eligible model, but
  responses do not expose Anthropic-signed thinking blocks."*
- So this agent does, on every question with more than one call, the one thing in that
  list. It worked on 45 questions and failed on 8.

That sentence was on the page when it was read before the run, and it was missed: the
first reading looked for the endpoint, the key, the tools and the billing, and did not ask
about reasoning blocks. The run cost 0.965549 USD on the gateway's wallet to find it.

**What the transcripts show, and what they cannot.** The 8 transcripts were read; all are
`dev` cases.

- **None failed on its first call, and none on its second.** The failing call was the
  third in 2 questions, the fourth in 5 and the fifth in 1. Each question had made between
  two and four calls that the gateway accepted before the one it refused.
- **The number in the error follows the conversation.** With T tool calls made before the
  failing call, the block named is always number 2 x (T - 1): 2, 2, 4, 4, 4, 4, 6 and 8 for
  T of 2, 2, 3, 3, 3, 3, 4 and 5. That is where the reasoning block before the last tool
  call would sit if each tool call is preceded by one. So what was refused is the block of
  the most recent turn, and the same kind of block had been accepted on the earlier calls
  of the same question.
- **The transcripts do not hold the reasoning blocks themselves.** They keep the text and
  the tool calls of each turn, not the other blocks the API returns, which the loop sends
  back without reading. That a refused turn carried a reasoning block is what the
  gateway's error says and what the arithmetic above agrees with. It was not seen in a
  transcript, because a transcript cannot show it.
- **No header says which upstream served a call.** The results keep the six headers the
  client asked for; on all 53 questions they are `x-ci-techniques` empty, `x-ci-cache`
  `miss`, `x-ci-tokens-saved` `0` and `x-ci-zdr` `false`, and none names a provider. The
  gateway's documentation says: *"Provider cost and private routing metadata are removed
  before the response is returned to you."* That one call of a question went to a
  different upstream from the call before it is the likely reason a signature stopped
  being accepted, and it cannot be shown from anything the gateway returns.

**No retry and no workaround.** Asking the 8 again could fail the same way. Dropping the
reasoning blocks before sending a turn back would make the questions pass and would change
what the model is sent, so the run would no longer be the agent that was measured direct.

**What the 45 that finished show, deciding nothing.** From
`evals/results/2026-10-13_cost.md` and the two results files; the direct run is
`evals/results/2026-10-12_sonnet_38281028329.json`.

| On `dev`, one run each | Direct, 53 questions | Gateway, the 45 that finished |
|---|---|---|
| Right | 53 of 53 | 44 of 45 |
| Questions with no answer refused | 9 of 9 | 5 of 6 |
| USD per question | 0.02540 | 0.01897 billed |
| The same 45 questions, USD | 1.136096 | 0.853725 billed, 0.8537958 by the price table |
| Seconds per question, mean | 5.59 | 15.32 |
| Input and output tokens, the same 45 | 466,383 and 20,333 | 528,836 and 25,586 |
| Model calls, the same 45 | 146 | 156 |
| Waits after a 429 | 0 | 0 |

- The 44 the gateway run got right, the direct run got right too; the one it got wrong,
  the direct run got right. The three other questions with no answer are among the 8 that
  ended in an error.
- What the gateway billed is what the catalog's price gives, to the fourth decimal: its
  price was what it said.
- The median question took 15.46 seconds and the slowest twentieth over 20.17, against
  5.08 and 9.02 direct (the per-run reports of the two files).
- The 8 questions that ended in an error were billed 0.111824 USD for the calls made
  before they failed.

**A run of 45 questions chosen by which ones did not fail is not a sample of the 53.** The
figures above are what happened, and they are not a comparison of cost or of quality.

## Golden set v2: a harder test the agent can fail

On v1 the agent is right in 98.9% of the answerable cases (445 of 450,
`evals/results/2026-10-12_baseline-regrounded.md`), so a change to the agent cannot be
measured there. v1 stays exactly as it is (a test pins its SHA-256); v2 is a second file,
[`evals/golden_v2.jsonl`](../evals/golden_v2.jsonl), with the same fields, scoring and
tolerance rules ([decision 26](../DECISIONS.md#26-golden-set-v2-is-a-second-harder-file-and-v1-stays-as-it-is)).
`make golden-v2` computes it from [`evals/golden_v2_templates.py`](../evals/golden_v2_templates.py)
and [`evals/hand_cases_v2.yml`](../evals/hand_cases_v2.yml) on the committed fixture, in a
throw-away database; seed 20261019.

| | Cases | `dev` | `test` |
|---|---|---|---|
| Template, ten families of ten | 100 | 30 | 70 |
| Hard, written by hand, ten families of six | 60 | 20 | 40 |
| No answer, ten families of eight | 80 | 20 | 60 |
| Total | 240 | 70 | 170 |

What is hard: pool-days with no row (the answer is 0 and a refusal is wrong), the first and
last day of the data (partial), the fee in hundredths of a basis point, token0 being USDC in
one pool family and wstETH in the other, gross against net volume, averages that are not
means of means, joins, two-query questions, and, for the 80 with no answer, near misses:
intraday and per-swap questions, days and pools outside the data, other chains and
protocols, smart money (the mart is empty), prices and balances the marts do not hold,
forecasts and counterfactuals, wallets, liquidity, and other data sources.

**One correction after review, 2026-10-20.** Seven of the ten `absent-poolday` cases ask
about a pool on 2026-08-09 or 2026-09-25, which the data covers only in part. There, no row
means no swap in the part of the day the data holds, not on the whole day, and unlike the
`partial-day` questions they did not say so. They now end the date with "as far as the data
goes", and the family's note says what no row means on those days. Nothing else changed:
the same 240 ids, splits, answers and SQL. The file's SHA-256 went from
`b5c9dbca282191252ce427a13ce7d652c9e4e4f807d3dccf16cd4450ce25bfdf` to
`9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7`. The partial runs below
were asked the old wording.

### Baseline on v2: the partial runs of 2026-10-19, not used for any rule

Three runs of `baseline` (`claude-haiku-5-5`), split `all`, repetitions 1, `max_usd` 0.66 each,
on `feat/golden-v2` at `a628239`, dispatched together on 2026-10-19:
[39343348798](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39343348798),
[39343368406](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39343368406) and
[39343371673](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39343371673).
Files: `evals/results/2026-10-19_baseline_<RUN_ID>.json`, the report
`evals/results/2026-10-19_baseline.md`, the spread and guards
`evals/results/2026-10-19_baseline_golden_v2_spread.md`, one row per case
`evals/results/2026-10-19_baseline_golden_v2_per_case.csv`.

**The runs are partial, by my mistake.** The runner stops when the budget left is less than
the ceiling of one question (0.25 USD). Each run spent 0.4141, 0.4109 and 0.4115 USD and
then stopped: 211, 210 and 205 of 240 cases were asked; 29, 30 and 35 were `not_run`, even
though the file says `complete`. Every case with an answer was asked in every run. The cases
not asked are questions with no answer, at the end of the file. Counting the three runs
together (94 `not_run` records): forecast 19, near-miss 24, liquidity 24, other-sources 24,
not-held 3. On `test`, 22, 22
and 26 of the 60 cases with no answer were not asked. Nothing was repeated: the night allowed
six runs and the second part needs three.

| On v2, three runs | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Right, of the 160 cases with an answer | 148 (92.5%) | 149 (93.1%) | 148 (92.5%) |
| `test`: right, of 110 with an answer | 102 | 102 | 102 |
| `test`: refused although they have an answer | 7 | 7 | 7 |
| `test`: refused, of the cases with no answer that were asked | 36 of 38 | 36 of 38 | 31 of 34 |
| Spent, USD | 0.4141 | 0.4109 | 0.4115 |

- **The agent can fail this set.** Over the three runs 445 of 480 answers with an answer are
  right, 92.7%, interval [88.8%, 96.2%] (`evals/results/2026-10-19_baseline.md`), against 98.9%
  on v1.
- **The failures are concentrated.** Of the 35 wrong answers, 28 are on the pool-days with no
  row (`absent-poolday` 28 of 30, `missing-pool-day` 3 of 18): in 25 and 3 of them the agent
  refused where the answer is 0.
- **The spread between runs is small on the cases with an answer** (0 cases on `test` by
  total, 2 cases whose runs disagree), and large on refusals: 36, 36 and 31 refused on `test`,
  a spread of 5 cases.
- **Guards, from that spread** (rule in `src/evalkit/spread.py`): on the 110 `test` cases with
  an answer the baseline is right in 102 by majority; a variant may lose at most
  max(1, 0) = 1 net. 7 are refused although they have an answer; a variant may have at most
  7 + max(1, 0) = 8.
- **The refusal recall of the baseline cannot be stated.** 36 of 38 asked cases on `test` is
  94.7% [82.7%, 98.5%] but it excludes the 22 that were not asked, which differ between runs.

### Baseline on v2: three complete runs

Three runs of `baseline` (`claude-haiku-5-5`), golden `evals/golden_v2.jsonl` (SHA-256
`9f920d57...`, the corrected file), split `all`, repetitions 1, `max_usd` 1.00 each, on
`feat/golden-v2` at `e08905b` (the branch with `main` merged in), approved by the owner on
2026-10-20:
[39403472270](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39403472270),
[39403483384](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39403483384) and
[39403493610](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39403493610).
Each asked 240 of 240 questions; none ended in an error. Spent 0.4616194, 0.4685382 and
0.4676213 USD. Files: `evals/results/2026-10-20_baseline_<RUN_ID>.json`, the report over the
three `evals/results/2026-10-20_baseline.md`, the spread and guards
`evals/results/2026-10-20_baseline_golden_v2_spread.md`, one row per case
`evals/results/2026-10-20_baseline_golden_v2_per_case.csv`. Three earlier dispatches, on the
commit before the merge, were cancelled before they started and cost nothing.

| `test`, baseline | Per run | By majority of the three runs |
|---|---|---|
| Correct, all 170 cases | 158, 156, 156 | |
| The 110 with an answer, right | 103, 102, 102 | 102 = 92.7% [86.3%, 96.3%] |
| The 60 with no answer, refused | 55, 54, 54 | 56 = 93.3% [84.1%, 97.4%] |

Intervals are 95% Wilson. Over the three runs together, 470 of 510 answers on `test` are
right, 92.2%, 95% interval [88.2%, 95.7%] resampling cases (`evals/results/2026-10-20_baseline.md`).

**The failures, by category**, cases wrong by majority:

| Category | `dev` (70) | `test` (170) |
|---|---|---|
| A pool-day with no row, refused where the answer is 0 (`absent-poolday`, and one `missing-pool-day`) | 3 | 7 |
| A question with no answer given a value (forecast, another chain, another source) | 3 | 3 |
| Ran out of model calls (one `multi-step`; one question about another pool) | 1 | 1 |
| A question with two readings answered with neither (`ambiguous`) | 0 | 1 |
| Total | 7 | 12 |

The `dev` column was read first and is what the change was designed from: of the 12 wrong
answers to `dev` cases that have an answer, over the three runs, 9 were `absent-poolday`
refusals, and the agent's reason was that one pool's own rows stop on 2026-09-24. The `test`
column was counted after the `zero-day` runs had finished.

### The change on v2, `zero-day`: improved, by the rule written first

The fourth entry of [EVAL_PREREGISTRATION.md](EVAL_PREREGISTRATION.md) was pushed in
`812fc7f`, before any run of the variant: one paragraph appended to the prompt
(`evals/variants/zero-day.md`) saying that within 2026-08-09 to 2026-09-25 and for a pool in
`dim_pools` a pool-day with no row means no swap, so its figures are 0, and that outside
those dates it is still a refusal. Three runs with the inputs of the baseline, on `812fc7f`:
[39407607316](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39407607316),
[39407618600](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39407618600) and
[39407628909](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39407628909).
Each asked 240 of 240, no errors, and records the two variant files with the SHA-256 of the
entry. Spent 0.4675909, 0.4715761 and 0.4688095 USD. Files:
`evals/results/2026-10-20_zero-day_<RUN_ID>.json`, `evals/results/2026-10-20_zero-day.md`,
`evals/results/2026-10-20_zero-day_golden_v2_spread.md` and the comparison
`evals/results/2026-10-20_baseline_vs_zero-day.md`.

**The rule, applied.** On the 110 `test` cases with an answer, by majority of three runs:

| | Baseline | `zero-day` | Rule | Holds |
|---|---|---|---|---|
| Right | 102 = 92.7% [86.3%, 96.3%] | 110 = 100.0% [96.6%, 100.0%] | | |
| Fixed / broke | | 8 / 0 | fixed minus broke 2 or more | yes, 8 |
| Refusal recall, the 60 with no answer | 56 of 60 | 56 of 60 | at least 55 | yes |
| Cases with an answer broken | | 0 | at most 1 | yes |
| Cases with an answer refused | 7 | 0 | at most 9 | yes |

Fixed minus broke is 8 and every guard holds: **improved, by 8 cases**. Every one of the 8
cases the baseline got wrong was fixed. Right in each run: 109, 109 and 108 of 110.

What else moved, deciding nothing:

- Among the 60 `test` cases with no answer, one was fixed and one broke: a question about
  another chain, refused by the baseline, was given a value in all three `zero-day` runs.
  Recall by majority is 56 of 60 in both.
- On `dev`, the cases the change was designed on: 4 of 50 with an answer fixed, none broke;
  the three `absent-poolday` cases are among them.
- Cost and time per question on `test`: 0.00189 against 0.00192 USD, 6.66 against 6.42
  seconds (`evals/results/2026-10-20_baseline_vs_zero-day.md`).
- Left wrong by majority on `test`: 4 cases, all with no answer: 2 forecasts and 1 other
  source given a value, and the other-chain case above.

**What this does and does not say.** The paragraph fixes the weakness it was written for,
on this fixture and this model: every pool-day with no row in `test` is now answered 0, and
nothing measured got worse by more than identical runs differ. It does not say the agent is
better in general. The set was built around known weak spots, and the paragraph names the
dates of this fixture, so it is a fix for this data, not a lesson the agent learnt.

### The zero-day rule as the default: not adopted, its refusals fell short

The `zero-day` paragraph writes the dates of this fixture, and the daily DAG adds a day every
day. So the rule was rewritten to read the dates from the data: `describe_schema` can return
a `coverage` (the first and last `block_date` of `fct_pool_daily`, computed at each call) and
the default prompt referred to it, with no table name and no date
([decision 28](../DECISIONS.md#28-a-pool-day-with-no-row-is-zero-by-default-and-the-dates-come-from-the-data)).
That text is not the one the fourth entry froze, so the
[fifth entry](EVAL_PREREGISTRATION.md#fifth-entry-the-zero-day-rule-as-the-default-checked-for-not-being-worse)
was pushed in `3a9c978`, before any run: by majority of three runs on `test`, at least 109 of
110 with an answer right, at least 55 of 60 with no answer refused, at most 2 with an answer
refused, margins taken from the spread of the `zero-day` and v2 baseline runs.

Three runs of `baseline` with that default, golden v2, split `all`, repetitions 1, `max_usd`
1.00, on `3a9c978`:
[39415287455](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39415287455),
[39415291174](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39415291174) and
[39415294685](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39415294685).
Files: `evals/results/2026-10-20_baseline-coverage_<RUN_ID>.json`.

| Run | Questions asked | Ended in an error | Spent, USD |
|---|---|---|---|
| 39415287455 | 240 | 142 | 0.2121334 |
| 39415291174 | 240 | 139 | 0.2119917 |
| 39415294685 | 240 | 135 | 0.2165488 |

Every error is the same: HTTP 400 from the model API, "You have reached your specified API
usage limits. You will regain access on 2026-11-01 at 00:00 UTC". The limit is the account's,
not the run's: each run spent less than a quarter of its `max_usd`.

**The rule, applied.** The fifth entry does not apply its rule to an incomplete set, and
then the default does not change. No score is drawn from these runs, and none is given here.
Pull request #87 had been merged two minutes after the runs ended, before their results
were read, so the new default reached `main`. A follow-up pull request from `main` took the
rule back out of the prompt, the sentence out of the tool's description and the coverage out
of `evals/warehouse.yml` (`5296cfe`): the default prompt is
again `9df22d15…`, the one of the v2 baseline. The runs were not repeated: that needs the
owner's word, and the API refuses calls until 2026-11-01.

The regression check of #87, at `3a9c978` with the new default, ran before
the limit was reached and passed: 30 of 30 asked and right, no error, 0.00176 USD a question
against a limit of 0.00268 (`eval-pr` run
[39415282729](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39415282729)).
It catches an agent that broke, not one that got slightly worse, so it does not stand in for
the fifth entry.

**Completed, 2026-10-20 (#90).** With the account's limit raised, a dated note on the fifth
entry (pushed in `5ce46f1`, before any run) replaced the incomplete runs by three with the
same inputs, at `5ce46f1` with the prompt `89acfeae…`:
[39422763149](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39422763149),
[39422770533](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39422770533) and
[39422777052](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39422777052).
Each asked 240 of 240 with no error, and spent 0.4778301, 0.4813956 and 0.4788343 USD.
Files: `evals/results/2026-10-20_baseline-coverage_<RUN_ID>.json` for those three ids, the
spread `evals/results/2026-10-20_baseline-coverage_golden_v2_spread.md`, the report over the
three `evals/results/2026-10-20_baseline-coverage-complete.md` and the comparison
`evals/results/2026-10-20_zero-day_vs_baseline-coverage.md`.

| On `test`, by majority of three runs | `zero-day` | New default | Allowed | Holds |
|---|---|---|---|---|
| Cases with an answer right, of 110 | 110 | 110 | at least 109 | yes |
| Cases with no answer refused, of 60 | 56 | 54 | at least 55 | **no** |
| Cases with an answer refused | 0 | 0 | at most 2 | yes |

**The rule, applied: worse than `zero-day` on refusal recall, by 2 cases, one below the
threshold.** The default does not change: #90 reverts its own revert, and the prompt is
`9df22d15…`, the one before #87.

What else the comparison shows, deciding nothing: on the 60 cases with no answer, 1 fixed
and 3 broke; per run, both prompts refused 55, 55, 55 and 55, 54, 55, a mean recall of 91.1%
each; execution accuracy 98.8% and 99.1%; 0.00192 and 0.00196 USD and 6.42 and 6.47 seconds a
question. The drop is the size of the noise between identical runs, so "worse" is what the
rule says, not a finding that the rewrite harms refusals. A rule fixed before the runs is
kept even when it is close. The regression check of #90 (`eval-pr` run
[39422766938](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39422766938)) passed.

## The regression check on pull requests

A pull request that changes the agent, the evaluation code, the evaluation's files or the
prompt starts [`eval-pr.yml`](../.github/workflows/eval-pr.yml): 30 fixed cases asked once,
in the environment `agent-eval-pr`, after the owner's approval
([decision 24](../DECISIONS.md#24-a-regression-check-of-the-agent-on-pull-requests)).

```sh
make eval-ci         # the 30 cases with a scripted model, and the rule: no key, no model
make eval-ci-cases   # pick the cases again and write what a run of them is compared with
```

**The cases** ([`evals/ci_cases.json`](../evals/ci_cases.json)). Picked by
[`evalkit.ci`](../src/evalkit/ci.py) with the seed 20261013 from the three baseline runs
(38242644460, 38245003388, 38247610883, checked again for grounding): only cases right in
all three, 20 from templates, 5 written by hand and 5 with no answer, one family at a time
in turn so that all twelve template families are in and none has more than two. `dev` had
enough of every kind, so **no `test` case was taken**: 30 of 30 are `dev`.

**What a run is compared with**
([`evals/results/ci_baseline.json`](../evals/results/ci_baseline.json)): each case was
right in 3 of 3 baseline runs, by construction, and a question cost 0.00179, 0.00177 and
0.00179 USD on these 30 in the three runs, 0.00178 on average.

**The threshold comes from runs, not from a guess.** Six runs sent the model the
baseline's text. How many of these 30 cases each got wrong:

| Run | Variant | Wrong, of the 30 |
|---|---|---|
| 38242644460 | `baseline` | 0 |
| 38245003388 | `baseline` | 0 |
| 38247610883 | `baseline` | 0 |
| 38280945667 | `cache` | 2 |
| 38280964508 | `cache` | 1 |
| 38280989734 | `cache` | 0 |

The three baseline runs are 0 because the cases were picked for being right in them. The
three `cache` runs are the honest estimate of the noise: they count as repeats of the
baseline because caching sends the model the same text and only bills it differently, which
is what made that experiment an A/A test that still moved by a few cases
([above](#prompt-caching-measured-cheaper-and-not-equivalent-by-the-rule)). The
`refuse-early` runs sent another prompt and are not counted. The worst of the six is 2, and
the limit is that plus one.

**The rule.** The job fails when any of these is true:

| | Fails when |
|---|---|
| Cases asked | fewer than 30, whatever the reason; a run that stops on its budget is a failed run, not a score |
| Questions that ended in an error | 1 or more |
| Cases wrong | more than 3 |
| Mean USD per question | more than 0.00268, which is 1.5 times the baseline's 0.00178 |

A run may spend 0.25 USD in all. The variant [`ci`](../evals/variants/ci.yml) is the
baseline with a ceiling of 0.05 USD per question, so that thirty questions fit under that.
A run that fails is not run again to make it pass.

**What it is for.** With 3 of 30 allowed it catches an agent that broke, not one that got
slightly worse: identical runs already differ by two cases. A claim about quality still
needs the full evaluation and its three runs.

**It has not run yet.** Its first run is the one of the pull request that adds it.

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
  question, every query that ran for it with the rows it returned as the results file kept
  them, in order and with the last one marked as the final one, and the explanation
  ([decision 22](../DECISIONS.md#22-the-judge-is-shown-every-query-of-the-question)). The verdict comes back through a tool, `submit_verdict`; a response with
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

<!-- The labels now in evals/calibration/sheet.csv were written by a model (Claude, in a separate session, applying evals/judge_rubric.md, without the key), not by a person. They are a test of the calibration pipeline. Any kappa computed from them is agreement between two models, not a human calibration, and must never be described as one. -->

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

The sheet cannot say who labelled it, so a file beside it does:
`evals/calibration/sheet.labels.json`, with `labelled_by` set to `person` or `model`.
`agree` refuses to print anything without it. When it says `model`, the report opens with
"NOT A HUMAN CALIBRATION", and every figure in it is named as agreement between two models.

**The sheet is built, and no person has labelled it.** It was built on 2026-10-12 from the
three baseline results files, `evals/results/2026-10-12_baseline_*.json`, with the default
seed: 30 rows, 15 of them altered (4 with a number changed, 8 with a date moved or a name
replaced, 3 with a claim added; none with the unit changed, because the draw gave none).

**The labels in it today were written by a model, not by a person.** Claude, in a separate
session, applied `evals/judge_rubric.md` to the 30 rows without the key: 18 `unfaithful`
and 12 `faithful`. They are there to test the calibration pipeline end to end. Agreement
computed from them is agreement between two models. It is **not** a human calibration of
the judge and must never be described as one. A calibration needs a person's labels: when
the owner labels the sheet, `sheet.labels.json` changes to `person`. Until then a verdict of
the judge is not a measurement, and no evaluation report in this repository uses one.

**How a person labels it**: [`evals/calibration/LABELLING.md`](../evals/calibration/LABELLING.md).
`python -m evalkit.labelling kit` writes one sheet, outside the working copy, with these 30
rows and twenty retrieval cases, none of them showing a model's label; `score` computes the
judge's kappa and the retrieval agreement from the filled sheet once it is committed.

**The judge ran once on this sheet**, on 2026-10-12: the `judge` workflow's run
[38275101405](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38275101405),
`claude-opus-5-5`, 30 of 30 rows judged, 0.400788 USD. Its verdicts are
`evals/calibration/2026-10-12_judge-verdicts_38275101405.json`, and the report of `agree`
with the key is
[`evals/calibration/2026-10-12_agree_model-labels.md`](../evals/calibration/2026-10-12_agree_model-labels.md).

- **The clean figure: 15 of 15 planted errors caught.** Which rows were altered is decided
  by code, not by a reader, and the judge called every one of them `unfaithful`.
- **Agreement with the labels was 30 of 30, between two models.** That is not a human
  calibration and says nothing about agreement with a person.
- **3 of the 15 unaltered rows were called `unfaithful`, by both.** In all three the
  explanation cites a value or a table from an earlier query of the same question, and the
  judge is shown the last query only. The explanations are true to what the agent saw: the
  judge sees less than the agent did, as the grounding check did before it was corrected.
  It was settled on 2026-10-13 by
  [decision 22](../DECISIONS.md#22-the-judge-is-shown-every-query-of-the-question): the
  judge is now shown every query of the question and every result. The sheet has a column
  for them, `earlier`, filled from the transcripts of the three baseline runs with
  `python -m evalkit.calibration earlier`; its questions, queries, explanations and labels
  are as they were. The verdicts and the report above are of the judge as it was.

**The judge ran again on 2026-10-13, shown every query**: the `judge` workflow's run
[38434632537](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38434632537),
30 of 30 rows judged, 0.427652 USD. Verdicts:
`evals/calibration/2026-10-13_judge-verdicts_38434632537.json`; report:
[`evals/calibration/2026-10-13_agree_model-labels.md`](../evals/calibration/2026-10-13_agree_model-labels.md).
Both things that were expected were checked against the key, and both held:

- **The 15 planted errors are still caught**, 15 of 15.
- **Rows 3, 7 and 16 are now judged faithful**, and so are all 15 untouched rows. Against
  the key the judge is right on 30 of 30.
- **Agreement with the labels fell from 30 of 30 to 27 of 30 (kappa 0.800), between two
  models.** The labels were written by a model when only the last query was shown, and the
  three rows it called unfaithful are the three the judge no longer does. That is the
  correction showing, not a regression. It is still not a human calibration, and no figure
  here says how the judge agrees with a person.

## Retrieval over the documentation

The agent answers questions about the data with SQL. Questions about what the data means
are answered in `README.md`, `DECISIONS.md` and `docs/*.md`, so there is a search over those
files and a measurement of it ([decision 27](../DECISIONS.md#27-questions-about-what-the-data-means-are-answered-from-the-documentation-by-search-and-with-citations)).

- [`agent.docs_index`](../src/agent/docs_index.py) splits the files at their headings (id
  `file#heading`) and ranks with BM25 in plain Python. 459 chunks.
- [`evals/rag_cases.jsonl`](../evals/rag_cases.jsonl): 44 questions, 15 `dev` and 29 `test`
  (fixed seed), each with the sections that answer it and 2 to 4 key facts.
  **The labels were written by a model, not by a person**, and nobody has checked them.
- [`evalkit.retrieval`](../src/evalkit/retrieval.py) computes recall@k (the share of cases
  with a relevant section among the first k different sections) and MRR. No model, no cost;
  `tests/test_docs_retrieval.py` runs it in `make test` on `dev` only.

Settings were chosen on `dev` only: 25 combinations of chunk size and heading weight,
ordered by MRR (`python -m evalkit.retrieval evals/rag_cases.jsonl --tune`). The best,
1,000 characters and weight 8, led the next by one case of 15, so it is a choice and not a
finding. `test` was read once, after that, with those settings:

| Split | Cases | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| `dev` (tuned on) | 15 | 12 (80.0%) | 12 (80.0%) | 14 (93.3%) | 0.838 |
| `test` (read once) | 29 | 20 (69.0%) | 25 (86.2%) | 27 (93.1%) | 0.783 |

From `python -m evalkit.retrieval evals/rag_cases.jsonl --split dev|test` in a checkout of
`d2f3f44`, the documents the run below also used (`evals/results/2026-10-20_retrieval.md`).
The search is over the live documents, so later edits move these numbers slightly. With 29 cases one case is 3.4 points; read these as "most questions find
their section in the first five", not as a ranking of rankers.

**A gap the cases do not show.** Two questions the owner suggested, "why is fee 500 for a
0.05% pool?" and why 2026-08-09 is partial, are answered in different places. The first
only in the dbt column descriptions, which are not indexed, so there is no case for it. The
second is in this file and in decision 15.

**The dbt column descriptions, indexed since `feat/zero-day-default`.** The index also reads
every `schema.yml` under `dbt/` (not dbt's `target/` or `dbt_packages/`): one chunk per model
and per seed, with its description and each column with its own, id
`dbt/models/<layer>/schema.yml#<name>`, never cut. That adds 7 chunks. Twelve new cases whose
answer is only there, the fee question among them, are a second file,
[`evals/rag_cases_dbt.jsonl`](../evals/rag_cases_dbt.jsonl), so that the seeded split of the
first does not move; **a model wrote their labels too**. Both sets were scored with and
without the new chunks on the same documents (`--without-dbt`;
`evals/results/2026-10-20_retrieval_dbt.md`):

| Set | Split | Documents only: recall@1 / @3 / @5, MRR | With dbt: recall@1 / @3 / @5, MRR |
|---|---|---|---|
| Old, 44 cases | `dev` (15) | 12 / 12 / 15, 0.840 | 12 / 12 / 13, 0.836 |
| Old, 44 cases | `test` (29) | 20 / 25 / 27, 0.788 | 18 / 24 / 27, 0.749 |
| New, 12 cases | `dev` (4) | cannot be scored | 4 / 4 / 4, 1.000 |
| New, 12 cases | `test` (8) | cannot be scored | 8 / 8 / 8, 1.000 |

The dbt chunks cost the old questions: six moved down and none up, because a short chunk
whose model and column names share the question's words now ranks above the section that
answers it. `dev` recall@5 is at the floor the tests hold. The new set's 12 of 12 says only
that the chunks can be found: most of its questions name a column, whose words are in one
chunk only. The ranker's settings were not tuned again.

**Then made a source of their own.** Because they cost the old questions, the dbt chunks
left the documents' index: `search_docs` takes `source`, `docs` by default or `dbt`, and
each source has its own index, so the documents rank exactly as they would without the dbt
files. The tool's description tells the model to ask for `dbt` only for a question about a
column or a model. Scored again on `main`'s documents
(`evals/results/2026-10-20_retrieval_sources.md`):

| Set | Split | Source | recall@1 / @3 / @5, MRR |
|---|---|---|---|
| Old, 44 cases | `dev` (15) | `docs` | 12 / 12 / 14, 0.838 |
| Old, 44 cases | `test` (29) | `docs` | 20 / 25 / 27, 0.788 |
| New, 12 cases | `dev` (4) | `dbt` | 4 / 4 / 4, 1.000 |
| New, 12 cases | `test` (8) | `dbt` | 8 / 8 / 8, 1.000 |

The old set is back where #86 had it. Whether the agent asks for `dbt` when it should has not
been measured: the run below was made before the parameter existed.

### The agent with the docs tool: one run

`search_docs` is offered only by a variant with `docs_tool: true`
([`evals/variants/docs.yml`](../evals/variants/docs.yml)); the baseline is unchanged. An
answer in words must cite chunk ids that the search returned in that question, or it is
`ungrounded`. [`evalkit.rag_run`](../src/evalkit/rag_run.py) asks each case once.
**Correct** means every key fact is in the answer, by a substring test, which cannot tell a
stated fact from a denied one. **Grounded** means the judge, with
[`evals/judge_rubric_docs.md`](../evals/judge_rubric_docs.md), finds every key statement
supported by a cited chunk; that rubric has not been calibrated against a person. The `eval`
workflow runs it with the new input `suite: docs` (default `sql`, which is the workflow as it
was).

**This is one run, not a measurement of the agent.** Eval run
[39355169194](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/39355169194)
on the branch `feat/rag-docs` at `d2f3f44`, variant `docs`, split `test` (29 cases),
`claude-haiku-5-5`, judge `claude-opus-5-5`, max_usd 1.00. File
`evals/results/2026-10-20_docs_39355169194.json`, report beside it. No error, none not run.

| | Value |
|---|---|
| Correct (every key fact present) | 19 of 29 = 65.5% [47.3%, 80.1%] |
| Key facts present | 54 of 67 |
| Grounded, over the 27 answers in words | 24 of 27 = 88.9% [71.9%, 96.1%] |
| A section that answers was among the chunks the agent was given | 26 of 29 |
| A section that answers was cited | 26 of 29 |
| Ended answered / refused | 27 / 2 |
| Spent: agent, judge | 0.0426 + 0.3924 = 0.4350 USD |

What it does not say: the labels were written by a model; the intervals are wide; the key-fact
test misses facts stated in other words, so 65.5% is a floor on what the answers contain,
by an unknown amount. The failures were not read case by case in this run.
