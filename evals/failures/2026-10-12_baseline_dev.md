# The baseline on `dev`: what failed, and what did not

Read on 2026-10-12 from the three baseline runs, `dev` cases only (53 of the 180). No `test`
transcript was opened and no `test` case was looked at; where a figure over `test` is given
below it is a count made by code, and it says so.

The runs, all on `main` at `b6befdc6fe05d666a456b7db9f15083745006f26`:

| Run | Results file, as first measured | Checked again for grounding |
|---|---|---|
| 38242644460 | `evals/results/2026-10-12_baseline_38242644460.json` | `evals/results/2026-10-12_baseline-regrounded_38242644460.json` |
| 38245003388 | `evals/results/2026-10-12_baseline_38245003388.json` | `evals/results/2026-10-12_baseline-regrounded_38245003388.json` |
| 38247610883 | `evals/results/2026-10-12_baseline_38247610883.json` | `evals/results/2026-10-12_baseline-regrounded_38247610883.json` |

Everything below is from the files checked again. Right and wrong are the same in both sets.

## Wrong answers: none that repeats

| | Cases | File |
|---|---|---|
| Wrong in at least two of the three runs | 0 | `2026-10-12_baseline_dev.csv` (a header and no row) |
| Wrong in exactly one run | 1 | `2026-10-12_baseline_dev_unstable.csv` |
| Right in all three | 52 | `evals/results/2026-10-12_baseline-regrounded.md` |

Over the three runs `dev` has 158 right answers of 159. By majority of the runs it is 53 of
53. There is no failure on `dev` to classify, so the count per category is:

| Category | Cases wrong in at least two runs | Cases wrong in one run |
|---|---|---|
| Ran out of turns | 0 | 1 |
| Wrong table; units or decimals; date filter; wrong pool; made something up; refused what has an answer; SQL error it did not recover from; other | 0 | 0 |

The one unstable case is `u-smart-money-001`, a question that has no answer because the
table it needs has no rows. In run 1 the agent used its six model calls on queries and never
called `submit_answer`: `no_answer`, "iteration_cap: 6 model calls without an answer". In
runs 2 and 3 it refused, correctly, on its sixth and last call.

## Refusals, case by case over the three runs

`2026-10-12_baseline_dev_refusals.csv` has every `dev` case with no answer, and how each run
ended.

| | |
|---|---|
| `dev` cases with no answer | 9 |
| Refused in all three runs | 8 |
| Missed in one run of three | 1 (`u-smart-money-001`, above) |
| Missed in two or three runs | 0 |
| Refused by majority of the runs | 9 of 9 |
| Answers that gave a value where a refusal was due | 0 of 27 |

So on `dev` the run-to-run change in refusal recall (8 of 9, 9 of 9, 9 of 9) is one case in
one run, and by the rule "a case missed in one of three is the draw" it is noise.

What is not noise is how close to the limit these questions run. The same file gives the
model calls of each answer:

| Model calls used, of the 6 allowed | Answers to `dev` questions with no answer (27) | Answers to `dev` questions with an answer (132) |
|---|---|---|
| 3 | 7 | 81 |
| 4 | 9 | 42 |
| 5 | 4 | 9 |
| 6 | 7 | 0 |

The left column is counted from `2026-10-12_baseline_dev_refusals.csv`; the right one from
`result.iterations` of the `dev` records of the three results files. No question that has an
answer needed its sixth call. Seven of the 27 answers to a question without one did, in
three cases (`u-other-chain-003`, `u-out-of-range-003`, `u-smart-money-001`): the agent
finds that the thing asked about is not there, then keeps querying to confirm it another
way, and refuses on the last call it has, or does not get to.

## Ungrounded answers: the check, not the agent

39 `dev` answers over the three runs were marked ungrounded as first measured. All 39 were
right, and all 39 values are in a result the model was shown.

| Where the value was | Right | Wrong |
|---|---|---|
| The same number as a cell of the last turn, read as a double (formatting) | 20 | 0 |
| A cell of another query sent in the same turn | 15 | 0 |
| A cell of an earlier turn, with another query run after it | 4 | 0 |
| Arithmetic done outside SQL | 0 | 0 |
| In no result | 0 | 0 |

Source: `2026-10-12_baseline_dev_ungrounded_<RUN_ID>.csv`, one file per run. 35 of the 39
were the check being too strict, and that was corrected as a measurement fix of its own
([docs/EVALS.md](../../docs/EVALS.md#the-grounding-check-was-too-strict)). The 4 left are in
three cases, each in one or two runs of three; by majority one case
(`t-swaps-all-range-005`, two runs) is ungrounded. `dev` shows no arithmetic outside SQL, so
grounding has no room for a measured improvement.

## What this leaves

- **The golden set is easy for this model.** `dev` cannot show that a change improves
  accuracy: it is already 53 of 53 by majority.
- **The one thing `dev` shows is the turn limit on questions with no answer.** It cost one
  answer of 27 on `dev`.
- **`test` has more room in refusals than `dev`, and I do not know why.** Counted by code
  over the 21 `test` cases with no answer, without reading any of them: 17 of 21 refused by
  majority; of the 63 answers, 52 refusals, 4 that ended without an answer, 7 that gave a
  value. The 4 are the kind of miss seen on `dev`. The 7 are not seen on `dev` at all, and
  nothing here was designed for them.

The change that follows from this, and how it will be judged, is in
[docs/EVAL_PREREGISTRATION.md](../../docs/EVAL_PREREGISTRATION.md).
