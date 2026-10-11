"""The scorer, as tables: every rule with a case on each side of it. No model, no network."""

import math

import pytest

from evalkit import score

SUM = {"abs": "0.01", "rel": "0.001"}
EXACT = {"abs": "0", "rel": "0"}
RATIO = {"abs": "0", "rel": "0.005"}


def case(answer_type="number", expected="100", accepted=(), tolerance=SUM, kind="template"):
    if answer_type == "refusal":
        expected, tolerance, kind = None, None, "unanswerable"
    if answer_type in ("label", "date", "list"):
        tolerance = None
    return {
        "id": "c-1",
        "kind": kind,
        "family": "f",
        "answer_type": answer_type,
        "expected": expected,
        "accepted": list(accepted),
        "tolerance": tolerance,
    }


def result(status="answered", value=None, calls=(), usd="0.01", seconds=1.0, tokens=1000, **more):
    answer = None if status == "no_answer" else {"value": value, **more}
    return {
        "status": status,
        "answer": answer,
        "tool_calls": [{"name": name, "summary": {"ok": ok}} for name, ok in calls],
        "usd": usd,
        "seconds": seconds,
        "tokens": {"input_tokens": tokens, "output_tokens": 0},
    }


# --- correct: numbers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected", "tolerance", "right"),
    [
        # A sum passes within a cent OR within a tenth of a percent, whichever is looser.
        ("100", "100", SUM, True),
        ("100.01", "100", SUM, True),  # a cent off: the absolute bound
        ("100.1", "100", SUM, True),  # exactly 0.1% off: the relative bound, inclusive
        ("100.11", "100", SUM, False),  # past both
        ("99.9", "100", SUM, True),
        ("99.89", "100", SUM, False),
        ("0.01", "0", SUM, True),  # at zero only the absolute bound can pass
        ("0.011", "0", SUM, False),
        ("1000000.5", "1000000", SUM, True),  # 50 cents is far within 0.1% of a million
        ("1001001", "1000000", SUM, False),
        # A count is exact.
        ("7785", "7785", EXACT, True),
        ("7786", "7785", EXACT, False),
        (7785, "7785", EXACT, True),  # a JSON number is as good as text
        (7785.0, "7785", EXACT, True),
        ("7785.000", "7785", EXACT, True),
        # A ratio passes within half a percent, relative only.
        ("2524.65", "2524.651342351471731116", RATIO, True),
        ("2537.27", "2524.651342351471731116", RATIO, True),  # +0.4998%
        ("2537.3", "2524.651342351471731116", RATIO, False),  # +0.501%
        ("-72.1", "-72.129075263530858117", RATIO, True),  # the sign is part of the value
        ("72.1", "-72.129075263530858117", RATIO, False),
        ("0.0001", "0", RATIO, False),  # a ratio of zero has no slack at all
        ("0", "0", RATIO, True),
        # What is not a number is wrong, not an error.
        ("about 100", "100", SUM, False),
        (None, "100", SUM, False),
        (True, "100", SUM, False),
        ("nan", "100", SUM, False),
        (["100"], "100", SUM, False),
    ],
)
def test_a_number_within_either_bound_is_right(value, expected, tolerance, right):
    assert score.number_matches(value, expected, tolerance) is right
    scored = score.score_case(case(expected=expected, tolerance=tolerance), result(value=value))
    assert scored["correct"] is right


def test_an_accepted_value_is_as_right_as_the_expected_one():
    two_readings = case(expected="1032736412.385572", accepted=["865373951.656246"])
    assert score.score_case(two_readings, result(value="865373951.66"))["correct"]
    assert score.score_case(two_readings, result(value="1032736412.38"))["correct"]
    assert not score.score_case(two_readings, result(value="900000000"))["correct"]


# --- correct: labels, dates, lists -----------------------------------------------------------


