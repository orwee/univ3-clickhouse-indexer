# Evaluation over 3 runs: refuse-early

| The same in every run |  |
|---|---|
| Variant | refuse-early |
| Variant file evals/variants/refuse-early.yml | SHA-256 93af24a6913e9585812d84693aa757b0aa8b7adb7317f022a441b2f09dd23c5d |
| Variant file evals/variants/refuse-early.md | SHA-256 efd4ecbb5915af6739c128ab1f64aaed353769044b8a7ee5de9b649325f498de |
| Model | claude-haiku-5-5 |
| Golden file | golden.jsonl, SHA-256 21f1c675a593eb0ee81afb90376e1a462e5694b305c7e667a1607433d0a2c620 |
| System prompt | SHA-256 bca4a778af3d13ebb586472cca215f3a61116646e88529cb3105f3c5b2a6bb13 |
| Per question | $0.25, 6 model calls, 200 rows |
| Cases | 180 |

| What was run | run 1 | run 2 | run 3 |
|---|---|---|---|
| File | 2026-10-12_refuse-early_38255611726.json | 2026-10-12_refuse-early_38255631966.json | 2026-10-12_refuse-early_38255651233.json |
| Run | 2026-10-12T132635Z_refuse-early_ad954b | 2026-10-12T132638Z_refuse-early_98f762 | 2026-10-12T132636Z_refuse-early_efadbd |
| Commit | 5caae398c7147032adf61ba890f544430e6cea92 | 5caae398c7147032adf61ba890f544430e6cea92 | 5caae398c7147032adf61ba890f544430e6cea92 |
| State | complete | complete | complete |
| Started | 2026-10-12T13:26:35+00:00 | 2026-10-12T13:26:38+00:00 | 2026-10-12T13:26:36+00:00 |
| Ended | 2026-10-12T13:43:27+00:00 | 2026-10-12T13:43:41+00:00 | 2026-10-12T13:43:24+00:00 |
| Split | all | all | all |
| Questions asked | 180 of 180 | 180 of 180 | 180 of 180 |
| Not run | 0 | 0 | 0 |
| Ended in an error | 0 | 0 | 0 |
| Budget, USD | 1.5 | 1.5 | 1.5 |
| Spent, USD | 0.3133477 | 0.3203692 | 0.3179268 |

| Errors, apart | run 1 | run 2 | run 3 | All runs |
|---|---|---|---|---|
| Questions asked | 180 | 180 | 180 | 540 |
| Ended in an error (in no figure of this report) | 0 | 0 | 0 | 0 |
| Scored | 180 | 180 | 180 | 540 |
| Not run | 0 | 0 | 0 | 0 |
| What the errors cost, USD | 0.00000 | 0.00000 | 0.00000 | 0.00000 |
| Waits after a 429 or a 529 | 0 | 0 | 0 | 0 |
| Seconds waited | 0 | 0 | 0 | 0 |

## All cases

| Metric | run 1 | run 2 | run 3 | Mean | Lowest | Highest | Spread between runs |
|---|---|---|---|---|---|---|---|
| Correct, all cases | 175 of 180 = 97.2% | 176 of 180 = 97.8% | 173 of 180 = 96.1% | 97.0% | 96.1% | 97.8% | 1.7 points |
| Execution accuracy (cases with an answer) | 149 of 150 = 99.3% | 149 of 150 = 99.3% | 148 of 150 = 98.7% | 99.1% | 98.7% | 99.3% | 0.7 points |
| Refusal recall (cases with no answer that were refused) | 26 of 30 = 86.7% | 27 of 30 = 90.0% | 25 of 30 = 83.3% | 86.7% | 83.3% | 90.0% | 6.7 points |
| Refusal precision (refusals that were due) | 26 of 27 = 96.3% | 27 of 28 = 96.4% | 25 of 26 = 96.2% | 96.3% | 96.2% | 96.4% | 0.3 points |
| Hallucination rate | 7 of 180 = 3.9% | 7 of 180 = 3.9% | 6 of 180 = 3.3% | 3.7% | 3.3% | 3.9% | 0.6 points |
| Ungrounded answers | 6 of 180 = 3.3% | 4 of 180 = 2.2% | 5 of 180 = 2.8% | 2.8% | 2.2% | 3.3% | 1.1 points |
| Valid SQL (queries that ran) | 305 of 308 = 99.0% | 314 of 319 = 98.4% | 309 of 317 = 97.5% | 98.3% | 97.5% | 99.0% | 1.5 points |
| Questions with a failed query | 3 of 180 = 1.7% | 5 of 180 = 2.8% | 7 of 180 = 3.9% | 2.8% | 1.7% | 3.9% | 2.2 points |

