# baseline against zero-day

| What is compared | baseline | zero-day |
|---|---|---|
| Files | 2026-10-20_baseline_39403472270.json, 2026-10-20_baseline_39403483384.json, 2026-10-20_baseline_39403493610.json | 2026-10-20_zero-day_39407607316.json, 2026-10-20_zero-day_39407618600.json, 2026-10-20_zero-day_39407628909.json |
| Runs | 3 | 3 |
| Commit | e08905b6b8a78e0a9c4c53dedbfa753a0811dfd4 | 812fc7f1177070d366e10ee233ce6491007e598b |
| Model | claude-haiku-5-5 | claude-haiku-5-5 |
| System prompt, SHA-256 | 9df22d15d8e9ee4b8e6061646085ef7e917ad487e3ab7ca835ab92519ccbb39b | 040507b25fa16ed7a755207090330eb3b8a16053f5d92bc54d1758fa675e3873 |
| Variant files | evals/variants/baseline.yml 124a43d52cc09f6bed2942509446c64732c7c1ff0996f92c5856fef9b2b0ea44 | evals/variants/zero-day.yml 4fa515d7bcea8d3857420f51f926cd476fba72d6cb12677fd1224a889804980a; evals/variants/zero-day.md 09f31ee929e61db02d4103d872c82f6d9b126f63fc1a61c8a6c7f3e5f205e2f8 |
| Per question | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} |

| The same in both |  |
|---|---|
| Golden file | golden_v2.jsonl, SHA-256 9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7 |
| Cases | 240 |
| What differs between the two | variant_files, system_prompt_sha256 |

## On `test`: the cases the change was not designed on

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| baseline | 103 of 110 = 93.6% | 102 of 110 = 92.7% | 102 of 110 = 92.7% | 93.0% | 92.7% | 93.6% | [87.9%, 97.3%] |
| zero-day | 109 of 110 = 99.1% | 109 of 110 = 99.1% | 108 of 110 = 98.2% | 98.8% | 98.2% | 99.1% | [97.6%, 99.7%] |

| The difference in execution accuracy on `test` |  |
|---|---|
| zero-day minus baseline, means of the runs | +5.8 points |
| 95% interval of the difference (paired bootstrap over cases) | [+1.5, +10.9] points |
| Spread between the runs of baseline | 0.9 points |
| Spread between the runs of zero-day | 0.9 points |

On `test`, execution accuracy went from 93.0% to 98.8%, a difference of +5.8 points; the runs of one variant differ among themselves by up to 0.9 points, so the difference is larger than the spread between runs.

| Case by case on `test`, by majority of the runs | Fixed | Broke | Stayed right | Stayed wrong | Not comparable |
|---|---|---|---|---|---|
| Cases with an answer | 8 | 0 | 102 | 0 | 0 |
| All cases | 9 | 1 | 157 | 3 | 0 |
| Cases with no answer | 1 | 1 | 55 | 3 | 0 |

| Cases with no answer on `test` | baseline | zero-day |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 56 of 60 = 93.3% [84.1%, 97.4%] | 56 of 60 = 93.3% [84.1%, 97.4%] |
| Ended without an answer (the cap, or the model stopped), all runs | 7 of 180 | 3 of 180 |
| Gave a value where a refusal was due, all runs | 10 of 180 | 13 of 180 |

| On `test`, mean of the runs (lowest to highest) | baseline | zero-day |
|---|---|---|
| Correct, all cases | 92.2% (91.8% to 92.9%) | 96.1% (95.9% to 96.5%) |
| Execution accuracy (cases with an answer) | 93.0% (92.7% to 93.6%) | 98.8% (98.2% to 99.1%) |
| Refusal recall | 90.6% (90.0% to 91.7%) | 91.1% (90.0% to 91.7%) |
| Refusal precision | 90.1% (88.5% to 91.7%) | 99.4% (98.2% to 100.0%) |
| Refusals made | 60 / 60 / 61 | 55 / 55 / 55 |
| Hallucination rate | 4.9% (4.1% to 5.3%) | 5.5% (4.1% to 7.1%) |
| Valid SQL (queries that ran) | 97.7% (97.1% to 98.2%) | 97.4% (97.0% to 98.3%) |
| Dollars per question, mean | 0.00189 (0.00188 to 0.00191) | 0.00192 (0.00191 to 0.00193) |
| Seconds per question, mean | 6.66 (6.52 to 6.78) | 6.42 (6.36 to 6.52) |

## On `dev`: the cases the change was designed on

These are the cases that were looked at to choose the change. A gain here is expected and is not evidence that the change works.

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| baseline | 47 of 50 = 94.0% | 45 of 50 = 90.0% | 46 of 50 = 92.0% | 92.0% | 90.0% | 94.0% | [84.0%, 98.0%] |
| zero-day | 50 of 50 = 100.0% | 50 of 50 = 100.0% | 49 of 50 = 98.0% | 99.3% | 98.0% | 100.0% | [98.0%, 100.0%] |

| On `dev`, mean of the runs (lowest to highest) | baseline | zero-day |
|---|---|---|
| Correct, all cases | 88.6% (87.1% to 90.0%) | 97.1% (95.7% to 98.6%) |
| Execution accuracy (cases with an answer) | 92.0% (90.0% to 94.0%) | 99.3% (98.0% to 100.0%) |
| Refusal recall | 80.0% (75.0% to 85.0%) | 91.7% (90.0% to 95.0%) |
| Refusal precision | 84.2% (83.3% to 85.0%) | 100.0% (100.0% to 100.0%) |
| Refusals made | 18 / 19 / 20 | 18 / 19 / 18 |
| Hallucination rate | 7.6% (7.1% to 8.6%) | 7.1% (4.3% to 10.0%) |
| Valid SQL (queries that ran) | 97.1% (95.9% to 98.2%) | 97.0% (95.8% to 98.1%) |
| Dollars per question, mean | 0.00205 (0.00201 to 0.00211) | 0.00205 (0.00205 to 0.00206) |
| Seconds per question, mean | 7.00 (6.82 to 7.14) | 6.70 (6.56 to 6.88) |

| Cases with no answer on `dev` | baseline | zero-day |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 17 of 20 = 85.0% [64.0%, 94.8%] | 19 of 20 = 95.0% [76.4%, 99.1%] |
| Ended without an answer (the cap, or the model stopped), all runs | 1 of 60 | 2 of 60 |
| Gave a value where a refusal was due, all runs | 11 of 60 | 3 of 60 |

## The largest failure category left on `dev`

Not classified: no failures file was given.
