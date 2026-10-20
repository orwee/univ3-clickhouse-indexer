# Evaluation over 3 runs: baseline

| The same in every run |  |
|---|---|
| Variant | baseline |
| Variant file evals/variants/baseline.yml | SHA-256 124a43d52cc09f6bed2942509446c64732c7c1ff0996f92c5856fef9b2b0ea44 |
| Model | claude-haiku-5-5 |
| Golden file | golden_v2.jsonl, SHA-256 9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7 |
| System prompt | SHA-256 89acfeae828e400166a35423d9682b34a275e57886f2b61ea5f7ac825ca9bca4 |
| Per question | $0.25, 6 model calls, 200 rows |
| Cases | 240 |

| What was run | run 1 | run 2 | run 3 |
|---|---|---|---|
| File | 2026-10-20_baseline-coverage_39422763149.json | 2026-10-20_baseline-coverage_39422770533.json | 2026-10-20_baseline-coverage_39422777052.json |
| Run | 2026-10-20T124117Z_baseline_ebe3cb | 2026-10-20T124146Z_baseline_6b76f7 | 2026-10-20T124157Z_baseline_852ef1 |
| Commit | 5ce46f1a7bb6cbe432f0e45cc6fd0626e7b91bcf | 5ce46f1a7bb6cbe432f0e45cc6fd0626e7b91bcf | 5ce46f1a7bb6cbe432f0e45cc6fd0626e7b91bcf |
| State | complete | complete | complete |
| Started | 2026-10-20T12:41:17+00:00 | 2026-10-20T12:41:46+00:00 | 2026-10-20T12:41:57+00:00 |
| Ended | 2026-10-20T13:07:43+00:00 | 2026-10-20T13:08:10+00:00 | 2026-10-20T13:07:46+00:00 |
| Split | all | all | all |
| Questions asked | 240 of 240 | 240 of 240 | 240 of 240 |
| Not run | 0 | 0 | 0 |
| Ended in an error | 0 | 0 | 0 |
| Budget, USD | 1.00 | 1.00 | 1.00 |
| Spent, USD | 0.4778301 | 0.4813956 | 0.4788343 |

| Errors, apart | run 1 | run 2 | run 3 | All runs |
|---|---|---|---|---|
| Questions asked | 240 | 240 | 240 | 720 |
| Ended in an error (in no figure of this report) | 0 | 0 | 0 | 0 |
| Scored | 240 | 240 | 240 | 720 |
| Not run | 0 | 0 | 0 | 0 |
| What the errors cost, USD | 0.00000 | 0.00000 | 0.00000 | 0.00000 |
| Waits after a 429 or a 529 | 0 | 0 | 0 | 0 |
| Seconds waited | 0 | 0 | 0 | 0 |

## All cases

| Metric | run 1 | run 2 | run 3 | Mean | Lowest | Highest | Spread between runs |
|---|---|---|---|---|---|---|---|
| Correct, all cases | 230 of 240 = 95.8% | 228 of 240 = 95.0% | 228 of 240 = 95.0% | 95.3% | 95.0% | 95.8% | 0.8 points |
| Execution accuracy (cases with an answer) | 159 of 160 = 99.4% | 158 of 160 = 98.8% | 157 of 160 = 98.1% | 98.8% | 98.1% | 99.4% | 1.3 points |
| Refusal recall (cases with no answer that were refused) | 71 of 80 = 88.8% | 70 of 80 = 87.5% | 71 of 80 = 88.8% | 88.3% | 87.5% | 88.8% | 1.2 points |
| Refusal precision (refusals that were due) | 71 of 71 = 100.0% | 70 of 70 = 100.0% | 71 of 71 = 100.0% | 100.0% | 100.0% | 100.0% | 0.0 points |
| Hallucination rate | 21 of 240 = 8.8% | 12 of 240 = 5.0% | 17 of 240 = 7.1% | 6.9% | 5.0% | 8.8% | 3.7 points |
| Ungrounded answers | 13 of 240 = 5.4% | 6 of 240 = 2.5% | 10 of 240 = 4.2% | 4.0% | 2.5% | 5.4% | 2.9 points |
| Valid SQL (queries that ran) | 489 of 498 = 98.2% | 490 of 500 = 98.0% | 491 of 500 = 98.2% | 98.1% | 98.0% | 98.2% | 0.2 points |
| Questions with a failed query | 9 of 240 = 3.8% | 9 of 240 = 3.8% | 8 of 240 = 3.3% | 3.6% | 3.3% | 3.8% | 0.4 points |

