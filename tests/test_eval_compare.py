"""Two variants compared, with results built by hand. No model, no server.

The six cases and the three baseline runs are the ones of tests/test_eval_runs.py. The
variant's runs are written below, and every figure is counted from the two tables by hand.
"""

import json

import pytest

from evalkit import compare, runs
from tests import test_eval_runs as base

#        d-1      d-2      t-1      t-2      d-u        t-u
AFTER = [
    ("right", "right", "right", "right", "refused", "refused"),
    ("right", "right", "wrong", "right", "refused", "refused"),
    ("right", "right", "right", "right", "refused", "refused"),
]


def runs_of(matrix, variant, monkeypatch, **changes):
    monkeypatch.setattr(base, "RUNS", matrix)
    files = []
    for n in range(1, len(matrix) + 1):
        results = base.a_run(n, variant, **changes)
        files.append((f"2026-10-11_{variant}_{n}.json", results))
    return files


@pytest.fixture
def two(monkeypatch):
    before = runs_of(list(base.RUNS), "baseline", monkeypatch)
    after = runs_of(AFTER, "notes", monkeypatch, system_prompt_sha256="q" * 64)
    return before, after


def test_execution_accuracy_on_test_per_run_with_the_mean_the_ends_and_an_interval(two):
    text = compare.render(*two)
    assert text.startswith("# baseline against notes\n")
    test = text[text.index("## On `test`") : text.index("## On `dev`")]
    # baseline on t-1, t-2: 1 of 2, 1 of 2, 2 of 2. notes: 2 of 2, 1 of 2, 2 of 2.
    runs_of_three = "1 of 2 = 50.0% | 1 of 2 = 50.0% | 2 of 2 = 100.0%"
    assert f"| baseline | {runs_of_three} | 66.7% | 50.0% | 100.0% | [" in test
    runs_of_three = "2 of 2 = 100.0% | 1 of 2 = 50.0% | 2 of 2 = 100.0%"
    assert f"| notes | {runs_of_three} | 83.3% | 50.0% | 100.0% | [" in test
    assert "| notes minus baseline, means of the runs | +16.7 points |" in test
    assert "| Spread between the runs of baseline | 50.0 points |" in test
    assert "| Spread between the runs of notes | 50.0 points |" in test
    assert "| 95% interval of the difference (paired bootstrap over cases) | [" in test


def test_the_sentence_says_it_is_not_larger_than_the_spread_when_it_is_not(two):
    text = compare.render(*two)
    assert (
        "On `test`, execution accuracy went from 66.7% to 83.3%, a difference of +16.7 points; "
        "the runs of one variant differ among themselves by up to 50.0 points, so the "
        "difference is not larger than the spread between runs: these runs do not show that "
        "the change did anything."
    ) in text


def test_the_sentence_says_it_is_larger_when_it_is(monkeypatch):
    steady = [("right", "right", "right", "wrong", "refused", "refused")] * 3
    better = [("right", "right", "right", "right", "refused", "refused")] * 3
    before = runs_of(steady, "baseline", monkeypatch)
    after = runs_of(better, "notes", monkeypatch)
    text = compare.render(before, after)
    assert (
        "On `test`, execution accuracy went from 50.0% to 100.0%, a difference of +50.0 points; "
        "the runs of one variant differ among themselves by up to 0.0 points, so the "
        "difference is larger than the spread between runs."
    ) in text
    assert "do not show" not in text
    # A change that makes it worse is larger than the spread too, and negative.
    worse = compare.render(after, before)
    assert "a difference of -50.0 points" in worse and "is larger than the spread" in worse


