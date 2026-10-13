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
