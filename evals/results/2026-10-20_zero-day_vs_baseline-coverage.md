# zero-day against baseline

| What is compared | zero-day | baseline |
|---|---|---|
| Files | 2026-10-20_zero-day_39407607316.json, 2026-10-20_zero-day_39407618600.json, 2026-10-20_zero-day_39407628909.json | 2026-10-20_baseline-coverage_39422763149.json, 2026-10-20_baseline-coverage_39422770533.json, 2026-10-20_baseline-coverage_39422777052.json |
| Runs | 3 | 3 |
| Commit | 812fc7f1177070d366e10ee233ce6491007e598b | 5ce46f1a7bb6cbe432f0e45cc6fd0626e7b91bcf |
| Model | claude-haiku-5-5 | claude-haiku-5-5 |
| System prompt, SHA-256 | 040507b25fa16ed7a755207090330eb3b8a16053f5d92bc54d1758fa675e3873 | 89acfeae828e400166a35423d9682b34a275e57886f2b61ea5f7ac825ca9bca4 |
| Variant files | evals/variants/zero-day.yml 4fa515d7bcea8d3857420f51f926cd476fba72d6cb12677fd1224a889804980a; evals/variants/zero-day.md 09f31ee929e61db02d4103d872c82f6d9b126f63fc1a61c8a6c7f3e5f205e2f8 | evals/variants/baseline.yml 124a43d52cc09f6bed2942509446c64732c7c1ff0996f92c5856fef9b2b0ea44 |
| Per question | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} |

| The same in both |  |
|---|---|
| Golden file | golden_v2.jsonl, SHA-256 9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7 |
| Cases | 240 |
| What differs between the two | variant_files, system_prompt_sha256 |

## On `test`: the cases the change was not designed on

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| zero-day | 109 of 110 = 99.1% | 109 of 110 = 99.1% | 108 of 110 = 98.2% | 98.8% | 98.2% | 99.1% | [97.6%, 99.7%] |
| baseline | 110 of 110 = 100.0% | 108 of 110 = 98.2% | 109 of 110 = 99.1% | 99.1% | 98.2% | 100.0% | [97.9%, 100.0%] |

| The difference in execution accuracy on `test` |  |
|---|---|
| baseline minus zero-day, means of the runs | +0.3 points |
| 95% interval of the difference (paired bootstrap over cases) | [-0.9, +1.5] points |
| Spread between the runs of zero-day | 0.9 points |
| Spread between the runs of baseline | 1.8 points |

On `test`, execution accuracy went from 98.8% to 99.1%, a difference of +0.3 points; the runs of one variant differ among themselves by up to 1.8 points, so the difference is not larger than the spread between runs: these runs do not show that the change did anything.

| Case by case on `test`, by majority of the runs | Fixed | Broke | Stayed right | Stayed wrong | Not comparable |
|---|---|---|---|---|---|
| Cases with an answer | 0 | 0 | 110 | 0 | 0 |
| All cases | 1 | 3 | 163 | 3 | 0 |
| Cases with no answer | 1 | 3 | 53 | 3 | 0 |

| Cases with no answer on `test` | zero-day | baseline |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 56 of 60 = 93.3% [84.1%, 97.4%] | 54 of 60 = 90.0% [79.9%, 95.3%] |
| Ended without an answer (the cap, or the model stopped), all runs | 3 of 180 | 2 of 180 |
| Gave a value where a refusal was due, all runs | 13 of 180 | 14 of 180 |

| On `test`, mean of the runs (lowest to highest) | zero-day | baseline |
|---|---|---|
| Correct, all cases | 96.1% (95.9% to 96.5%) | 96.3% (95.3% to 97.1%) |
| Execution accuracy (cases with an answer) | 98.8% (98.2% to 99.1%) | 99.1% (98.2% to 100.0%) |
| Refusal recall | 91.1% (90.0% to 91.7%) | 91.1% (90.0% to 91.7%) |
| Refusal precision | 99.4% (98.2% to 100.0%) | 100.0% (100.0% to 100.0%) |
| Refusals made | 55 / 55 / 55 | 55 / 54 / 55 |
| Hallucination rate | 5.5% (4.1% to 7.1%) | 6.1% (5.3% to 7.6%) |
| Valid SQL (queries that ran) | 97.4% (97.0% to 98.3%) | 98.2% (98.0% to 98.2%) |
| Dollars per question, mean | 0.00192 (0.00191 to 0.00193) | 0.00196 (0.00195 to 0.00199) |
| Seconds per question, mean | 6.42 (6.36 to 6.52) | 6.47 (6.36 to 6.54) |

## On `dev`: the cases the change was designed on

These are the cases that were looked at to choose the change. A gain here is expected and is not evidence that the change works.

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| zero-day | 50 of 50 = 100.0% | 50 of 50 = 100.0% | 49 of 50 = 98.0% | 99.3% | 98.0% | 100.0% | [98.0%, 100.0%] |
| baseline | 49 of 50 = 98.0% | 50 of 50 = 100.0% | 48 of 50 = 96.0% | 98.0% | 96.0% | 100.0% | [95.3%, 100.0%] |

| On `dev`, mean of the runs (lowest to highest) | zero-day | baseline |
|---|---|---|
| Correct, all cases | 97.1% (95.7% to 98.6%) | 92.9% (91.4% to 94.3%) |
| Execution accuracy (cases with an answer) | 99.3% (98.0% to 100.0%) | 98.0% (96.0% to 100.0%) |
| Refusal recall | 91.7% (90.0% to 95.0%) | 80.0% (80.0% to 80.0%) |
| Refusal precision | 100.0% (100.0% to 100.0%) | 100.0% (100.0% to 100.0%) |
| Refusals made | 18 / 19 / 18 | 16 / 16 / 16 |
| Hallucination rate | 7.1% (4.3% to 10.0%) | 9.0% (4.3% to 11.4%) |
| Valid SQL (queries that ran) | 97.0% (95.8% to 98.1%) | 98.1% (98.0% to 98.1%) |
| Dollars per question, mean | 0.00205 (0.00205 to 0.00206) | 0.00209 (0.00205 to 0.00211) |
| Seconds per question, mean | 6.70 (6.56 to 6.88) | 6.64 (6.56 to 6.68) |

| Cases with no answer on `dev` | zero-day | baseline |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 19 of 20 = 95.0% [76.4%, 99.1%] | 17 of 20 = 85.0% [64.0%, 94.8%] |
| Ended without an answer (the cap, or the model stopped), all runs | 2 of 60 | 4 of 60 |
| Gave a value where a refusal was due, all runs | 3 of 60 | 8 of 60 |

## The largest failure category left on `dev`

Not classified: no failures file was given.