@pytest.mark.parametrize(
    ("answer_type", "value", "expected", "right"),
    [
        ("label", "Wednesday", "Wednesday", True),
        ("label", "  wednesday \n", "Wednesday", True),  # trimmed and case-folded
        ("label", "WEDNESDAY", "Wednesday", True),
        ("label", "Wed", "Wednesday", False),  # exactly, after that
        ("label", "Wednesday.", "Wednesday", False),
        ("label", "A/B 0.05%", "A/B 0.05%", True),
        ("label", "B/A 0.05%", "A/B 0.05%", False),
        ("label", None, "Wednesday", False),
        ("label", ["Wednesday"], "Wednesday", False),
        ("date", "2026-08-22", "2026-08-22", True),
        ("date", " 2026-08-22 ", "2026-08-22", True),
        ("date", "2026-08-22T00:00:00", "2026-08-22", True),  # the same day, as a timestamp
        ("date", "2026-08-22T13:00:00", "2026-08-22", False),  # a moment is not a day
        ("date", "2026-08-23", "2026-08-22", False),
        ("date", "22 August 2026", "2026-08-22", False),  # compared as a date: ISO or wrong
        ("date", 20260822, "2026-08-22", False),
        ("list", ["2026-08-19", "2026-08-21", "2026-08-20"], ["2026-08-19", "2026-08-21", "2026-08-20"], True),
        ("list", ["2026-08-19", "2026-08-20", "2026-08-21"], ["2026-08-19", "2026-08-21", "2026-08-20"], False),  # the right days, the wrong order
        ("list", ["2026-08-19", "2026-08-21"], ["2026-08-19", "2026-08-21", "2026-08-20"], False),
        ("list", ["2026-08-19", "2026-08-21", "2026-08-20", "2026-09-11"], ["2026-08-19", "2026-08-21", "2026-08-20"], False),
        ("list", ["a/b 0.01%", " A/B 0.05% "], ["A/B 0.01%", "A/B 0.05%"], True),  # labels fold
        ("list", [1, "2", 3.0], ["1", "2", "3"], True),  # numbers compare as numbers
        ("list", ["1", "2", "3.01"], ["1", "2", "3"], False),  # and exactly
        ("list", "2026-08-19, 2026-08-21, 2026-08-20", ["2026-08-19", "2026-08-21", "2026-08-20"], False),
    ],
)  # fmt: skip
def test_labels_dates_and_lists(answer_type, value, expected, right):
    assert score.value_matches(value, expected, answer_type, None) is right
    scored = score.score_case(case(answer_type, expected), result(value=value))
    assert scored["correct"] is right


# --- correct: refusing ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer_type", "status", "value", "correct", "hallucinated"),
    [
        # A case with an answer: a right value is right, refusing it is wrong.
        ("number", "answered", "100", True, False),
        ("number", "refused", None, False, False),
        ("number", "no_answer", None, False, False),
        ("number", "answered", "5", False, False),  # wrong, but it came out of the data
        # Right AND ungrounded counts in both places.
        ("number", "ungrounded", "100", True, True),
        ("number", "ungrounded", "5", False, True),
        # A case with no answer: refusing is right, anything else is wrong.
        ("refusal", "refused", None, True, False),
        ("refusal", "answered", "0", False, True),  # answered when it should have refused
        ("refusal", "ungrounded", "0", False, True),
        ("refusal", "no_answer", None, False, False),  # not right, and not a made-up answer
    ],
)
def test_refusing_and_where_an_answer_came_from(answer_type, status, value, correct, hallucinated):
    scored = score.score_case(case(answer_type), result(status, value))
    assert scored["correct"] is correct and scored["hallucinated"] is hallucinated
    assert scored["should_refuse"] is (answer_type == "refusal")
    assert scored["refused"] is (status == "refused")
    assert scored["ungrounded"] is (status == "ungrounded")


def test_queries_that_ran_and_queries_that_failed_are_counted_per_question():
    calls = [
        ("describe_schema", True),
        ("run_sql", False),
        ("run_sql", True),
        ("submit_answer", True),
    ]
    scored = score.score_case(case(), result(value="100", calls=calls))
    assert (scored["queries"], scored["queries_ok"]) == (2, 1)
    scored = score.score_case(case(), result(value="100", calls=[("describe_schema", False)]))
    assert (scored["queries"], scored["queries_ok"]) == (0, 0)


# --- the Wilson interval, against values worked out by hand ----------------------------------


