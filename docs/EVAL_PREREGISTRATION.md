# The one change to the agent: what will be measured, written before it is run

Committed on 2026-10-12, before any run of the variant below exists. The baseline is
measured; the variant is not. The text of the change, the metric and the rule that decides
what may be claimed are frozen by this commit. The report of the comparison says which
commit the variant's runs were made with and the SHA-256 of the files they used, so that
anyone can check them against this page.

## What the baseline showed

Three runs of the 180 cases on `main` at `b6befdc6fe05d666a456b7db9f15083745006f26`: eval
runs 38242644460, 38245003388 and 38247610883. The analysis is
[evals/failures/2026-10-12_baseline_dev.md](../evals/failures/2026-10-12_baseline_dev.md),
made on the 53 `dev` cases and on nothing else.

- **Accuracy is at the ceiling.** On `dev` no case is wrong in two runs of three. A change
  aimed at accuracy cannot show a difference on this set.
- **Grounding has no room.** The 39 `dev` answers marked ungrounded were all right and all
  in a result; 35 were the check being too strict, corrected apart. None was arithmetic
  outside SQL.
- **Refusals are where the runs differ.** Refusal recall over all cases was 24, 28 and 26 of
  30 in three identical runs (`evals/results/2026-10-12_baseline.md`).
- **On `dev`, the only miss is a question that ran out of turns.** One answer of 27 to a
  question with no answer ended at the cap of six model calls without `submit_answer`. Seven
  of those 27 answers used all six calls; none of the 132 answers to a question that has an
  answer did.

## The change

One variant, `refuse-early`: a paragraph appended to the system prompt. Nothing else
differs from the baseline: the same model, the same tools, the same limits, the same six
model calls.

| File | SHA-256 |
|---|---|
| `evals/variants/refuse-early.yml` | `93af24a6913e9585812d84693aa757b0aa8b7adb7317f022a441b2f09dd23c5d` |
| `evals/variants/refuse-early.md` | `efd4ecbb5915af6739c128ab1f64aaed353769044b8a7ee5de9b649325f498de` |

The paragraph, word for word:

```
## When the data cannot answer

Some questions cannot be answered from this warehouse. Decide that early, and keep a turn
to say so.

- When one result shows that what the question needs is not in the warehouse (a table with
  no rows at all, a period or an item that the data does not hold, no column that records
  it), that result is the evidence. Call `submit_answer` with a refusal in your next
  response. Do not run more queries to confirm the same thing another way, and do not look
  for a substitute to report instead.
- A query of yours that returned nothing because of how it was written is not that
  evidence: correct the query.
- Count your turns. When only one is left, that response must be `submit_answer`: the
  answer if your last result holds it, or a refusal that says what you found. Never spend
  your last turn on a query.
```

**Why this one.** It is the only failure `dev` shows, and `dev` shows its cause: on
questions with no answer the agent finds the absence and then spends its remaining calls
confirming it. I chose refusals over grounding because grounding, once the check was
corrected, has nothing left to improve.

**The `dev` cases it targets**: the nine with no answer, and among them the three that use
five or six calls in every run: `u-other-chain-003`, `u-out-of-range-003` and
`u-smart-money-001`. Only the last was ever missed, once.

**What I looked at on `test`, and what I did not.** No `test` case, question, answer or
transcript. I did compute, by code, four counts over the 21 `test` cases with no answer,
after choosing the change and before writing this page; they are the baseline row of the
tables below. They say that most of what `test` misses (7 answers of 63 that gave a value)
is of a kind `dev` does not show, and this change was not designed for it.

## The metric

**Refusal recall on `test`, case by case, by majority of the three runs.** A case with no
answer counts as refused when at least two of its three runs refused it. This is how
run-to-run variation is handled: a case missed in one run of three is counted as refused,
a case missed in two or three is counted as missed, for the baseline and for the variant
alike.

| On the 21 `test` cases with no answer | Baseline |
|---|---|
| Refused by majority of the runs | 17 of 21 = 81.0%, 95% Wilson interval [60.0%, 92.3%] |
| Answers that were refusals, three runs | 52 of 63 |
| Answers that ended without an answer, three runs | 4 of 63 |
| Answers that gave a value where a refusal was due, three runs | 7 of 63 |

Source: the three files `evals/results/2026-10-12_baseline-regrounded_<RUN_ID>.json`,
counted by `evalkit.compare.refusals_due`. The comparison report prints the same four
figures in its baseline column.

The comparison is paired. For each of the 21 cases: **fixed** (missed by majority before,
refused by majority after), **broke** (the reverse), or unchanged.

## What may be claimed, decided now

