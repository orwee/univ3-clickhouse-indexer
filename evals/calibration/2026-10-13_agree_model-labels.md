**NOT A HUMAN CALIBRATION.** The labels of this sheet were written by a model, not by a person. Every figure below is agreement between two models. It does not say how well the judge agrees with a person, and must not be reported as a calibration of the judge.

Labels written by: Claude, in a separate session, applying evals/judge_rubric.md without the key, on 2026-10-12. Written by a model and not by a person: a test of the calibration pipeline.

| Agreement between the labelling model and the judge | |
|---|---|
| Rows of the sheet | 30 |
| Rows with a label and a verdict | 30 |
| Rows the judge gave no verdict on | 0 |
| Percent agreement, between two models | 0.900 |
| Cohen's kappa, between two models | 0.800 |

| Labelling model, down; judge, across | faithful | unfaithful |
|---|---|---|
| faithful | 12 | 0 |
| unfaithful | 3 | 15 |

| Rows, by what the key says | Rows | Expected | Labelling model | Judge |
|---|---|---|---|---|
| number | 4 | unfaithful | 4 | 4 |
| unit | 0 | unfaithful | 0 | 0 |
| name_or_date | 8 | unfaithful | 8 | 8 |
| claim | 3 | unfaithful | 3 | 3 |
| not altered | 15 | faithful | 12 | 15 |
## Where this comes from

- Sheet: `evals/calibration/sheet.csv`, SHA-256 `0b38c8585878b75a81ae7ba652340499b0f773280058a57aa4c8883c3928f3f5`, the one the verdicts record as their source. It is the sheet of 2026-10-12 with the column `earlier` added; its questions, queries, explanations and labels are the same.
- Verdicts: `evals/calibration/2026-10-13_judge-verdicts_38434632537.json`, the artifact
  `judge-verdicts` of the `judge` workflow's run
  [38434632537](https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38434632537),
  on `main` at `27dab382cd0c0f9d4f9b561e68d2ec1eecf80d21`: `claude-opus-5-5`, 30 of 30 rows
  judged, no error, 0.427652 USD of a budget of 0.8. Rubric SHA-256
  `9089df5d4110db55fa55f66d626d21b54ba08580eb782b8cbe1364c030b13ca2`.
- Key: the file under the data directory. It is not in the repository.
- Command: `python -m evalkit.calibration agree SHEET VERDICTS --key KEY`. Everything above
  this heading is its output, unedited.

## What changed since the report of 2026-10-12

Between the two runs the judge was changed to be shown every query of the question and
every result, not only the last
([decision 22](../../DECISIONS.md#22-the-judge-is-shown-every-query-of-the-question)).
Two things were expected, and both were checked against the key, not assumed.

| | Judge of 2026-10-12, last query only | Judge of 2026-10-13, every query |
|---|---|---|
| Planted errors called `unfaithful` | 15 of 15 | 15 of 15 |
| Untouched rows called `faithful` | 12 of 15 | 15 of 15 |
| Rows 3, 7 and 16 | `unfaithful`, all three | `faithful`, all three |
| Agreement with the model labels, between two models | 30 of 30, kappa 1.000 | 27 of 30, kappa 0.800 |
| Spent, USD | 0.400788 | 0.427652 |

- **The 15 planted errors are still caught**: 4 of 4 numbers, 8 of 8 dates or names, 3 of 3
  added claims. Showing the judge more did not give an altered explanation anything to
  hide behind. No row had its unit changed, so that kind is still untested.
- **Rows 3, 7 and 16 are now judged faithful**, and its reasons name the earlier query:
  "the earlier query returned one pool", "the tables (fct_pool_daily, dim_pools)",
  "the shares (38.01% and 36.52%, from query 3)".
- **Against the key the judge is now right on 30 of 30 rows.** That is the one figure here
  that does not depend on who labelled: which rows were altered is decided by code.

## The agreement fell, and that is the correction, not a regression

**The labels were written by a model, when only the last query was shown.** The three rows
the judge now calls faithful are the three the labelling model called unfaithful, for the
reason decision 22 removed. So the two models now disagree on exactly those three: 27 of
30, kappa 0.800. Neither figure, 1.000 before or 0.800 now, is a human calibration, and
neither says how the judge would agree with a person. If a model labelled the sheet again
with every query in view the figure would move again, and it would still be agreement
between two models.

A calibration of the judge still needs a person's labels.