def test_case_by_case_by_majority_fixed_broke_and_stayed(two):
    """t-1: right in 3 of 3, then in 2 of 3: stayed right. t-2: right in 1 of 3, then in
    3 of 3: fixed. t-u: refused in 2 of 3, then in 3 of 3: stayed right."""
    text = compare.render(*two)
    assert "| Cases with an answer | 1 | 0 | 1 | 0 | 0 |" in text
    assert "| All cases | 1 | 0 | 2 | 0 | 0 |" in text
    before, after = two
    assert compare.moves(
        {"a": [True, True, False], "b": [False] * 3, "c": [True] * 3, "d": [False] * 3, "e": []},
        {
            "a": [False] * 3,
            "b": [True] * 3,
            "c": [True] * 3,
            "d": [False, True, False],
            "e": [True],
        },
    ) == {"fixed": 1, "broke": 1, "stayed right": 1, "stayed wrong": 1, "not comparable": 1}


def test_refusals_hallucinations_valid_sql_dollars_and_seconds_for_both(two):
    text = compare.render(*two)
    test = text[text.index("## On `test`") : text.index("## On `dev`")]
    # On test, t-u: baseline refused, answered, refused. Recall 1, 0, 1: mean 66.7%.
    assert "| Refusal recall | 66.7% (0.0% to 100.0%) | 100.0% (100.0% to 100.0%) |" in test
    # Hallucination: baseline run 2 answered t-u, 1 of 3 cases. Mean of 0, 1/3, 0.
    assert "| Hallucination rate | 11.1% (0.0% to 33.3%) | 0.0% (0.0% to 0.0%) |" in test
    assert "| Refusals made | 1 / 0 / 1 | 1 / 1 / 1 |" in test
    assert "| Valid SQL (queries that ran) | 100.0% (100.0% to 100.0%) |" in test
    dollars = "0.02000 (0.01000 to 0.03000)"
    assert f"| Dollars per question, mean | {dollars} | {dollars} |" in test
    assert "| Seconds per question, mean | 2.00 (1.00 to 3.00) | 2.00 (1.00 to 3.00) |" in test


def test_dev_is_in_a_table_of_its_own_and_says_what_it_is(two):
    text = compare.render(*two)
    dev = text[text.index("## On `dev`: the cases the change was designed on") :]
    assert "A gain here is expected and is not evidence that the change works." in dev
    # baseline on d-1, d-2: 2 of 2, 1 of 2, 1 of 1 (d-2 is an error in run 3). notes: 2 of 2.
    assert "| baseline | 2 of 2 = 100.0% | 1 of 2 = 50.0% | 1 of 1 = 100.0% | 83.3% |" in dev
    assert "| notes | 2 of 2 = 100.0% | 2 of 2 = 100.0% | 2 of 2 = 100.0% | 100.0% |" in dev
    assert "ERRORS: in 2026-10-11_baseline_3.json" in text
    for case_id in base.CASES:
        assert case_id not in text, case_id


def test_what_differs_between_the_two_is_printed(two):
    text = compare.render(*two)
    assert "| What differs between the two | variant_files, system_prompt_sha256 |" in text
    assert f"| Golden file | golden.jsonl, SHA-256 {'g' * 64} |" in text
    assert "| Runs | 3 | 3 |" in text


def test_the_largest_failure_category_left_on_dev(two):
    text = compare.render(*two)
    assert "Not classified: no failures file was given." in text
    failures = [{"category": c} for c in ("date filter", "wrong table", "date filter", "other")]
    text = compare.render(*two, failures)
    assert "| date filter | 2 |" in text and "| other | 1 |" in text
    assert "Largest: date filter, with 2 cases." in text
    tied = compare.render(*two, [{"category": "a"}, {"category": "b"}])
    assert "Largest: a and b, with 1 cases." in tied
    assert "No case is left in the file." in compare.render(*two, [])


def test_the_interval_of_the_difference_is_paired_and_fixed():
    """Four cases. Two are always right before and after; two are always wrong before and
    always right after. Whatever cases are drawn, the rate after is 1, so the difference is
    1 minus the share of always-right cases drawn: between 0 and 1, never negative."""
    before = {"a": [True] * 3, "b": [True] * 3, "c": [False] * 3, "d": [False] * 3}
    after = {name: [True] * 3 for name in before}
    low, high = compare.difference_interval(before, after)
    assert (low, high) == (0.0, 1.0)
    assert compare.difference_interval(before, after) == (low, high)
    assert compare.difference_interval(before, before) == (0.0, 0.0)  # no change, no interval
    assert compare.difference_interval({}, after) is None
    # Cases only one of the two was scored on are left out.
    assert compare.difference_interval({"a": [True]}, {"a": [True], "z": [False]}) == (0.0, 0.0)