| Over the 3 runs together | Correct of scored | 95% interval (bootstrap over cases) | Cases correct in every run | in some runs | in no run | scored in fewer runs |
|---|---|---|---|---|---|---|
| Correct, all cases | 686 of 720 = 95.3% | [92.8%, 97.4%] | 221 | 13 | 6 | 0 |
| Execution accuracy (cases with an answer) | 474 of 480 = 98.8% | [97.7%, 99.6%] | 154 | 6 | 0 | 0 |

| Per question | run 1 | run 2 | run 3 | Mean | Lowest | Highest |
|---|---|---|---|---|---|---|
| Cost per question, USD, mean | 0.00199 | 0.00201 | 0.00200 | 0.00200 | 0.00199 | 0.00201 |
| Cost per question, USD, median | 0.00201 | 0.00199 | 0.00201 | 0.00200 | 0.00199 | 0.00201 |
| Cost per question, USD, 95th percentile | 0.00321 | 0.00320 | 0.00314 | 0.00319 | 0.00314 | 0.00321 |
| Tokens per question, mean | 15,834 | 16,019 | 15,911 | 15,921 | 15,834 | 16,019 |
| Tokens per question, median | 16,340 | 16,186 | 16,301 | 16,276 | 16,186 | 16,340 |
| Tokens per question, 95th percentile | 25,949 | 26,747 | 26,550 | 26,415 | 25,949 | 26,747 |
| Seconds per question, mean | 6.57 | 6.58 | 6.41 | 6.52 | 6.41 | 6.58 |
| Seconds per question, median | 6.20 | 6.21 | 6.28 | 6.23 | 6.20 | 6.28 |
| Seconds per question, 95th percentile | 10.68 | 10.76 | 9.67 | 10.37 | 9.67 | 10.76 |

## `dev` cases

| Metric | run 1 | run 2 | run 3 | Mean | Lowest | Highest | Spread between runs |
|---|---|---|---|---|---|---|---|
| Correct, all cases | 65 of 70 = 92.9% | 66 of 70 = 94.3% | 64 of 70 = 91.4% | 92.9% | 91.4% | 94.3% | 2.9 points |
| Execution accuracy (cases with an answer) | 49 of 50 = 98.0% | 50 of 50 = 100.0% | 48 of 50 = 96.0% | 98.0% | 96.0% | 100.0% | 4.0 points |
| Refusal recall (cases with no answer that were refused) | 16 of 20 = 80.0% | 16 of 20 = 80.0% | 16 of 20 = 80.0% | 80.0% | 80.0% | 80.0% | 0.0 points |
| Refusal precision (refusals that were due) | 16 of 16 = 100.0% | 16 of 16 = 100.0% | 16 of 16 = 100.0% | 100.0% | 100.0% | 100.0% | 0.0 points |
| Hallucination rate | 8 of 70 = 11.4% | 3 of 70 = 4.3% | 8 of 70 = 11.4% | 9.0% | 4.3% | 11.4% | 7.1 points |
| Ungrounded answers | 5 of 70 = 7.1% | 2 of 70 = 2.9% | 5 of 70 = 7.1% | 5.7% | 2.9% | 7.1% | 4.3 points |
| Valid SQL (queries that ran) | 156 of 159 = 98.1% | 150 of 153 = 98.0% | 156 of 159 = 98.1% | 98.1% | 98.0% | 98.1% | 0.1 points |
| Questions with a failed query | 3 of 70 = 4.3% | 3 of 70 = 4.3% | 2 of 70 = 2.9% | 3.8% | 2.9% | 4.3% | 1.4 points |

| Over the 3 runs together | Correct of scored | 95% interval (bootstrap over cases) | Cases correct in every run | in some runs | in no run | scored in fewer runs |
|---|---|---|---|---|---|---|
| Correct, all cases | 195 of 210 = 92.9% | [87.6%, 97.1%] | 60 | 8 | 2 | 0 |
| Execution accuracy (cases with an answer) | 147 of 150 = 98.0% | [95.3%, 100.0%] | 47 | 3 | 0 | 0 |