| Over the 3 runs together | Correct of scored | 95% interval (bootstrap over cases) | Cases correct in every run | in some runs | in no run | scored in fewer runs |
|---|---|---|---|---|---|---|
| Correct, all cases | 524 of 540 = 97.0% | [95.0%, 98.9%] | 170 | 9 | 1 | 0 |
| Execution accuracy (cases with an answer) | 446 of 450 = 99.1% | [97.3%, 100.0%] | 148 | 1 | 1 | 0 |

| Per question | run 1 | run 2 | run 3 | Mean | Lowest | Highest |
|---|---|---|---|---|---|---|
| Cost per question, USD, mean | 0.00174 | 0.00178 | 0.00177 | 0.00176 | 0.00174 | 0.00178 |
| Cost per question, USD, median | 0.00151 | 0.00152 | 0.00152 | 0.00152 | 0.00151 | 0.00152 |
| Cost per question, USD, 95th percentile | 0.00283 | 0.00288 | 0.00272 | 0.00281 | 0.00272 | 0.00288 |
| Tokens per question, mean | 13,744 | 14,080 | 13,958 | 13,927 | 13,744 | 14,080 |
| Tokens per question, median | 11,424 | 11,540 | 11,562 | 11,509 | 11,424 | 11,562 |
| Tokens per question, 95th percentile | 22,379 | 22,863 | 21,922 | 22,388 | 21,922 | 22,863 |
| Seconds per question, mean | 5.60 | 5.67 | 5.58 | 5.62 | 5.58 | 5.67 |
| Seconds per question, median | 5.31 | 5.25 | 5.22 | 5.26 | 5.22 | 5.31 |
| Seconds per question, 95th percentile | 8.45 | 8.94 | 8.49 | 8.63 | 8.45 | 8.94 |

## `dev` cases

| Metric | run 1 | run 2 | run 3 | Mean | Lowest | Highest | Spread between runs |
|---|---|---|---|---|---|---|---|
| Correct, all cases | 53 of 53 = 100.0% | 53 of 53 = 100.0% | 52 of 53 = 98.1% | 99.4% | 98.1% | 100.0% | 1.9 points |
| Execution accuracy (cases with an answer) | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 44 of 44 = 100.0% | 100.0% | 100.0% | 100.0% | 0.0 points |
| Refusal recall (cases with no answer that were refused) | 9 of 9 = 100.0% | 9 of 9 = 100.0% | 8 of 9 = 88.9% | 96.3% | 88.9% | 100.0% | 11.1 points |
| Refusal precision (refusals that were due) | 9 of 9 = 100.0% | 9 of 9 = 100.0% | 8 of 8 = 100.0% | 100.0% | 100.0% | 100.0% | 0.0 points |
| Hallucination rate | 1 of 53 = 1.9% | 1 of 53 = 1.9% | 3 of 53 = 5.7% | 3.1% | 1.9% | 5.7% | 3.8 points |
| Ungrounded answers | 1 of 53 = 1.9% | 1 of 53 = 1.9% | 2 of 53 = 3.8% | 2.5% | 1.9% | 3.8% | 1.9 points |
| Valid SQL (queries that ran) | 87 of 88 = 98.9% | 95 of 96 = 99.0% | 90 of 91 = 98.9% | 98.9% | 98.9% | 99.0% | 0.1 points |
| Questions with a failed query | 1 of 53 = 1.9% | 1 of 53 = 1.9% | 1 of 53 = 1.9% | 1.9% | 1.9% | 1.9% | 0.0 points |

| Over the 3 runs together | Correct of scored | 95% interval (bootstrap over cases) | Cases correct in every run | in some runs | in no run | scored in fewer runs |
|---|---|---|---|---|---|---|
| Correct, all cases | 158 of 159 = 99.4% | [98.1%, 100.0%] | 52 | 1 | 0 | 0 |
| Execution accuracy (cases with an answer) | 132 of 132 = 100.0% | [100.0%, 100.0%] | 44 | 0 | 0 | 0 |