def test_two_variants_on_different_golden_files_are_not_compared(two, tmp_path, capsys):
    before, after = two
    paths = {"baseline": [], "variant": []}
    for group, files in (("baseline", before), ("variant", after)):
        for name, results in files:
            if group == "variant":
                results = {**results, "golden_sha256": "x" * 64}
            (tmp_path / name).write_text(json.dumps(results))
            paths[group].append(str(tmp_path / name))
    arguments = ["--baseline", *paths["baseline"], "--variant", *paths["variant"]]
    assert compare.main([*arguments, "--out", str(tmp_path / "report.md")]) == 2
    assert "cannot be compared: golden_sha256 is not the same" in capsys.readouterr().err
    assert not (tmp_path / "report.md").exists()


def test_the_command_writes_what_render_gives(two, tmp_path, capsys):
    before, after = two
    paths = {"baseline": [], "variant": []}
    for group, files in (("baseline", before), ("variant", after)):
        for name, results in files:
            (tmp_path / name).write_text(json.dumps(results))
            paths[group].append(str(tmp_path / name))
    failures = tmp_path / "failures.csv"
    failures.write_text("id,category\nd-9,date filter\n")
    arguments = ["--baseline", *paths["baseline"], "--variant", *paths["variant"]]
    out = str(tmp_path / "r.md")
    assert compare.main([*arguments, "--failures", str(failures), "--out", out]) == 0
    written = (tmp_path / "r.md").read_text()
    assert written == compare.render(before, after, [{"id": "d-9", "category": "date filter"}])
    assert "Largest: date filter, with 1 cases." in written
    failures.write_text("id,kind\nd-9,x\n")
    assert compare.main([*arguments, "--failures", str(failures)]) == 2
    assert "no category column" in capsys.readouterr().err
    assert runs.differences(before) == []


def test_the_cases_with_no_answer_have_a_table_of_their_own(two):
    """t-u: the baseline refused it, gave a value, refused it; the variant refused it three
    times. Refused by majority in both, so it stayed right. d-u was refused six times."""
    text = compare.render(*two)
    test = text[text.index("## On `test`") : text.index("## On `dev`")]
    assert "| Cases with no answer | 0 | 0 | 1 | 0 | 0 |" in test
    one_of_one = "1 of 1 = 100.0% [20.7%, 100.0%]"
    assert "| Cases with no answer on `test` | baseline | notes |" in test
    assert f"Wilson interval | {one_of_one} | {one_of_one} |" in test
    assert (
        "| Ended without an answer (the cap, or the model stopped), all runs | 0 of 3 | 0 of 3 |"
        in test
    )
    assert "| Gave a value where a refusal was due, all runs | 1 of 3 | 0 of 3 |" in test
    dev = text[text.index("## On `dev`") :]
    assert "| Cases with no answer on `dev` | baseline | notes |" in dev
    assert "| Gave a value where a refusal was due, all runs | 0 of 3 | 0 of 3 |" in dev
    before, _ = two
    for _, results in before:
        for record in results["records"]:
            if record["id"] == "t-u" and record["result"]["status"] == "answered":
                record["result"]["status"] = "no_answer"
                record["result"]["answer"] = None
                record["score"] = compare.score.score_case(
                    results["cases"]["t-u"], record["result"]
                )
    due = compare.refusals_due(before, "test")
    assert due["ended"] == {"no_answer": 1, "gave a value": 0, "answers": 3}
    assert (due["by_majority"]["k"], due["by_majority"]["n"]) == (1, 1)
