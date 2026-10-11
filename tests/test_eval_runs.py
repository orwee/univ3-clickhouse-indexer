"""Several runs of one variant as one report. Built by hand here; no model, no server.

Three runs of six cases: four with an answer (two `dev`, two `test`) and two that must be
refused. What each run did is written in the table below, and every figure the report
prints is counted from it by hand in the tests.
"""

import json

import pytest

from evalkit import runs, score

CASES = {
    "d-1": ("dev", "number"),
    "d-2": ("dev", "number"),
    "t-1": ("test", "number"),
    "t-2": ("test", "number"),
    "d-u": ("dev", "refusal"),
    "t-u": ("test", "refusal"),
}
#        d-1      d-2      t-1      t-2      d-u        t-u
RUNS = [
    ("right", "right", "right", "wrong", "refused", "refused"),
    ("right", "wrong", "right", "wrong", "refused", "answered"),
    ("right", "error", "right", "right", "refused", "refused"),
]


def case(case_id):
    split, answer_type = CASES[case_id]
    refusal = answer_type == "refusal"
    return {
        "id": case_id,
        "kind": "unanswerable" if refusal else "template",
        "family": "f",
        "split": split,
        "answer_type": answer_type,
        "expected": None if refusal else "100",
        "accepted": [],
        "tolerance": None if refusal else {"abs": "0", "rel": "0"},
    }


def result(what, usd, seconds):
    status = {"right": "answered", "wrong": "answered", "answered": "answered"}.get(what, what)
    answer = None
    if status == "answered":
        answer = {"value": "100" if what == "right" else "1"}
    if status == "refused":
        answer = {"refusal_reason": "No such thing."}
    waits = [{"seconds": 30.0}] if what == "error" else []
    return {
        "status": status,
        "reason": "llm_error: APIConnectionError" if what == "error" else "",
        "answer": answer,
        "tool_calls": [{"name": "run_sql", "summary": {"ok": True}}],
        "usd": usd,
        "seconds": seconds,
        "tokens": {"input_tokens": 1000},
        "waits": waits,
    }


def a_run(number, variant="baseline", **changes):
    cases = {case_id: case(case_id) for case_id in CASES}
    records = []
    for case_id, what in zip(CASES, RUNS[number - 1], strict=True):
        made = result(what, usd=f"0.0{number}", seconds=float(number))
        records.append(
            {"id": case_id, "repetition": 1, "status": "ran", "result": made}
            | {"score": score.score_case(cases[case_id], made)}
        )
    results = {
        "format": 2, "state": "complete", "not_reached": [], "run_id": f"run-{number}",
        "commit": "c" * 40, "started": f"2026-10-11T1{number}:00:00+00:00",
        "ended": f"2026-10-11T1{number}:20:00+00:00", "written": "w", "variant": variant,
        "variant_files": {f"evals/variants/{variant}.yml": "v" * 64}, "model": "some-model",
        "system_prompt_sha256": "p" * 64, "golden_file": "golden.jsonl",
        "golden_sha256": "g" * 64, "split": "all", "repetitions": 1, "cases_selected": 6,
        "limits": {"max_usd_per_question": "0.25", "max_iterations": 6, "row_cap": 200},
        "budget_usd": "1.50", "spent_usd": f"0.{6 * number:02d}", "cases": cases,
        "records": records, "summary": score.summarize(records, cases),
    }  # fmt: skip
    results.update(changes)
    return results


def three():
    return [(f"2026-10-11_baseline_{n}.json", a_run(n)) for n in (1, 2, 3)]