def test_the_wilson_interval_against_values_computed_by_hand():
    """z = 1.959964, so z^2 = 3.841459.

    8 of 10: p = 0.8.
      denominator = 1 + 3.841459 / 10                       = 1.3841459
      centre      = (0.8 + 3.841459 / 20) / 1.3841459       = 0.9920729 / 1.3841459 = 0.716741
      half        = 1.959964 * sqrt(0.8 * 0.2 / 10 + 3.841459 / 400) / 1.3841459
                  = 1.959964 * sqrt(0.016 + 0.0096036) / 1.3841459
                  = 1.959964 * 0.160011 / 1.3841459         = 0.226575
      interval    = [0.490166, 0.943316]

    0 of 10: p = 0. centre = 0.1920729 / 1.3841459 = 0.138766; half = 1.959964 *
      sqrt(0.0096036) / 1.3841459 = 1.959964 * 0.0979982 / 1.3841459 = 0.138766, so
      [0, 0.277533]. 10 of 10 is its mirror: [0.722467, 1].

    50 of 100: p = 0.5. denominator = 1.03841459; centre = 0.5 exactly; half = 1.959964 *
      sqrt(0.0025 + 0.000096036) / 1.03841459 = 1.959964 * 0.0509513 / 1.03841459 = 0.096168,
      so [0.403832, 0.596168].
    """
    for (k, n), (low, high) in {
        (8, 10): (0.490166, 0.943316),
        (0, 10): (0.0, 0.277533),
        (10, 10): (0.722467, 1.0),
        (50, 100): (0.403832, 0.596168),
    }.items():
        got = score.wilson(k, n)
        assert got[0] == pytest.approx(low, abs=2e-5) and got[1] == pytest.approx(high, abs=2e-5)
    assert score.wilson(0, 0) is None
    assert score.proportion(0, 0) == {"k": 0, "n": 0, "value": None, "low": None, "high": None}
    p = score.proportion(8, 10)
    assert (p["k"], p["n"], p["value"]) == (8, 10, 0.8) and p["low"] < 0.8 < p["high"]
    # It never leaves [0, 1], and it narrows as the sample grows.
    assert score.wilson(1, 1)[1] == 1.0 and score.wilson(0, 1)[0] == 0.0
    narrow, wide = score.wilson(800, 1000), score.wilson(8, 10)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]


def test_the_95th_percentile_is_by_nearest_rank():
    assert score.percentile_95([]) is None
    assert score.percentile_95([7.0]) == 7.0
    assert score.percentile_95(list(range(1, 21))) == 19  # ceil(0.95 * 20) = 19th value
    assert score.percentile_95(list(range(1, 101))) == 95
    assert score.percentile_95([5, 1, 3]) == 5  # ceil(2.85) = 3rd of three, sorted
    assert score.distribution([1.0, 2.0, 9.0]) == {"mean": 4.0, "median": 2.0, "p95": 9.0}
    assert score.distribution([]) == {"mean": None, "median": None, "p95": None}


# --- the figures of a run ---------------------------------------------------------------------


def records_of(*runs):
    """(case, result, repetition) triples as the runner writes them; None means not run."""
    cases, records = {}, []
    for n, (c, r, repetition) in enumerate(runs):
        c = {**c, "id": c.get("label", f"c-{n}")}
        c.pop("label", None)
        cases[c["id"]] = c
        if r is None:
            records.append({"id": c["id"], "repetition": repetition, "status": "not_run"})
        else:
            records.append(
                {"id": c["id"], "repetition": repetition, "status": "ran", "result": r,
                 "score": score.score_case(c, r)}
            )  # fmt: skip
    return records, cases


