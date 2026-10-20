# The new default on golden set v2: three incomplete runs

Read from `evals/results/2026-10-20_baseline-coverage_<RUN_ID>.json` (variant `baseline`, the default of the fifth entry of `docs/EVAL_PREREGISTRATION.md`). Eval runs 39415287455, 39415291174 and 39415294685. No score is drawn from them: by that entry the rule is not applied to an incomplete set.

Commit `3a9c978c3c7b33f362dd9b4afc5ede2d4375395e`, system prompt SHA-256 `89acfeae828e400166a35423d9682b34a275e57886f2b61ea5f7ac825ca9bca4`, golden `evals/golden_v2.jsonl`, split `all`, repetitions 1, `max_usd` 1.00 each.

| GitHub run | Questions asked | Ended in an error | Spent, USD |
|---|---|---|---|
| 39415287455 | 240 | 142 | 0.2121334 |
| 39415291174 | 240 | 139 | 0.2119917 |
| 39415294685 | 240 | 135 | 0.2165488 |

Spent by the three together: 0.6406739 USD (0.64 rounded).

Every error has the same reason: `llm_error: BadRequestError: HTTP 400, invalid_request_error: You have reached your specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC.`

The rule it would have applied, from the fifth entry: on `test` by majority of the three runs, at least 109 of the 110 cases with an answer right, at least 55 of the 60 with no answer refused, at most 2 cases with an answer refused.