def test_every_figure_per_run_and_over_the_three_with_the_spread():
    text = runs.render(three())
    assert text.startswith("# Evaluation over 3 runs: baseline\n")
    # All cases. Run 1: 5 of 6. Run 2: 3 of 6. Run 3: 5 of 5, because d-2 ended in an error.
    assert (
        "| Correct, all cases | 5 of 6 = 83.3% | 3 of 6 = 50.0% | 5 of 5 = 100.0% | 77.8% | "
        "50.0% | 100.0% | 50.0 points |"
    ) in text
    # Cases with an answer. Run 1: 3 of 4. Run 2: 2 of 4. Run 3: 3 of 3.
    assert (
        "| Execution accuracy (cases with an answer) | 3 of 4 = 75.0% | 2 of 4 = 50.0% | "
        "3 of 3 = 100.0% | 75.0% | 50.0% | 100.0% | 50.0 points |"
    ) in text
    # Refusals due: two per run. Run 2 answered one of them.
    assert (
        "| Refusal recall (cases with no answer that were refused) | 2 of 2 = 100.0% | "
        "1 of 2 = 50.0% | 2 of 2 = 100.0% | 83.3% | 50.0% | 100.0% | 50.0 points |"
    ) in text
    assert (
        "| Hallucination rate | 0 of 6 = 0.0% | 1 of 6 = 16.7% | 0 of 5 = 0.0% | 5.6% | 0.0% | "
        "16.7% | 16.7 points |"
    ) in text
    # Costs: each question of run n cost 0.0n dollars and took n seconds.
    cost = "| Cost per question, USD, mean | 0.01000 | 0.02000 | 0.03000 | 0.02000 | 0.01000 |"
    assert cost + " 0.03000 |" in text
    assert "| Seconds per question, mean | 1.00 | 2.00 | 3.00 | 2.00 | 1.00 | 3.00 |" in text
    assert "| Tokens per question, mean | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 |" in text


def test_dev_and_test_are_apart():
    text = runs.render(three())
    assert text.index("## All cases") < text.index("## `dev` cases") < text.index("## `test` cases")
    dev = text[text.index("## `dev` cases") : text.index("## `test` cases")]
    test = text[text.index("## `test` cases") :]
    # dev: d-1, d-2, d-u. Run 1: 3 of 3. Run 2: 2 of 3. Run 3: 2 of 2 (d-2 is an error).
    assert "| Correct, all cases | 3 of 3 = 100.0% | 2 of 3 = 66.7% | 2 of 2 = 100.0% |" in dev
    assert (
        "| Execution accuracy (cases with an answer) | 2 of 2 = 100.0% | 1 of 2 = 50.0% | "
        "1 of 1 = 100.0% | 83.3% | 50.0% | 100.0% | 50.0 points |"
    ) in dev
    # test: t-1, t-2, t-u. Run 1: 2 of 3. Run 2: 1 of 3. Run 3: 3 of 3.
    assert "| Correct, all cases | 2 of 3 = 66.7% | 1 of 3 = 33.3% | 3 of 3 = 100.0% |" in test
    assert (
        "| Execution accuracy (cases with an answer) | 1 of 2 = 50.0% | 1 of 2 = 50.0% | "
        "2 of 2 = 100.0% | 66.7% | 50.0% | 100.0% | 50.0 points |"
    ) in test
    # Over the three runs together, on test, cases with an answer: t-1 3 of 3, t-2 1 of 3.
    assert "| Execution accuracy (cases with an answer) | 4 of 6 = 66.7% | [" in test
    assert test.count("| 1 | 1 | 0 | 0 |") == 1  # t-1 in every run, t-2 in some


def test_errors_are_apart_and_in_no_figure():
    text = runs.render(three())
    assert "| Read this first |" in text and "ERRORS: in 2026-10-11_baseline_3.json" in text
    assert "| Ended in an error (in no figure of this report) | 0 | 0 | 1 | 1 |" in text
    assert "| Scored | 6 | 6 | 5 | 17 |" in text and "| Questions asked | 6 | 6 | 6 | 18 |" in text
    assert "| What the errors cost, USD | 0.00000 | 0.00000 | 0.03000 | 0.03000 |" in text
    assert "| Waits after a 429 or a 529 | 0 | 0 | 1 | 1 |" in text
    assert "| Seconds waited | 0 | 0 | 30 | 30 |" in text
    assert "| llm_error: APIConnectionError | 0 | 0 | 1 | 1 |" in text
    # d-2 was scored in two runs only: it is counted as such, not as a case that failed.
    dev = text[text.index("## `dev` cases") : text.index("## `test` cases")]
    assert "| Correct, all cases | 7 of 8 = 87.5% | [" in dev
    assert "| 2 | 0 | 0 | 1 |" in dev  # d-1 and d-u in every run; d-2 scored in fewer runs