| Result on the 21 cases | What the README will say |
|---|---|
| Fixed minus broke is 2 or more, and both guards hold | An improvement on this set, of that many cases, with both Wilson intervals |
| Fixed minus broke is -1, 0 or 1 | No measurable difference |
| Broke minus fixed is 2 or more, or a guard fails | The change made it worse, or cost more than it gave; the baseline stays |

**The guards**, on the 106 `test` cases that have an answer, by majority of the runs:

1. Cases answered right: the baseline has 105 of 106. The variant may lose at most one net
   (broke minus fixed of 1 or less).
2. Cases refused although they have an answer: the baseline has 1 of 106. The variant may
   have at most 2.

**What this set cannot show.** The baseline misses 4 cases by majority, so at most 4 can be
fixed. Four fixed and none broken has a one-sided exact sign test of 1 in 16, 0.0625: this
set cannot establish an improvement at the 5% level whatever happens. The two Wilson
intervals will overlap. So the strongest sentence available is "refused N more of 21, an
improvement on this set that it is too small to establish", and the README will use those
words and not stronger ones. If the result is "no measurable difference", it is reported as
that, and it is the likeliest result: the change addresses 4 of the 11 missed answers.

## Also reported, and deciding nothing

- Over the 63 answers: refusals, answers that ended without an answer (baseline 4), answers
  that gave a value (baseline 7).
- Execution accuracy on `test` with the interval of its difference; refusal precision; the
  hallucination rate; valid SQL; dollars and seconds per question.
- The same for `dev`, in a table of its own, labelled as the cases the change was designed
  on. A gain there is not evidence.
- On `dev`, how many answers to a question with no answer used all six model calls
  (baseline 7 of 27).

## The runs

- Three runs of `refuse-early`, with the inputs of the baseline: split `all`, repetitions
  1, `max_usd` 1.50. The owner dispatches and approves them.
- They are made on a `main` that has the corrected grounding check, and are compared with
  the baseline files checked again with that same check. Refusals are not touched by it.
- Every run dispatched is listed in the report. None is left out for its result. A run that
  is partial or has errors is completed with `--only-errors` or replaced, and the report
  says which; a question that ended in an error is never counted as a miss.
- A case with fewer than three scored runs is judged by the majority of the runs it has; a
  case with no majority is "not comparable" and is reported as such.
- Nothing on this page changes after the first run of the variant: not the paragraph, not
  the metric, not the thresholds, not the cases. A second variant would need a second page.

## What this cannot fix

The golden set is easy for this model, and its `test` split has 21 cases with no answer.
That is too few to tell a real gain of two or three cases from chance, and making the set
harder now would change the baseline, so it is not done in this phase. The honest reading
of whatever comes out is on a set of this size and for this model, `claude-haiku-5-5`, only.

---

# Second entry: prompt caching, a change to the cost and not to the agent

