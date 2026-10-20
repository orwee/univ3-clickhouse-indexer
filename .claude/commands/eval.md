---
description: Run the evaluation the way docs/EVALS.md documents it, compare with the latest saved baseline, and summarise from evals/results/ only
argument-hint: "[variant] [RUN_ID ...]"
---

The evaluation as `docs/EVALS.md` documents it, in four stages. The paid runs are started by
the owner, never by this command: stage 2 ends by stopping and waiting for him.

Arguments: `$ARGUMENTS`. With a variant name and no run ids, start at stage 1. With run ids,
the runs already happened: start at stage 3.

## Rules

- **Every number in the summary comes from a file under `evals/results/`**, and the file is
  named next to it. No number from memory, from a run's web page or from an estimate.
- **Never start a paid run.** Not `gh workflow run`, not `python -m evalkit.run`, not
  `--only-errors`. The owner starts the workflow `eval` and approves its environment
  ("Running an evaluation from GitHub" in `docs/EVALS.md`).
- Run every command on its own and judge it by its exit code: no pipes in between.
- Failures are read on `dev` only ("Reading the failures, on `dev` only"). Do not open the
  per-case records of `test` cases.
- Commit nothing. The files written here go into a pull request the owner asks for.

## 1. The free check

`make eval-ci`

The 30 cases of the pull-request check with a scripted model: no key, no model, no cost.
Report its exit code. A non-zero exit means the evaluation code is broken: say so and stop
before stage 2.

## 2. What to run, then stop

Propose the values of the workflow form, from the files and from `docs/EVALS.md`:

- `variant`: a file in `evals/variants/`, without `.yml`. If it does not exist, say so.
- `golden`: `evals/golden.jsonl` (v1) or `evals/golden_v2.jsonl` (v2). The latest
  baseline is on v2.
- `split` `all`, `repetitions` 1, `limit` empty, `model` empty, unless the owner says
  otherwise. Three runs, because one run is one draw ("Several runs of one variant").
- `max_usd`: the largest `spent_usd` among the latest runs on the same golden file, plus
  0.25. A run stops once less than one question's ceiling (0.25) is left, so a budget equal
  to the expected spend gives a partial run (DECISIONS.md, "Agent corrections", 2026-10-20).
  Name the files the `spent_usd` came from.
- If the variant is new, and not yet run, suggest a first run with `limit` 5, as
  `docs/EVALS.md` says.
- If `docs/EVAL_PREREGISTRATION.md` has no entry for this variant, say that the rule it
  will be judged by is not written yet, and that it should be written before the runs.

Then **stop**. Wait for the owner to start the runs and give their run ids.

## 3. Fetch, and the runs read together

For each run id, on its own:

`scripts/fetch_eval_results.sh RUN_ID`

It writes `evals/results/<date>_<variant>_<RUN_ID>.json` and `.md`, never over an existing
file. Then, for the files of this variant:

`PYTHONPATH=src uv run python -m evalkit.runs <the new .json files> --out evals/results/<date>_<variant>.md`

Before going on, read with `jq` from each new file `state`, `cases_selected`, `spent_usd` and
`budget_usd`, and count its `not_run` records. A run with cases not asked is partial even
when `state` says `complete`; say so in the summary.

## 4. Against the latest saved baseline

The latest saved baseline is the newest date of `evals/results/<date>_baseline_<RUN_ID>.json`
whose `golden_sha256` is the same as the new runs', all files of that date. Check the hash
with `jq -r .golden_sha256` on both sides. If no baseline matches, say so and stop:
`evalkit.compare` refuses two different golden files. If the new runs are the baseline
itself, compare them with the baseline before them on the same golden file. If
`system_prompt_sha256` differs between the two sides, say so.

`PYTHONPATH=src uv run python -m evalkit.compare --baseline <baseline .json files> --variant <new .json files> --out evals/results/<date>_baseline_vs_<variant>.md`

## Summary

From `evals/results/<date>_<variant>.md` and `evals/results/<date>_baseline_vs_<variant>.md`,
naming the file of every number:

1. What was run: variant, golden file, run ids, cases asked of selected, partial or not,
   errors, dollars spent.
2. Execution accuracy on `test`, for both, with the intervals as printed; the difference
   and its interval; fixed, broke and stayed.
3. The sentence of `evalkit.compare` on the spread between runs, copied as it is.
4. Refusals on the cases with no answer, and dollars and seconds per question, as printed.
5. If `docs/EVAL_PREREGISTRATION.md` has an entry for this variant, apply its rule as
   written and say which conditions hold. Otherwise, claim nothing beyond what the
   comparison prints.
6. The files written, uncommitted.