| Per question | run 1 | run 2 | run 3 | Mean | Lowest | Highest |
|---|---|---|---|---|---|---|
| Cost per question, USD, mean | 0.00170 | 0.00179 | 0.00175 | 0.00174 | 0.00170 | 0.00179 |
| Cost per question, USD, median | 0.00145 | 0.00148 | 0.00149 | 0.00147 | 0.00145 | 0.00149 |
| Cost per question, USD, 95th percentile | 0.00274 | 0.00282 | 0.00301 | 0.00286 | 0.00274 | 0.00301 |
| Tokens per question, mean | 13,432 | 14,077 | 13,823 | 13,777 | 13,432 | 14,077 |
| Tokens per question, median | 11,159 | 11,354 | 11,341 | 11,285 | 11,159 | 11,354 |
| Tokens per question, 95th percentile | 22,045 | 22,863 | 23,080 | 22,663 | 22,045 | 23,080 |
| Seconds per question, mean | 5.42 | 5.80 | 5.45 | 5.55 | 5.42 | 5.80 |
| Seconds per question, median | 5.22 | 5.42 | 5.11 | 5.25 | 5.11 | 5.42 |
| Seconds per question, 95th percentile | 7.86 | 8.77 | 9.49 | 8.71 | 7.86 | 9.49 |

## `test` cases

| Metric | run 1 | run 2 | run 3 | Mean | Lowest | Highest | Spread between runs |
|---|---|---|---|---|---|---|---|
| Correct, all cases | 122 of 127 = 96.1% | 123 of 127 = 96.9% | 121 of 127 = 95.3% | 96.1% | 95.3% | 96.9% | 1.6 points |
| Execution accuracy (cases with an answer) | 105 of 106 = 99.1% | 105 of 106 = 99.1% | 104 of 106 = 98.1% | 98.7% | 98.1% | 99.1% | 0.9 points |
| Refusal recall (cases with no answer that were refused) | 17 of 21 = 81.0% | 18 of 21 = 85.7% | 17 of 21 = 81.0% | 82.5% | 81.0% | 85.7% | 4.8 points |
| Refusal precision (refusals that were due) | 17 of 18 = 94.4% | 18 of 19 = 94.7% | 17 of 18 = 94.4% | 94.5% | 94.4% | 94.7% | 0.3 points |
| Hallucination rate | 6 of 127 = 4.7% | 6 of 127 = 4.7% | 3 of 127 = 2.4% | 3.9% | 2.4% | 4.7% | 2.4 points |
| Ungrounded answers | 5 of 127 = 3.9% | 3 of 127 = 2.4% | 3 of 127 = 2.4% | 2.9% | 2.4% | 3.9% | 1.6 points |
| Valid SQL (queries that ran) | 218 of 220 = 99.1% | 219 of 223 = 98.2% | 219 of 226 = 96.9% | 98.1% | 96.9% | 99.1% | 2.2 points |
| Questions with a failed query | 2 of 127 = 1.6% | 4 of 127 = 3.1% | 6 of 127 = 4.7% | 3.1% | 1.6% | 4.7% | 3.1 points |

| Over the 3 runs together | Correct of scored | 95% interval (bootstrap over cases) | Cases correct in every run | in some runs | in no run | scored in fewer runs |
|---|---|---|---|---|---|---|
| Correct, all cases | 366 of 381 = 96.1% | [93.2%, 98.4%] | 118 | 8 | 1 | 0 |
| Execution accuracy (cases with an answer) | 314 of 318 = 98.7% | [96.5%, 100.0%] | 104 | 1 | 1 | 0 |

| Per question | run 1 | run 2 | run 3 | Mean | Lowest | Highest |
|---|---|---|---|---|---|---|
| Cost per question, USD, mean | 0.00176 | 0.00178 | 0.00177 | 0.00177 | 0.00176 | 0.00178 |
| Cost per question, USD, median | 0.00152 | 0.00153 | 0.00155 | 0.00154 | 0.00152 | 0.00155 |
| Cost per question, USD, 95th percentile | 0.00287 | 0.00297 | 0.00272 | 0.00285 | 0.00272 | 0.00297 |
| Tokens per question, mean | 13,874 | 14,081 | 14,014 | 13,989 | 13,874 | 14,081 |
| Tokens per question, median | 11,542 | 11,603 | 11,668 | 11,604 | 11,542 | 11,668 |
| Tokens per question, 95th percentile | 22,521 | 22,930 | 21,751 | 22,401 | 21,751 | 22,930 |
| Seconds per question, mean | 5.68 | 5.62 | 5.64 | 5.65 | 5.62 | 5.68 |
| Seconds per question, median | 5.40 | 5.23 | 5.27 | 5.30 | 5.23 | 5.40 |
| Seconds per question, 95th percentile | 8.51 | 8.95 | 8.49 | 8.65 | 8.49 | 8.95 |