Added on 2026-10-12, before any run of the variant `cache` exists. Nothing above this line
was changed: the first entry is as it was committed, and its result is in
[EVALS.md](EVALS.md#the-one-change-measured-refuse-early-no-measurable-difference).

## The change

One variant, `cache`: `prompt_cache: true` and nothing else. The tool definitions and the
system prompt, which every call of every question repeats, are sent as a cached prefix: one
`cache_control` breakpoint on the system prompt, which covers the tools before it. The
model is sent the same text, word for word; the system prompt's SHA-256 is the baseline's.
What changes is how the input is billed.

| File | SHA-256 |
|---|---|
| `evals/variants/cache.yml` | `02f903a9dd3247d62e12443e266090cb9ee6e548ecc3a9757ff4a9a08e7c775c` |

**What the documentation says**, read on 2026-10-12 at
<https://platform.claude.com/docs/en/build-with-claude/prompt-caching>:

- the smallest prefix that can be cached is 512 tokens for Claude Haiku 5.5;
- prefixes are built in the order tools, system, messages, and everything up to and
  including the block with `cache_control` is cached;
- for Claude Haiku 5.5 on prompts up to 100,000 tokens, per million tokens: base input 0.10
  USD, five-minute cache writes 0.125 USD, cache hits 0.01 USD, output 0.50 USD. These are
  the prices already in `src/agent/llm.py`;
- the cache lives five minutes and each use renews it; a prefix under the minimum is not
  cached and no error is returned: both cache counts of the response are then 0.

**The prefix is above the minimum, by an estimate and not by a count.** The token-counting
endpoint needs a key this machine does not have, and the results keep tokens per question,
not per call. What they do give: the shortest `dev` question on record,
`u-not-in-marts-004` in run 38255611726, made 2 calls and was billed 5,967 input tokens
(`evals/results/2026-10-12_refuse-early_38255611726.json`). Everything in those two requests
that is not the prefix is 3,562 characters in its transcript. Counting those at 2 characters
per token, which overstates them, leaves about 2,090 tokens per call for the prefix of that
variant, and about 1,670 without its added paragraph (850 characters, counted the same
way). So the baseline's prefix is somewhere near 1,700 to 2,200 tokens, against a minimum
of 512. The first run settles it: if its results show no cache reads, the prefix was not
cached and the rule below reports no reduction.

**What is expected, as an estimate.** A `test` question takes about 3.6 calls (456, 458 and
450 calls for 127 questions in the three baseline files). If about 1,700 to 2,200 tokens of
each call are read from the cache at a tenth of the price, a question costs about 0.0005 to
0.0007 USD less than the baseline's 0.0017 USD. That is arithmetic, not a measurement.

## The metric

**Mean cost per question on `test`, per run.** Three runs of `cache` against the three
baseline runs.

| Baseline run | Mean USD per question on `test` (127 questions) |
|---|---|
| 38242644460 | 0.00170 |
| 38245003388 | 0.00173 |
| 38247610883 | 0.00168 |

Source: `usd` of the `test` records of
`evals/results/2026-10-12_baseline-regrounded_<RUN_ID>.json`; the comparison report prints
them as "Dollars per question, mean".

## The guard

The text the model is sent does not change, so answers should not change beyond the spread
between runs. That is checked, not assumed, on `test`, by majority of the three runs:

1. **Correctness.** The baseline is right on 122 of 127 cases, 96.1%, 95% Wilson interval
   [91.1%, 98.3%]. The variant has to be inside that interval: right on 116 to 124 cases.
2. **Refusal recall.** The baseline refuses 17 of the 21 cases with no answer. The variant
   has to refuse at least 16.

## The rule, decided now

**A cost reduction is claimed only if all three runs of `cache` have a lower mean cost per
question on `test` than all three baseline runs, that is, each is below 0.00168 USD taken
at full precision from the files, and both parts of the guard hold.**

- If the three runs are cheaper and the guard holds: the README states the reduction as the
  two ranges, baseline and `cache`, with their run ids.
- If any run of `cache` is not cheaper than every baseline run: no reduction is claimed.
- If the runs are cheaper and the guard fails: reported as cheaper and not equivalent, and
  caching stays off.

## Also reported, and deciding nothing

Cost per correct answer; mean seconds per question; cache reads and cache writes as counted
in the results; the same on `dev`.

## The runs

Three runs of `cache`, dispatched and approved by the owner: split `all`, repetitions 1,
`max_usd` 1.00. Every run dispatched is listed, none is left out for its result, and a
question that ended in an error is in no figure. Nothing in this entry changes after the
first run.

## What this cannot show

- The cache is shared by every request of the organisation with the same prefix. Three runs
  started together help each other, and a run alone would write the prefix at least once at
  1.25 times the price. The saving measured is the saving of runs like these.
- Whether the answers are the same is tested by a guard wide enough to hold run-to-run
  noise. It can catch a real loss; it cannot prove there is none.

---

# Third entry: the same model through a second provider

Added on 2026-10-13, before any request has been sent through the gateway. Nothing above
this line was changed. Its two results are in [EVALS.md](EVALS.md): the first change made
no measurable difference, and caching was cheaper and not equivalent by its own rule.

## What the second entry taught, applied here

The `cache` runs sent the model the same text as the baseline. They were in effect the
baseline run three more times, and they still failed a guard that was set at "the baseline
minus one case". A guard has to leave room for the spread between runs of the same thing,
and that spread has to be read from runs, not assumed. The guards below are set that way.

## The change

One variant, `sonnet-ci`: the requests go to the CheaperInference gateway instead of
Anthropic ([decision 23](../DECISIONS.md#23-a-second-provider-only-when-a-variant-names-it)),
and the model is named by the gateway's own id, `claude-sonnet-5.5`. The prompt, the tools,
the six model calls, the row cap and the ceiling per question are those of the variant
`sonnet`, which is the same agent on `claude-sonnet-5-5` asked direct.

| File | SHA-256 |
|---|---|
| `evals/variants/sonnet-ci.yml` | `8d8bfeb70ea5f7bb17f08df38643b3046325930f57d558a199ea07375fc09634` |

**Why Sonnet and why `dev`.** The gateway's catalog, read on 2026-10-13
(<https://www.cheaperinference.com/markets>), lists `claude-sonnet-5.5` and no Haiku 5.5.
The default model cannot be compared, so the three baseline runs cannot be the reference.
The only direct run of Sonnet 5.5 is one run on `dev`, eval run 38281028329
(`evals/results/2026-10-12_sonnet_38281028329.json`), so the comparison is one run on `dev`
against that one.

**One run measures cost, not quality.** A price is the same on every call, so one run of 53
questions says what the gateway charges for them. Whether the answers are as good cannot
be told from one run against one run, on the split the agent was designed on. The guards
below can catch a collapse. They cannot show equivalence, and nothing here will be worded
as if they had.

## The metric

**Billed USD per `dev` question**: what the gateway reports as billed
(`cheaper_inference.billing.billed_cost_usd`, summed in the results as `billed_usd`), over
the 53 questions.

| | Direct, run 38281028329 |
|---|---|
| Questions asked, ended in an error | 53, 0 |
| Spent, USD | 1.345966 |
| USD per question | 0.02540 |
| Input and output tokens | 553,263 and 23,944 |

The direct figure is the cost computed from Anthropic's published prices (2 and 10 USD per
million tokens), which is what Anthropic bills; that run has no separate "billed" field.

## The guards

Counted in the one `sonnet-ci` run, on the 53 `dev` questions. With one run there is no
majority to take: the counts of that run are used.

| | Direct runs on `dev`, each | Lowest | The run must reach |
|---|---|---|---|
| Right answers, of 53 | Haiku baseline 52, 53, 53; Sonnet 53 | 52 | at least 52 |
| Questions with no answer refused, of 9 | Haiku baseline 8, 9, 9; Sonnet 9 | 8 | at least 8 |

Source: the three files `evals/results/2026-10-12_baseline-regrounded_<RUN_ID>.json` and the
Sonnet file above. **The spread is borrowed.** There is one direct run of Sonnet, so its own
run-to-run spread is not known. The three Haiku baseline runs are the only repeated runs on
these 53 questions, and their lowest values are used as the floor: one case below the best.
That is a floor against a collapse, taken from the only spread there is.

## The rule, decided now

**"The same model, cheaper" is claimed only if all four hold:**

1. **It is the same model.** Every response of the run names its model, and every name,
   with dots read as dashes, begins with `claude-sonnet-5-5`. A run whose responses name
   anything else, or name nothing, is a run of another model or of an unknown one: it is
   reported under the name it gave, and never as "the same model".
2. **Every question was billed and none ended in an error**: 53 asked, 53 with a billed
   cost, 0 errors.
3. **It is cheaper by billed cost**: the billed total is below 1.345966 USD.
4. **Both guards hold.**

What is said in each case:

| Outcome | What the README says |
|---|---|
| All four hold | The same model through the gateway cost X against 1.345966 USD for the same 53 questions, in one run each; quality was not measured |
| 1 fails | The gateway served another model; its row is labelled with that model and is not compared as the same |
| 2 fails | The run is incomplete; its cost per question is reported with the count it is over, and no claim is made |
| 3 fails | Not cheaper |
| 4 fails | Cheaper by billed cost, with answers below the floor; not recommended, and said so |

## Also reported, and deciding nothing

- Per question, whether the gateway run and the direct run agree: both right, both wrong,
  one of each. Counts only.
- Seconds per question, median and 95th percentile, for both. The direct run has 5.08 and
  9.02.
- Waits after a 429: how many and how long.
- The cost computed from the catalog's price next to the cost billed, and their difference.
- Cache reads and cache writes as counted, and the gateway's own headers about each call
  (`x-ci-techniques`, `x-ci-cache` and the others kept under `reports`).

## Two things that would void the comparison, looked for before anything is claimed

- **A technique applied.** If any response reports a technique (minification, trimming,
  routing to another model), the request was not the one sent direct. The row is then
  reported with that said, and rule 1 or the wording of the claim follows from it.
- **An answer reused.** If `x-ci-cache` reports a hit, an answer came from the gateway's
  response cache and no model was asked. Those questions are counted, and a run with any
  is reported as such: its cost is not the cost of asking the model.

## The run

One run, dispatched and approved by the owner: variant `sonnet-ci`, split `dev`,
repetitions 1. It is listed whatever it shows. If it stops on an empty wallet or on errors,
it is completed with `--only-errors` or replaced, and the report says which. Nothing in
this entry changes after the first request.

## What this cannot show

- Whether quality is the same. One run each, on `dev`.
- What the gateway will charge next month: its catalog says prices follow capacity.
- Anything about Haiku 5.5, the model the agent runs on by default. It is not on the
  gateway, so the cost of the agent as it is configured does not change with this.
- What happens to a prompt after it reaches the gateway. Decision 23 says what is sent.

---

# Fourth entry: on golden set v2, a pool-day with no row is zero

Added on 2026-10-20, before any run of the variant `zero-day`. Nothing above this line was
changed.

## The baseline, complete

Three runs of `baseline` on golden set v2 (`evals/golden_v2.jsonl`, SHA-256
`9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7`), split `all`,
repetitions 1, `max_usd` 1.00 each, on `feat/golden-v2` at `e08905b`: eval runs
39403472270, 39403483384 and 39403493610. Each asked 240 of 240 questions, none ended in an
error. Files: `evals/results/2026-10-20_baseline_<RUN_ID>.json`; the spread and the guards
are `evals/results/2026-10-20_baseline_golden_v2_spread.md`, written by `evalkit.spread`.

The three partial runs of 2026-10-19 (39343348798, 39343368406, 39343371673) are not used
for anything here.

## What `dev` showed, and nothing else

The change was designed on the 70 `dev` cases only. No `test` case, question, answer or
transcript was read to design it.

- 7 `dev` cases are wrong by majority of the three runs: the 3 `absent-poolday` cases, each
  refused in all three runs; 3 cases with no answer that were given a number (a forecast,
  another chain, another source); and 1 `multi-step` case that ran out of model calls.
- Of the 12 wrong answers to `dev` cases that have an answer, over the three runs, 9 are
  those `absent-poolday` refusals.
- The refusals give one reason: the agent reads the range of one pool's own rows as the
  range of the data ("its coverage runs from 2026-08-10 to 2026-09-24 only, so the data does
  not cover the requested day").

## The change

One variant, `zero-day`: a paragraph appended to the system prompt. It says that within
the dates the data covers (2026-08-09 to 2026-09-25) and for a pool in `dim_pools`, a
missing day in `fct_pool_daily` means no swap that day, so counts, volumes and fees are 0;
that one pool's first or last row is not the edge of the data; and that outside those
dates, or for a pool not in `dim_pools`, it is still a refusal. Nothing else differs: the
model, the tools, the six calls, the ceilings.

| File | SHA-256 |
|---|---|
| `evals/variants/zero-day.yml` | `4fa515d7bcea8d3857420f51f926cd476fba72d6cb12677fd1224a889804980a` |
| `evals/variants/zero-day.md` | `09f31ee929e61db02d4103d872c82f6d9b126f63fc1a61c8a6c7f3e5f205e2f8` |

The system prompt it gives has the SHA-256
`040507b25fa16ed7a755207090330eb3b8a16053f5d92bc54d1758fa675e3873`; each results file
records it.

## The metric

**Correct on the 110 `test` cases that have an answer, per case by majority of the three
runs.** A case counts as right when at least two of its three runs got it right.

| | Baseline |
|---|---|
| Right by majority, of 110 | 102 = 92.7%, 95% Wilson interval [86.3%, 96.3%] |
| Right in each run | 103, 102, 102 |
| Spread between runs (highest minus lowest) | 1 |

The comparison is paired: for each of the 110 cases, **fixed** (wrong by majority in the
baseline, right by majority with `zero-day`), **broke** (the reverse), or unchanged. The
baseline is wrong by majority on 8 of them, so at most 8 can be fixed.

## The guards, from the spread

On `test`, by majority of three runs, read from `evals/results/2026-10-20_baseline_golden_v2_spread.md`:

| Guard | Baseline | Spread between runs | Allowed with `zero-day` |
|---|---|---|---|
| Refusal recall on the 60 cases with no answer | 56 of 60 | 1 (55, 54, 54) | at least 55 of 60, a drop of max(1, 1) = 1 |
| Cases with an answer broken (right by majority before, wrong after) | 0 | 1 (103, 102, 102 right) | at most max(1, 1) = 1 |
| Cases with an answer refused by majority | 7 | 2 (5, 6, 7) | at most 7 + max(1, 2) = 9 |

The first is what the change could cost: an agent told that a missing day is 0 may start
answering 0 where a refusal is due. The second and third say that nothing else may break by
more than identical runs differ.

## The rule, decided now

The threshold for "measurable" is the baseline's own spread on the metric. Its runs differ
by 1 case right, so a difference of 1 is what identical runs already show.

| Fixed minus broke, on the 110 | Guards | What is said |
|---|---|---|
| 2 or more | all hold | **Improved, by that many cases.** Both Wilson intervals are given |
| 2 or more | any fails | Improved on the metric, at a cost the guards do not allow: not adopted, and said so |
| -1, 0 or 1 | | **No measurable difference** |
| -2 or less | | **Worse** |

Also stated, whatever the outcome: how many of the 8 cases wrong in the baseline were
fixed, and how many broke.

## Also reported, and deciding nothing

Per run, on `test` and on `dev`: correct, execution accuracy, refusal recall and
precision, hallucination rate, cost and seconds per question. On `dev`, the three
`absent-poolday` cases, labelled as the cases the change was designed on.

## The runs

Three runs of `zero-day` with the inputs of the baseline (golden `evals/golden_v2.jsonl`,
split `all`, repetitions 1, `max_usd` 1.00), dispatched together, approved by the owner.
Every run dispatched is listed; none is left out for its result. A run that does not ask
all 240 questions, or that has an error, is reported and not repeated without the owner's
word, and the rule is not applied to an incomplete set. Nothing in this entry changes
after the first run.

## What this cannot show

- `test` has 110 cases with an answer and the baseline is wrong on 8. A change that fixes
  every one of them moves the metric by 7.3 points; one that fixes two is the smallest
  difference this rule will call measurable.
- The change was aimed at one known weakness of this model on this fixture. A gain says
  the paragraph fixes that weakness, not that the agent is better in general.

---

# Fifth entry: the zero-day rule as the default, checked for not being worse

Added on 2026-10-20, before any run of the new default. Nothing above this line was
changed.

## What changed, and why it needs its own check

The fourth entry measured `zero-day`: the default prompt of its day plus a paragraph that
writes the dates the data covers. That paragraph is now part of the default prompt,
rewritten so that it names no table and no date: it refers to the `coverage` that
`describe_schema` computes from the data at each call (decision 28). The meaning is meant to
be the same, but the text the model reads is not the text the fourth entry froze, and
`describe_schema` returns more than it did. So the fourth entry does not cover this prompt,
and this entry checks one thing: **that the new default is not worse than `zero-day`** on
golden set v2. It does not try to show that it is better.

| What the new default is | SHA-256 |
|---|---|
| System prompt as sent (`loop.system_prompt(6, 200)`, no descriptions) | `89acfeae828e400166a35423d9682b34a275e57886f2b61ea5f7ac825ca9bca4` |
| `src/agent/prompts/system.md` | `1dab52b7c0fba2ca867edcfcbf316e1ddcce332f0dd743a51a8216b2c9e4e31d` |
| `evals/warehouse.yml` (where the coverage is read) | `f901b186b5dd18818f437696ad1a4026491bc7c5a0c96f2e85decb2e9dd218ce` |
| `evals/variants/baseline.yml` (sets nothing) | `124a43d52cc09f6bed2942509446c64732c7c1ff0996f92c5856fef9b2b0ea44` |
| `src/agent/tools.py` (computes the coverage) | `01a7b2a4e226a2df873cc3987cbe7ee5989366e59c155ec54739e0c10a479ba6` |
| `src/agent/loop.py` (the tool's description) | `9b9309cbfab0abb19cc476120fe50a018d7136e7ab16ab879c0910323d4371b7` |

The model, the tools, the six calls and the ceilings are those of `zero-day`.

## What it is compared with

The three runs of `zero-day` of the fourth entry (39407607316, 39407618600, 39407628909) and,
for the size of the margins only, the three complete runs of the v2 baseline (39403472270,
39403483384, 39403493610). Both sets: golden `evals/golden_v2.jsonl` (SHA-256
`9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7`), split `all`, repetitions
1, `max_usd` 1.00, `claude-haiku-5-5`. Numbers read from
`evals/results/2026-10-20_zero-day_golden_v2_spread.md` and
`evals/results/2026-10-20_baseline_golden_v2_spread.md`.

## The three measures, and the margin of each

All on `test`, per case by majority of three runs (a case counts when at least two of its
three runs agree). The margin of a measure is the larger of 1 and the spread between runs
(highest minus lowest) of that measure in either set: what identical runs already differ by.

| Measure | `zero-day` by majority | Spread, `zero-day` runs | Spread, baseline runs | Margin | Non-inferior when the new default has |
|---|---|---|---|---|---|
| Cases with an answer right, of 110 | 110 | 1 (109, 109, 108) | 1 (103, 102, 102) | max(1, 1, 1) = 1 | **at least 109** |
| Refusal recall, of the 60 with no answer | 56 | 1 (55, 54, 55) | 1 (55, 54, 54) | max(1, 1, 1) = 1 | **at least 55** |
| Cases with an answer refused | 0 | 1 (0, 1, 0) | 2 (5, 6, 7) | max(1, 1, 2) = 2 | **at most 2** |

## The rule, decided now

| The three measures | What is said | What happens to the default |
|---|---|---|
| All three hold | **Not worse than `zero-day`**, within margins of 1, 1 and 2 cases | It stays the default, if the regression check of the pull request also passes |
| Any one fails | **Worse than `zero-day`** on that measure, by how many cases | It does not change: the section "Days with no row", the sentence added to the tool's description and the `coverage` block of `evals/warehouse.yml` are taken out on this pull request, so the default is again the prompt `9df22d15…` and `describe_schema` returns what it returned |

The regression check of decision 24 (`eval-pr`, 30 cases of v1) runs on this pull request
by itself. If it fails its own rule, the default does not change either, whatever the three
runs say, and the same three things are taken out.

Nothing is said about being better: a gain on these measures over `zero-day` is reported,
not claimed.

## Also reported, and deciding nothing

Per run, on `test` and on `dev`: correct, execution accuracy, refusal recall and
precision, hallucination rate, cost and seconds per question. Case by case against
`zero-day` (`evalkit.compare`): fixed and broke, on the cases with an answer and on those
without. The coverage each run's `describe_schema` returned, from the tool-call summaries in the
results files.

## The runs

Three runs of the variant `baseline`, which is now the new default, dispatched together on
the branch `feat/zero-day-default` at the commit that adds this entry, approved by the
owner: golden `evals/golden_v2.jsonl`, split `all`, repetitions 1, `max_usd` 1.00 each, model
left empty (the default in the code, `claude-haiku-5-5`). Every run dispatched is listed;
none is left out for its result. A run that does not ask all 240 questions, or that has an
error, is reported and not repeated without the owner's word, and the rule is not applied
to an incomplete set; the default then does not change on this pull request. Nothing in
this entry changes after the first run.

The files are renamed on fetching to `evals/results/<date>_baseline-coverage_<RUN_ID>.json`,
so that a glob for the v2 baseline's files cannot pick them up. The variant inside them is
`baseline`.

## What this cannot show

- The runs ask the committed fixture, whose data covers 2026-08-09 to 2026-09-25, the dates
  the `zero-day` paragraph wrote. So they check that the rewrite means the same to the
  model, not that the rule stays right as days are added. That the dates follow the data
  is checked by a test that loads a later day and calls `describe_schema` again
  (`tests/test_agent_tools.py`), not by a model.
- Non-inferiority within one case of `zero-day` on 110 cases is not equivalence: a
  difference smaller than identical runs show cannot be seen here.
- The coverage is read from one table. Nothing here measures a question about another one.

## Note added on 2026-10-20, before the replacement runs: how the incomplete runs are replaced

The three runs of 2026-10-20 (39415287455, 39415291174, 39415294685) each asked 240 of 240
and ended 142, 139 and 135 questions in an error, all of one kind: HTTP 400 from the model
API, the account's usage limit. The entry above says what an incomplete set means (the rule
is not applied) but not how it is replaced. The owner has raised the account's limit and
given his word: the three runs are replaced by three new runs with the same inputs (variant
`baseline` with the default pinned above, `evals/golden_v2.jsonl`, split `all`, repetitions
1, `max_usd` 1.00 each, the model left empty), dispatched together on the branch
`feat/default-coverage`, approved by the owner. Each must ask 240 of 240 with no error; if
one does not, nothing is applied and nothing is run again without the owner's word.

Nothing else changes: the default and its SHA-256, the three measures, their margins and
thresholds, and the rule are those written above. The files of the incomplete runs stay in
`evals/results/` and decide nothing; the replacement runs' files are named, as above,
`evals/results/<date>_baseline-coverage_<RUN_ID>.json`, and are told apart from them by
their run ids, which the report lists.

---

# Sixth entry: the coverage default again, under the per-run-means guards

Added on 2026-10-27, before any run of it, at the owner's request (Inbox #94, R03). Nothing
above this line was changed.

## What is measured, and why again

The fifth entry checked that the default with the section "Days with no row" (decision 28)
is not worse than `zero-day`. Its complete runs (39422763149, 39422770533, 39422777052)
refused 54 of the 60 `test` cases with no answer by majority, where 55 were needed, so the
default did not change. That result stands: the rule was written before the runs and was
applied as written, and applying a later rule to those runs is not a result (decision 29).

Decision 29 adopts guards on per-run means. This entry asks the same question as the fifth,
with **new runs** and those guards: **is the default with the section "Days with no row" not
worse than `zero-day`** on golden set v2? It does not try to show that it is better.

The default is the one the fifth entry froze, byte for byte in the prompt sent:

| What the default is | SHA-256 |
|---|---|
| System prompt as sent (`loop.system_prompt(6, 200)`, no descriptions) | `89acfeae828e400166a35423d9682b34a275e57886f2b61ea5f7ac825ca9bca4` |
| `src/agent/prompts/system.md` | `1dab52b7c0fba2ca867edcfcbf316e1ddcce332f0dd743a51a8216b2c9e4e31d` |
| `evals/warehouse.yml` (where the coverage is read) | `f901b186b5dd18818f437696ad1a4026491bc7c5a0c96f2e85decb2e9dd218ce` |
| `evals/variants/baseline.yml` (sets nothing) | `124a43d52cc09f6bed2942509446c64732c7c1ff0996f92c5856fef9b2b0ea44` |
| `src/agent/tools.py` (computes the coverage) | `01a7b2a4e226a2df873cc3987cbe7ee5989366e59c155ec54739e0c10a479ba6` |
| `src/agent/loop.py` (the tool's description) | `f422de482b1deff397960f6d4d704f8bcb67fe6ca9ef80b762af550936bfd607` |

The first five hashes are the fifth entry's. `src/agent/loop.py` differs from the fifth
entry's file by `aafaa5e` only, which changed `search_docs`: that tool is offered only to a
variant that sets `docs_tool`, and `baseline` sets nothing, so the tools sent are the same.
The prompt is restored by reverting `bd409f3`, which had taken it out.

The model, the tools, the six calls and the ceilings are those of `zero-day`.

## What it is compared with

The three runs of `zero-day` of the fourth entry (39407607316, 39407618600, 39407628909):
golden `evals/golden_v2.jsonl` (SHA-256
`9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7`), split `all`,
repetitions 1, `max_usd` 1.00, `claude-haiku-5-5`. They are the reference side of
`evalkit.means.compare`; the new runs are the variant side. The runs of the fifth entry are
not used, neither as reference nor to set a margin.

## The three measures, and the margin of each

All on `test`, counted per run and averaged over the runs of each side, as
`evalkit.means.compare` does (decision 29). The margin of a measure is
`max(1, spread of zero-day's runs)`, the spread being the highest count minus the lowest.
The guard holds when the new runs' mean is worse than `zero-day`'s mean by at most the
margin; better never fails it. Numbers read from the three `zero-day` results files.

| Measure | `zero-day`, per run | Mean | Spread | Margin | Holds when the new runs' mean is |
|---|---|---|---|---|---|
| Right, cases with an answer, of 110 | 109, 109, 108 | 108.67 | 1 | 1 | **at least 107.67** |
| Refused, cases with no answer, of 60 | 55, 54, 55 | 54.67 | 1 | 1 | **at least 53.67** |
| Refused, cases with an answer, of 110 | 0, 1, 0 | 0.33 | 1 | 1 | **at most 1.33** |

## The rule, decided now

| The three measures | What is said | What happens to the default |
|---|---|---|
| All three hold | **Not worse than `zero-day`**, on per-run means within one case | It becomes the default when this pull request is merged, if the regression check of the pull request also passes |
| Any one fails | **Worse than `zero-day`** on that measure, by the shortfall `evalkit.means.compare` prints | It does not change: `bd409f3` is applied again on this pull request (the section "Days with no row", the sentence added to the tool's description and the `coverage` block of `evals/warehouse.yml` come out), so the default is again the prompt `9df22d15…` |

The regression check of decision 24 (`eval-pr`, 30 cases of v1) runs on this pull request
by itself. If it fails its own rule, the default does not change either, whatever the three
runs say.

Nothing is said about being better: a gain on these measures over `zero-day` is reported,
not claimed.

## Also reported, and deciding nothing

Per run, on `test` and on `dev`: correct, execution accuracy, refusal recall and
precision, hallucination rate, cost and seconds per question. Case by case against
`zero-day` (`evalkit.compare`). What `spread.guards` would have said by majority, as a line
in the report and not as a verdict.

## The runs

Three runs of the variant `baseline`, with the default pinned above, dispatched together by
the owner on the branch of this pull request at the commit that adds this entry: golden
`evals/golden_v2.jsonl`, split `all`, repetitions 1, `max_usd` 1.00 each, model left empty
(the default in the code, `claude-haiku-5-5`). Every run dispatched is listed; none is left
out for its result. A run that does not ask all 240 questions, or that has an error, is
reported and not repeated without the owner's word, and the rule is not applied to an
incomplete set; the default then does not change on this pull request. Nothing in this
entry changes after the first run.

The files are renamed on fetching to `evals/results/<date>_coverage-default_<RUN_ID>.json`,
so that a glob for the v2 baseline's or the fifth entry's files cannot pick them up. The
variant inside them is `baseline`.

## What this cannot show

- The runs ask the committed fixture, whose data covers 2026-08-09 to 2026-09-25. They check
  that the rule in the default means to the model what the `zero-day` paragraph meant, not
  that it stays right as days are added; that is a test (`tests/test_agent_tools.py`).
- Three runs a side give a rough estimate of the spread. A margin of one case per run on
  means cannot see a difference smaller than that.
- The fifth entry asked the same question of runs with the same inputs and its rule said
  worse; this one may say not worse. Both are reported, and the difference is the rule's,
  which is why decision 29 applies it from now on only.
- The coverage is read from one table. Nothing here measures a question about another one.
