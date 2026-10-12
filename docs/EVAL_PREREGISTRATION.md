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