def test_no_case_is_named_in_the_report():
    text = runs.render(three())
    for case_id in CASES:
        assert case_id not in text, case_id


def test_what_was_run_says_what_is_the_same_and_what_each_run_was():
    text = runs.render(three())
    for line in (
        "| Variant | baseline |",
        f"| Variant file evals/variants/baseline.yml | SHA-256 {'v' * 64} |",
        f"| Golden file | golden.jsonl, SHA-256 {'g' * 64} |",
        "| Per question | $0.25, 6 model calls, 200 rows |",
        "| Run | run-1 | run-2 | run-3 |",
        "| Spent, USD | 0.06 | 0.12 | 0.18 |",
        "| Questions asked | 6 of 6 | 6 of 6 | 6 of 6 |",
        "| File | 2026-10-11_baseline_1.json | 2026-10-11_baseline_2.json | "
        "2026-10-11_baseline_3.json |",
    ):
        assert line in text, line


def test_the_interval_resamples_cases_and_is_the_same_every_time():
    """Two cases always right and two always wrong, three runs each: 6 of 12 correct.

    Resampling answers would give a narrow interval around a half. Resampling cases cannot:
    four cases drawn from two that are all right and two that are all wrong give 0, 1/4,
    1/2, 3/4 or 1, so the 95% interval reaches both ends.
    """
    per_case = {"a": [True] * 3, "b": [True] * 3, "c": [False] * 3, "d": [False] * 3}
    assert runs.rate_over_runs(per_case) == 0.5
    low, high = runs.interval(per_case)
    assert (low, high) == (0.0, 1.0)
    assert runs.interval(per_case) == (low, high)  # a fixed seed
    assert runs.interval({"a": [True] * 3}) == (1.0, 1.0)
    assert runs.interval({}) is None and runs.rate_over_runs({}) is None
    # A case scored in fewer runs weighs by the runs it has.
    assert runs.rate_over_runs({"a": [True, True, True], "b": [False]}) == pytest.approx(3 / 4)


def test_majority_and_stability():
    assert runs.majority([True, True, False]) is True
    assert runs.majority([True, False, False]) is False
    assert runs.majority([True, False]) is False  # a tie is not a majority
    assert runs.majority([True]) is True and runs.majority([]) is None
    per_case = {"a": [True] * 3, "b": [True, False, True], "c": [False] * 3, "d": [True, True]}
    assert runs.stability(per_case, 3) == {
        "in every run": 1,
        "in some runs": 1,
        "in no run": 1,
        "scored in fewer runs than there were": 1,
    }


def test_files_that_are_not_runs_of_the_same_thing_are_refused(tmp_path, capsys):
    paths = []
    for n in (1, 2, 3):
        changes = {"golden_sha256": "x" * 64} if n == 2 else {}
        path = tmp_path / f"run{n}.json"
        path.write_text(json.dumps(a_run(n, **changes)))
        paths.append(str(path))
    assert runs.main([*paths, "--out", str(tmp_path / "report.md")]) == 2
    assert "golden_sha256 is not the same in run1.json and run2.json" in capsys.readouterr().err
    assert not (tmp_path / "report.md").exists()
    other = a_run(1, variant="other")
    assert "variant is not the same" in runs.differences([("a", a_run(1)), ("b", other)])[0]
    fewer = a_run(2)
    fewer["cases"].pop("t-u")
    assert runs.differences([("a", a_run(1)), ("b", fewer)]) == [
        "the cases are not the same in a and b"
    ]
    (tmp_path / "bad.json").write_text("[]")
    assert runs.main([str(tmp_path / "bad.json")]) == 2
    assert "not a results file" in capsys.readouterr().err


def test_the_command_writes_what_render_gives(tmp_path, capsys):
    paths = []
    for name, results in three():
        (tmp_path / name).write_text(json.dumps(results))
        paths.append(str(tmp_path / name))
    assert runs.main([*paths, "--out", str(tmp_path / "report.md")]) == 0
    assert (tmp_path / "report.md").read_text() == runs.render(three())
    assert runs.main(paths) == 0 and capsys.readouterr().out == runs.render(three())
