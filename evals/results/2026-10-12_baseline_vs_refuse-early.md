# baseline against refuse-early

| What is compared | baseline | refuse-early |
|---|---|---|
| Files | 2026-10-12_baseline-regrounded_38242644460.json, 2026-10-12_baseline-regrounded_38245003388.json, 2026-10-12_baseline-regrounded_38247610883.json | 2026-10-12_refuse-early_38255611726.json, 2026-10-12_refuse-early_38255631966.json, 2026-10-12_refuse-early_38255651233.json |
| Runs | 3 | 3 |
| Commit | b6befdc6fe05d666a456b7db9f15083745006f26 | 5caae398c7147032adf61ba890f544430e6cea92 |
| Model | claude-haiku-5-5 | claude-haiku-5-5 |
| System prompt, SHA-256 | 9df22d15d8e9ee4b8e6061646085ef7e917ad487e3ab7ca835ab92519ccbb39b | bca4a778af3d13ebb586472cca215f3a61116646e88529cb3105f3c5b2a6bb13 |
| Variant files | evals/variants/baseline.yml 124a43d52cc09f6bed2942509446c64732c7c1ff0996f92c5856fef9b2b0ea44 | evals/variants/refuse-early.yml 93af24a6913e9585812d84693aa757b0aa8b7adb7317f022a441b2f09dd23c5d; evals/variants/refuse-early.md efd4ecbb5915af6739c128ab1f64aaed353769044b8a7ee5de9b649325f498de |
| Per question | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} |

| The same in both |  |
|---|---|
| Golden file | golden.jsonl, SHA-256 21f1c675a593eb0ee81afb90376e1a462e5694b305c7e667a1607433d0a2c620 |
| Cases | 180 |
| What differs between the two | variant_files, system_prompt_sha256 |

## On `test`: the cases the change was not designed on

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| baseline | 104 of 106 = 98.1% | 104 of 106 = 98.1% | 105 of 106 = 99.1% | 98.4% | 98.1% | 99.1% | [95.9%, 100.0%] |
| refuse-early | 105 of 106 = 99.1% | 105 of 106 = 99.1% | 104 of 106 = 98.1% | 98.7% | 98.1% | 99.1% | [96.5%, 100.0%] |

| The difference in execution accuracy on `test` |  |
|---|---|
| refuse-early minus baseline, means of the runs | +0.3 points |
| 95% interval of the difference (paired bootstrap over cases) | [-0.6, +1.6] points |
| Spread between the runs of baseline | 0.9 points |
| Spread between the runs of refuse-early | 0.9 points |

On `test`, execution accuracy went from 98.4% to 98.7%, a difference of +0.3 points; the runs of one variant differ among themselves by up to 0.9 points, so the difference is not larger than the spread between runs: these runs do not show that the change did anything.

| Case by case on `test`, by majority of the runs | Fixed | Broke | Stayed right | Stayed wrong | Not comparable |
|---|---|---|---|---|---|
| Cases with an answer | 0 | 0 | 105 | 1 | 0 |
| All cases | 1 | 1 | 121 | 4 | 0 |
| Cases with no answer | 1 | 1 | 16 | 3 | 0 |

| Cases with no answer on `test` | baseline | refuse-early |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 17 of 21 = 81.0% [60.0%, 92.3%] | 17 of 21 = 81.0% [60.0%, 92.3%] |
| Ended without an answer (the cap, or the model stopped), all runs | 4 of 63 | 5 of 63 |
| Gave a value where a refusal was due, all runs | 7 of 63 | 6 of 63 |

| On `test`, mean of the runs (lowest to highest) | baseline | refuse-early |
|---|---|---|
| Correct, all cases | 95.8% (94.5% to 96.9%) | 96.1% (95.3% to 96.9%) |
| Execution accuracy (cases with an answer) | 98.4% (98.1% to 99.1%) | 98.7% (98.1% to 99.1%) |
| Refusal recall | 82.5% (76.2% to 90.5%) | 82.5% (81.0% to 85.7%) |
| Refusal precision | 94.5% (94.1% to 95.0%) | 94.5% (94.4% to 94.7%) |
| Refusals made | 17 / 20 / 18 | 18 / 19 / 18 |
| Hallucination rate | 3.1% (2.4% to 3.9%) | 3.9% (2.4% to 4.7%) |
| Valid SQL (queries that ran) | 97.9% (96.7% to 98.7%) | 98.1% (96.9% to 99.1%) |
| Dollars per question, mean | 0.00171 (0.00168 to 0.00173) | 0.00177 (0.00176 to 0.00178) |
| Seconds per question, mean | 5.66 (5.57 to 5.80) | 5.65 (5.62 to 5.68) |

## On `dev`: the cases the change was designed on

These are the cases that were looked at to choose the change. A gain here is expected and is not evidence that the change works.

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| baseline | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 100.0% | 100.0% | 100.0% | [100.0%, 100.0%] |
| refuse-early | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 100.0% | 100.0% | 100.0% | [100.0%, 100.0%] |

| On `dev`, mean of the runs (lowest to highest) | baseline | refuse-early |
|---|---|---|
| Correct, all cases | 99.4% (98.1% to 100.0%) | 99.4% (98.1% to 100.0%) |
| Execution accuracy (cases with an answer) | 100.0% (100.0% to 100.0%) | 100.0% (100.0% to 100.0%) |
| Refusal recall | 96.3% (88.9% to 100.0%) | 96.3% (88.9% to 100.0%) |
| Refusal precision | 100.0% (100.0% to 100.0%) | 100.0% (100.0% to 100.0%) |
| Refusals made | 8 / 9 / 9 | 9 / 9 / 8 |
| Hallucination rate | 2.5% (1.9% to 3.8%) | 3.1% (1.9% to 5.7%) |
| Valid SQL (queries that ran) | 99.7% (99.0% to 100.0%) | 98.9% (98.9% to 99.0%) |
| Dollars per question, mean | 0.00173 (0.00172 to 0.00174) | 0.00174 (0.00170 to 0.00179) |
| Seconds per question, mean | 5.74 (5.67 to 5.80) | 5.55 (5.42 to 5.80) |

| Cases with no answer on `dev` | baseline | refuse-early |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 9 of 9 = 100.0% [70.1%, 100.0%] | 9 of 9 = 100.0% [70.1%, 100.0%] |
| Ended without an answer (the cap, or the model stopped), all runs | 1 of 27 | 0 of 27 |
| Gave a value where a refusal was due, all runs | 0 of 27 | 1 of 27 |

## The largest failure category left on `dev`

Not classified: no failures file was given.