def test_the_figures_of_a_small_run_counted_by_hand():
    """Ten questions. Six have an answer, four do not.

    with an answer:  right, right, right and ungrounded, wrong, refused (wrong), no answer
    with no answer:  refused, refused, answered (wrong), no answer (wrong)
    """
    ok, bad = ("run_sql", True), ("run_sql", False)
    template, hand = case(kind="template"), {**case(kind="hand"), "family": "g"}
    none = case("refusal")
    records, cases = records_of(
        (template, result(value="100", calls=[ok], usd="0.01", seconds=1, tokens=100), 1),
        (template, result(value="100.05", calls=[bad, ok], usd="0.02", seconds=2, tokens=200), 1),
        (template, result("ungrounded", "100", calls=[ok], usd="0.03", seconds=3, tokens=300), 1),
        (hand, result(value="7", calls=[ok, ok], usd="0.04", seconds=4, tokens=400), 1),
        (hand, result("refused", calls=[ok], usd="0.05", seconds=5, tokens=500), 1),
        (hand, result("no_answer", calls=[bad, bad], usd="0.06", seconds=6, tokens=600), 1),
        (none, result("refused", calls=[ok], usd="0.07", seconds=7, tokens=700), 1),
        (none, result("refused", usd="0.08", seconds=8, tokens=800), 1),
        (none, result(value="0", calls=[ok], usd="0.09", seconds=9, tokens=900), 1),
        (none, result("no_answer", usd="0.10", seconds=10, tokens=1000), 1),
    )
    summary = score.summarize(records, cases)
    assert (summary["records"], summary["ran"], summary["not_run"], summary["partial"]) == (
        10,
        10,
        0,
        False,
    )
    f = summary["overall"]
    counts = lambda p: (p["k"], p["n"])  # noqa: E731
    assert counts(f["correct"]) == (5, 10)  # three values and two refusals
    assert counts(f["execution_accuracy"]) == (3, 6)  # over the cases with an answer
    assert counts(f["valid_sql"]) == (8, 11)  # queries that ran over queries sent
    assert counts(f["questions_with_a_failed_query"]) == (2, 10)
    assert counts(f["hallucination_rate"]) == (2, 10)  # one ungrounded, one answered a refusal
    assert counts(f["ungrounded"]) == (1, 10)
    table = f["refusals"]
    assert (table["should_and_did"], table["should_and_did_not"]) == (2, 2)
    assert (table["should_not_and_did"], table["should_not_and_did_not"]) == (1, 5)
    assert counts(table["precision"]) == (2, 3)  # of three refusals made, two were due
    assert counts(table["recall"]) == (2, 4)  # of four due, two were made
    assert f["usd"]["total"] == "0.55" and f["usd"]["per_correct_answer"] == "0.11"
    assert f["usd"]["mean"] == pytest.approx(0.055) and f["usd"]["median"] == pytest.approx(0.055)
    assert f["usd"]["p95"] == pytest.approx(0.10)
    assert f["seconds"] == {"mean": 5.5, "median": 5.5, "p95": 10.0}
    assert f["tokens"] == {"mean": 550.0, "median": 550.0, "p95": 1000.0}
    assert f["correct"]["low"] == pytest.approx(score.wilson(5, 10)[0])
    # Broken down by kind and by family, with the same definitions.
    assert set(summary["by_kind"]) == {"hand", "template", "unanswerable"}
    assert counts(summary["by_kind"]["template"]["correct"]) == (3, 3)
    assert counts(summary["by_kind"]["hand"]["correct"]) == (0, 3)
    assert counts(summary["by_kind"]["unanswerable"]["correct"]) == (2, 4)
    assert counts(summary["by_kind"]["unanswerable"]["execution_accuracy"]) == (0, 0)
    assert set(summary["by_family"]) == {"hand / g", "template / f", "unanswerable / f"}
    assert counts(summary["by_family"]["hand / g"]["valid_sql"]) == (3, 5)
    assert "repetitions" not in summary


def test_a_case_that_was_not_run_is_in_no_figure_and_makes_the_run_partial():
    records, cases = records_of(
        ({**case(), "label": "a"}, result(value="100"), 1),
        ({**case(), "label": "b"}, None, 1),
        ({**case("refusal"), "label": "c"}, None, 1),
    )
    summary = score.summarize(records, cases)
    assert (summary["records"], summary["ran"], summary["not_run"]) == (3, 1, 2)
    assert summary["partial"] is True
    assert (summary["overall"]["correct"]["k"], summary["overall"]["correct"]["n"]) == (1, 1)
    assert summary["overall"]["refusals"]["recall"]["n"] == 0


def test_with_repetitions_each_case_says_how_many_runs_passed_and_the_spread_between_runs():
    a, b, c = ({**case(), "label": name} for name in "abc")
    right, wrong = result(value="100"), result(value="1")
    records, cases = records_of(
        (a, right, 1), (b, right, 1), (c, wrong, 1),
        (a, right, 2), (b, wrong, 2), (c, wrong, 2),
        (a, right, 3), (b, wrong, 3), (c, wrong, 3),
    )  # fmt: skip
    rep = score.summarize(records, cases)["repetitions"]
    assert rep["count"] == 3
    assert rep["per_case"] == {
        "a": {"passed": 3, "runs": 3},
        "b": {"passed": 1, "runs": 3},
        "c": {"passed": 0, "runs": 3},
    }
    assert (rep["always_passed"], rep["sometimes_passed"], rep["never_passed"]) == (1, 1, 1)
    assert [(p["k"], p["n"]) for p in rep["correct_per_run"]] == [(2, 3), (1, 3), (1, 3)]
    assert rep["spread"]["highest"] == pytest.approx(2 / 3)
    assert rep["spread"]["lowest"] == pytest.approx(1 / 3)
    assert rep["spread"]["range"] == pytest.approx(1 / 3)
    assert math.isclose(score.summarize(records, cases)["overall"]["correct"]["value"], 4 / 9)
