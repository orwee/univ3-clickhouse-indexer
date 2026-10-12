**NOT A HUMAN CALIBRATION.** The labels of this sheet were written by a model, not by a person. Every figure below is agreement between two models. It does not say how well the judge agrees with a person, and must not be reported as a calibration of the judge.

Labels written by: Claude, in a separate session, applying evals/judge_rubric.md without the key, on 2026-10-12. Written by a model and not by a person: a test of the calibration pipeline.

| Agreement between the labelling model and the judge | |
|---|---|
| Rows of the sheet | 30 |
| Rows with a label and a verdict | 30 |
| Rows the judge gave no verdict on | 0 |
| Percent agreement, between two models | 1.000 |
| Cohen's kappa, between two models | 1.000 |

| Labelling model, down; judge, across | faithful | unfaithful |
|---|---|---|
| faithful | 12 | 0 |
| unfaithful | 0 | 18 |

| Rows, by what the key says | Rows | Expected | Labelling model | Judge |
|---|---|---|---|---|
| number | 4 | unfaithful | 4 | 4 |
| unit | 0 | unfaithful | 0 | 0 |
| name_or_date | 8 | unfaithful | 8 | 8 |
| claim | 3 | unfaithful | 3 | 3 |
| not altered | 15 | faithful | 12 | 12 |
## Where this comes from

- Sheet: `evals/calibration/sheet.csv`, SHA-256 `4f7f08c24d2a8970b75624c3e142f3c22b45c891c348553d94101a161f8a5a68`, the one the verdicts record as their source.
- Verdicts: `evals/calibration/2026-10-12_judge-verdicts_38275101405.json`, the artifact
  `judge-verdicts` of the `judge` workflow's run
  [38275101405](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38275101405),
  on `main` at `3d306139218afc165406468ca483b3af1fe89c5c`: `claude-opus-5-5`, 30 of 30 rows
  judged, no error, 0.400788 USD of a budget of 0.5.
- Key: the file `evalkit.calibration build` wrote under the data directory. It is not in the
  repository.
- Command: `python -m evalkit.calibration agree SHEET VERDICTS --key KEY`. Everything above
  this heading is its output, unedited.

## What may be read from it

**The one clean figure is the planted errors: 15 of 15 caught.** The 15 altered rows were
altered by code, so which rows are wrong does not depend on anybody's judgement. The judge
called all 15 `unfaithful`: 4 of 4 with a number changed, 8 of 8 with a date moved or a
name replaced, 3 of 3 with a claim added. No row had its unit changed, so that kind of
error is not tested.

**The kappa of 1.000 is agreement between two models, not a human calibration.** Both are
Claude models reading the same rubric. That they agree on 30 of 30 rows says the rubric is
applied the same way twice. It does not say a person would apply it that way.

## The three unaltered rows both called unfaithful

Read after the labelling was finished, with the key open. Of the 15 rows the code did not
touch, both models called 3 `unfaithful`. They are rows 3, 7 and 16, as the labelling model
expected, and they have one cause.

| Row | Case, run | What the explanation says | Where the agent got it |
|---|---|---|---|
| 3 | `t-volume-change-009`, 38242644460 | The two daily volumes, 50,399,504.90 and 85,449,867.41 USD | Its first query returned both days. Its last query returned only their difference |
| 7 | `t-peak-day-range-006`, 38242644460 | "the only such pool in dim_pools" | Its first query read `dim_pools` and returned one pool. Its last query read only the daily table |
| 16 | `h-multi-step-002`, 38245003388 | The two weekly shares, "about 38.01% to 36.52%" | Its third query returned 38.012 and 36.5155. Its last query returned only the change |

Checked in the `dev` transcripts of those two runs: in each case the value or the table the
explanation cites is in the result of an earlier query of the same question. The three
explanations are true to what the agent saw. The judge is shown the final query and its
result only, and the rubric tells it to judge against those, so it calls them unsupported.

This is the pattern the grounding check had before it was corrected: **the judge sees less
than the agent saw.** On this sheet it accounts for every disagreement with the key on the
unaltered rows: 3 of 15, which is the judge's whole false-alarm rate here. For row 3 the
judge also gave a second reason, that "single pool" is not shown by the last query; the
first query shows it.

Nothing is changed by this report: not the rubric, not the judge. What to do about it is a
decision for the owner.