| Per question | run 1 | run 2 | run 3 | Mean | Lowest | Highest |
|---|---|---|---|---|---|---|
| Cost per question, USD, mean | 0.00210 | 0.00205 | 0.00211 | 0.00209 | 0.00205 | 0.00211 |
| Cost per question, USD, median | 0.00206 | 0.00204 | 0.00212 | 0.00207 | 0.00204 | 0.00212 |
| Cost per question, USD, 95th percentile | 0.00328 | 0.00314 | 0.00322 | 0.00321 | 0.00314 | 0.00328 |
| Tokens per question, mean | 16,719 | 16,421 | 16,930 | 16,690 | 16,421 | 16,930 |
| Tokens per question, median | 16,523 | 16,414 | 16,856 | 16,598 | 16,414 | 16,856 |
| Tokens per question, 95th percentile | 27,495 | 25,171 | 26,941 | 26,536 | 25,171 | 27,495 |
| Seconds per question, mean | 6.68 | 6.68 | 6.56 | 6.64 | 6.56 | 6.68 |
| Seconds per question, median | 6.21 | 6.25 | 6.36 | 6.27 | 6.21 | 6.36 |
| Seconds per question, 95th percentile | 10.48 | 11.54 | 9.89 | 10.64 | 9.89 | 11.54 |

## `test` cases

| Metric | run 1 | run 2 | run 3 | Mean | Lowest | Highest | Spread between runs |
|---|---|---|---|---|---|---|---|
| Correct, all cases | 165 of 170 = 97.1% | 162 of 170 = 95.3% | 164 of 170 = 96.5% | 96.3% | 95.3% | 97.1% | 1.8 points |
| Execution accuracy (cases with an answer) | 110 of 110 = 100.0% | 108 of 110 = 98.2% | 109 of 110 = 99.1% | 99.1% | 98.2% | 100.0% | 1.8 points |
| Refusal recall (cases with no answer that were refused) | 55 of 60 = 91.7% | 54 of 60 = 90.0% | 55 of 60 = 91.7% | 91.1% | 90.0% | 91.7% | 1.7 points |
| Refusal precision (refusals that were due) | 55 of 55 = 100.0% | 54 of 54 = 100.0% | 55 of 55 = 100.0% | 100.0% | 100.0% | 100.0% | 0.0 points |
| Hallucination rate | 13 of 170 = 7.6% | 9 of 170 = 5.3% | 9 of 170 = 5.3% | 6.1% | 5.3% | 7.6% | 2.4 points |
| Ungrounded answers | 8 of 170 = 4.7% | 4 of 170 = 2.4% | 5 of 170 = 2.9% | 3.3% | 2.4% | 4.7% | 2.4 points |
| Valid SQL (queries that ran) | 333 of 339 = 98.2% | 340 of 347 = 98.0% | 335 of 341 = 98.2% | 98.2% | 98.0% | 98.2% | 0.3 points |
| Questions with a failed query | 6 of 170 = 3.5% | 6 of 170 = 3.5% | 6 of 170 = 3.5% | 3.5% | 3.5% | 3.5% | 0.0 points |

| Over the 3 runs together | Correct of scored | 95% interval (bootstrap over cases) | Cases correct in every run | in some runs | in no run | scored in fewer runs |
|---|---|---|---|---|---|---|
| Correct, all cases | 491 of 510 = 96.3% | [93.5%, 98.6%] | 161 | 5 | 4 | 0 |
| Execution accuracy (cases with an answer) | 327 of 330 = 99.1% | [97.9%, 100.0%] | 107 | 3 | 0 | 0 |

| Per question | run 1 | run 2 | run 3 | Mean | Lowest | Highest |
|---|---|---|---|---|---|---|
| Cost per question, USD, mean | 0.00195 | 0.00199 | 0.00195 | 0.00196 | 0.00195 | 0.00199 |
| Cost per question, USD, median | 0.00200 | 0.00198 | 0.00198 | 0.00199 | 0.00198 | 0.00200 |
| Cost per question, USD, 95th percentile | 0.00320 | 0.00325 | 0.00314 | 0.00320 | 0.00314 | 0.00325 |
| Tokens per question, mean | 15,470 | 15,854 | 15,491 | 15,605 | 15,470 | 15,854 |
| Tokens per question, median | 16,228 | 16,081 | 16,068 | 16,125 | 16,068 | 16,228 |
| Tokens per question, 95th percentile | 24,950 | 27,432 | 25,561 | 25,981 | 24,950 | 27,432 |
| Seconds per question, mean | 6.53 | 6.54 | 6.36 | 6.47 | 6.36 | 6.54 |
| Seconds per question, median | 6.18 | 6.18 | 6.22 | 6.19 | 6.18 | 6.22 |
| Seconds per question, 95th percentile | 10.97 | 10.76 | 9.51 | 10.42 | 9.51 | 10.97 |
