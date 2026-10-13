# baseline against cache

| What is compared | baseline | cache |
|---|---|---|
| Files | 2026-10-12_baseline-regrounded_38242644460.json, 2026-10-12_baseline-regrounded_38245003388.json, 2026-10-12_baseline-regrounded_38247610883.json | 2026-10-12_cache_38280945667.json, 2026-10-12_cache_38280964508.json, 2026-10-12_cache_38280989734.json |
| Runs | 3 | 3 |
| Commit | b6befdc6fe05d666a456b7db9f15083745006f26 | 40fdcd8350b05f36532529cfd732e4269b135428 |
| Model | claude-haiku-5-5 | claude-haiku-5-5 |
| System prompt, SHA-256 | 9df22d15d8e9ee4b8e6061646085ef7e917ad487e3ab7ca835ab92519ccbb39b | 9df22d15d8e9ee4b8e6061646085ef7e917ad487e3ab7ca835ab92519ccbb39b |
| Variant files | evals/variants/baseline.yml 124a43d52cc09f6bed2942509446c64732c7c1ff0996f92c5856fef9b2b0ea44 | evals/variants/cache.yml 02f903a9dd3247d62e12443e266090cb9ee6e548ecc3a9757ff4a9a08e7c775c |
| Per question | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} | {'max_usd_per_question': '0.25', 'max_iterations': 6, 'row_cap': 200} |

| The same in both |  |
|---|---|
| Golden file | golden.jsonl, SHA-256 21f1c675a593eb0ee81afb90376e1a462e5694b305c7e667a1607433d0a2c620 |
| Cases | 180 |
| What differs between the two | variant_files |

## On `test`: the cases the change was not designed on

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| baseline | 104 of 106 = 98.1% | 104 of 106 = 98.1% | 105 of 106 = 99.1% | 98.4% | 98.1% | 99.1% | [95.9%, 100.0%] |
| cache | 105 of 106 = 99.1% | 104 of 106 = 98.1% | 104 of 106 = 98.1% | 98.4% | 98.1% | 99.1% | [95.9%, 100.0%] |

| The difference in execution accuracy on `test` |  |
|---|---|
| cache minus baseline, means of the runs | +0.0 points |
| 95% interval of the difference (paired bootstrap over cases) | [-0.9, +0.9] points |
| Spread between the runs of baseline | 0.9 points |
| Spread between the runs of cache | 0.9 points |

On `test`, execution accuracy went from 98.4% to 98.4%, a difference of +0.0 points; the runs of one variant differ among themselves by up to 0.9 points, so the difference is not larger than the spread between runs: these runs do not show that the change did anything.

| Case by case on `test`, by majority of the runs | Fixed | Broke | Stayed right | Stayed wrong | Not comparable |
|---|---|---|---|---|---|
| Cases with an answer | 0 | 1 | 104 | 1 | 0 |
| All cases | 0 | 3 | 119 | 5 | 0 |
| Cases with no answer | 0 | 2 | 15 | 4 | 0 |

| Cases with no answer on `test` | baseline | cache |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 17 of 21 = 81.0% [60.0%, 92.3%] | 15 of 21 = 71.4% [50.0%, 86.2%] |
| Ended without an answer (the cap, or the model stopped), all runs | 4 of 63 | 8 of 63 |
| Gave a value where a refusal was due, all runs | 7 of 63 | 7 of 63 |

| On `test`, mean of the runs (lowest to highest) | baseline | cache |
|---|---|---|
| Correct, all cases | 95.8% (94.5% to 96.9%) | 94.8% (94.5% to 95.3%) |
| Execution accuracy (cases with an answer) | 98.4% (98.1% to 99.1%) | 98.4% (98.1% to 99.1%) |
| Refusal recall | 82.5% (76.2% to 90.5%) | 76.2% (71.4% to 81.0%) |
| Refusal precision | 94.5% (94.1% to 95.0%) | 92.8% (88.9% to 100.0%) |
| Refusals made | 17 / 20 / 18 | 15 / 19 / 18 |
| Hallucination rate | 3.1% (2.4% to 3.9%) | 3.9% (3.1% to 4.7%) |
| Valid SQL (queries that ran) | 97.9% (96.7% to 98.7%) | 97.9% (97.0% to 99.1%) |
| Dollars per question, mean | 0.00171 (0.00168 to 0.00173) | 0.00110 (0.00109 to 0.00110) |
| Seconds per question, mean | 5.66 (5.57 to 5.80) | 5.89 (5.63 to 6.38) |

## On `dev`: the cases the change was designed on

These are the cases that were looked at to choose the change. A gain here is expected and is not evidence that the change works.

| Execution accuracy | run 1 | run 2 | run 3 | Mean | Lowest | Highest | 95% interval (bootstrap over cases) |
|---|---|---|---|---|---|---|---|
| baseline | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 100.0% | 100.0% | 100.0% | [100.0%, 100.0%] |
| cache | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 100.0% | 100.0% | 100.0% | [100.0%, 100.0%] |

| On `dev`, mean of the runs (lowest to highest) | baseline | cache |
|---|---|---|
| Correct, all cases | 99.4% (98.1% to 100.0%) | 97.5% (96.2% to 100.0%) |
| Execution accuracy (cases with an answer) | 100.0% (100.0% to 100.0%) | 100.0% (100.0% to 100.0%) |
| Refusal recall | 96.3% (88.9% to 100.0%) | 85.2% (77.8% to 100.0%) |
| Refusal precision | 100.0% (100.0% to 100.0%) | 100.0% (100.0% to 100.0%) |
| Refusals made | 8 / 9 / 9 | 7 / 7 / 9 |
| Hallucination rate | 2.5% (1.9% to 3.8%) | 0.0% (0.0% to 0.0%) |
| Valid SQL (queries that ran) | 99.7% (99.0% to 100.0%) | 98.4% (98.1% to 99.0%) |
| Dollars per question, mean | 0.00173 (0.00172 to 0.00174) | 0.00114 (0.00111 to 0.00117) |
| Seconds per question, mean | 5.74 (5.67 to 5.80) | 6.01 (5.72 to 6.58) |

| Cases with no answer on `dev` | baseline | cache |
|---|---|---|
| Refused, by majority of the runs, with its 95% Wilson interval | 9 of 9 = 100.0% [70.1%, 100.0%] | 8 of 9 = 88.9% [56.5%, 98.0%] |
| Ended without an answer (the cap, or the model stopped), all runs | 1 of 27 | 4 of 27 |
| Gave a value where a refusal was due, all runs | 0 of 27 | 0 of 27 |

## The largest failure category left on `dev`

Not classified: no failures file was given.
