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

**When this was written, on 2026-10-11, the `eval` workflow had never run**, and so neither
had the script. Everything above about them is what the code and its tests say, not what a
run showed.

### What a run costs: an estimate, not yet a measurement

No evaluation has been measured yet. The only real question asked so far is the one of the
`agent` workflow's run
[38150882341](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38150882341),
whose artifact `agent-result` says: 3 model calls, 9,329 input and 535 output tokens,
0.0012004 USD, 4.1 seconds, with `claude-haiku-5-5`. If every question cost that, the 180
cases would come to about 0.22 USD and about 12 minutes. That is one question multiplied by
180, and nothing more: the first full run replaces this paragraph with what it measured.

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

`build` writes `evals/calibration/sheet.csv`, which does not exist yet: thirty answered
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

**None of this has run.** No model has judged anything, the owner has not labelled a sheet,
and there is no agreement figure. Until there is one, a verdict of the judge is not a
measurement, and no report in this repository uses one.
