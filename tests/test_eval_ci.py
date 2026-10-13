"""The check that runs on a pull request: its 30 cases and its rule. No key, no model.

`make eval-ci` runs this file. The cases and the threshold are derived again from the
committed runs and have to come out as committed; the rule is tried on runs written by
hand; and the 30 cases are asked of a scripted model through the real runner, on the marts
fixture, with the limits the workflow uses.
"""

import json
import shutil
from decimal import Decimal

import pytest

from agent import llm
from evalkit import ci, runs
from tests.test_eval_run import GOLDEN, FromTheCase, go, setup  # noqa: F401 - setup is a fixture
from univ3_indexer import config

RESULTS = config.REPO_ROOT / "evals" / "results"
CASES_FILE = config.REPO_ROOT / "evals" / "ci_cases.json"
BASELINE_FILE = RESULTS / "ci_baseline.json"
VARIANT = config.REPO_ROOT / "evals" / "variants" / "ci.yml"
PICKED_FROM = [
    RESULTS / f"2026-10-12_baseline-regrounded_{run}.json"
    for run in ("38242644460", "38245003388", "38247610883")
]
SAME_TEXT = [
    RESULTS / f"2026-10-12_cache_{run}.json"
    for run in ("38280945667", "38280964508", "38280989734")
]
QUOTAS = {"template": 20, "hand": 5, "unanswerable": 5}
HAIKU = "claude-haiku-5-5"


@pytest.fixture(scope="module")
def committed():
    return json.loads(CASES_FILE.read_text()), json.loads(BASELINE_FILE.read_text())


# --- the cases ------------------------------------------------------------------------------


def test_the_cases_are_the_ones_the_code_picks_from_the_three_baseline_runs(committed):
    cases, _ = committed
    again = ci.select(runs.load(PICKED_FROM), QUOTAS, ci.DEFAULT_SEED)
    assert again == cases, "evals/ci_cases.json is not what `make eval-ci-cases` writes"
    assert cases["seed"] == 20261013
    assert cases["picked_from"] == [path.name for path in PICKED_FROM]
    # Another seed is another pick: the seed is what fixes it.
    other = ci.select(runs.load(PICKED_FROM), QUOTAS, ci.DEFAULT_SEED + 1)
    assert ci.ids_of(other) != ci.ids_of(cases)


def test_thirty_cases_twenty_five_five_all_dev_right_in_every_run_and_spread(committed):
    cases, _ = committed
    picked = cases["cases"]
    assert len(picked) == 30 == len({case["id"] for case in picked})
    by_kind = {kind: [c for c in picked if c["kind"] == kind] for kind in QUOTAS}
    assert {kind: len(found) for kind, found in by_kind.items()} == QUOTAS
    # dev could fill every kind, so no test case was taken.
    assert {case["split"] for case in picked} == {"dev"} and cases["from_another_split"] == {}
    stable = set(ci.right_in_all(runs.load(PICKED_FROM)))
    assert {case["id"] for case in picked} <= stable
    # Spread: all twelve template families are there and none has more than two; the hard
    # and the unanswerable cases are five different families each.
    families = [case["family"] for case in by_kind["template"]]
    assert len(set(families)) == 12 and max(families.count(f) for f in families) == 2
    assert len({case["family"] for case in by_kind["hand"]}) == 5
    assert len({case["family"] for case in by_kind["unanswerable"]}) == 5


def test_a_kind_that_dev_cannot_fill_takes_from_test_and_says_how_many():
    files = runs.load(PICKED_FROM)
    picked = ci.select(files, {"unanswerable": 12}, ci.DEFAULT_SEED)
    splits = [case["split"] for case in picked["cases"]]
    # dev has nine cases with no answer and eight of them were right in all three runs.
    assert splits.count("dev") == 8 and splits.count("test") == 4
    assert picked["from_another_split"] == {"unanswerable": 4}
    with pytest.raises(ci.CIError, match="hand: 500 cases are wanted"):
        ci.select(files, {"hand": 500}, ci.DEFAULT_SEED)


# --- what a run is compared with, and the noise ----------------------------------------------


def test_the_baseline_file_is_what_the_code_computes_and_the_threshold_comes_from_the_runs(
    committed,
):
    cases, base = committed
    again = ci.baseline(cases, runs.load(PICKED_FROM), runs.load(SAME_TEXT))
    assert again == base, "evals/results/ci_baseline.json is not what `make eval-ci-cases` writes"
    assert set(base["cases"]) == set(ci.ids_of(cases))
    assert all(entry == {"right_in": 3, "runs": 3} for entry in base["cases"].values())
    noise = base["noise"]
    # Six runs that sent the model the same text: the three the cases were picked from,
    # right on all thirty by construction, and the three with the prompt cached.
    assert [(run["variant"], run["wrong"]) for run in noise["runs"]] == [
        ("baseline", 0), ("baseline", 0), ("baseline", 0), ("cache", 2), ("cache", 1), ("cache", 0),
    ]  # fmt: skip
    assert (noise["worst"], noise["margin"], noise["max_wrong"]) == (2, 1, 3)
    cost = base["cost"]
    mean = Decimal(cost["mean_usd_per_question"])
    assert round(mean, 5) == Decimal("0.00178")
    assert Decimal(cost["max_mean_usd_per_question"]) == Decimal("0.0026767950")
    assert abs(Decimal(cost["max_mean_usd_per_question"]) - mean * Decimal("1.5")) < Decimal("1e-9")
    # The same text: the cached runs and the baseline have one system prompt.
    prompts = {results["system_prompt_sha256"] for _, results in runs.load(PICKED_FROM + SAME_TEXT)}
    assert len(prompts) == 1


# --- the rule ---------------------------------------------------------------------------------


def a_run(cases, wrong=0, errors=0, not_asked=0, usd="0.0017", state="complete"):
    records = []
    for number, case_id in enumerate(ci.ids_of(cases)):
        if number < not_asked:
            records.append({"id": case_id, "repetition": 1, "status": "not_run", "why": "budget"})
            continue
        is_error = not_asked <= number < not_asked + errors
        is_wrong = not_asked + errors <= number < not_asked + errors + wrong
        records.append(
            {
                "id": case_id,
                "repetition": 1,
                "status": "ran",
                "result": {"usd": usd, "status": "error" if is_error else "answered"},
                "score": {"error": is_error, "correct": not (is_error or is_wrong)},
            }
        )
    return {"state": state, "records": records}


@pytest.mark.parametrize(
    ("changes", "passes", "says"),
    [
        ({}, True, "| Cases wrong | 0 | at most 3 | yes |"),
        ({"wrong": 3}, True, "| Cases wrong | 3 | at most 3 | yes |"),
        ({"wrong": 4}, False, "| Cases wrong | 4 | at most 3 | **no** |"),
        ({"errors": 1}, False, "| No question ended in an error | 1 | 0 | **no** |"),
        ({"not_asked": 2}, False, "| Every case was asked | 28 of 30 | all 30 | **no** |"),
        ({"state": "unfinished"}, False, "30 of 30, run not finished | all 30 | **no** |"),
        ({"usd": "0.0026"}, True, "| Mean USD per question | 0.00260 | at most 0.00268 | yes |"),
        (
            {"usd": "0.0027"},
            False,
            "| Mean USD per question | 0.00270 | at most 0.00268 | **no** |",
        ),
    ],
)
def test_the_rule(committed, changes, passes, says):
    cases, base = committed
    passed, lines = ci.check(a_run(cases, **changes), cases, base)
    text = "\n".join(lines)
    assert passed is passes and says in text, text
    assert lines[0] == "### The regression check: " + ("passed" if passes else "FAILED")
    assert "the worst of 6 runs that sent the model the same text (2) plus 1" in text
    assert "not run again to make it pass" in text
    for case in ci.ids_of(cases):
        assert case not in text  # the summary names no case


def test_the_command_exits_with_one_when_the_run_fails_and_appends_the_summary(
    committed, tmp_path, capsys
):
    cases, _ = committed
    good, bad, summary = tmp_path / "good.json", tmp_path / "bad.json", tmp_path / "summary.md"
    good.write_text(json.dumps(a_run(cases)))
    bad.write_text(json.dumps(a_run(cases, wrong=4)))
    common = [
        "--cases",
        str(CASES_FILE),
        "--baseline",
        str(BASELINE_FILE),
        "--summary",
        str(summary),
    ]
    assert ci.main(["check", str(good), *common]) == 0
    assert ci.main(["check", str(bad), *common]) == 1
    assert summary.read_text().count("### The regression check") == 2
    assert "FAILED" in capsys.readouterr().out
    assert ci.main(["check", str(tmp_path / "absent.json"), *common]) == ci.SETUP_ERROR


# --- the thirty cases through the real runner, with a scripted model -------------------------


def the_check(setup, model, *extra):  # noqa: F811 - the fixture's value
    """What the workflow does: the variant `ci`, the picked cases, 0.25 USD for the run."""
    shutil.copy(VARIANT, setup["tmp"] / "variants" / "ci.yml")
    arguments = ["--variant", "ci", "--split", "all", "--ids", str(CASES_FILE), "--max-usd", "0.25"]
    return go(setup, model, *arguments, *extra)


def test_the_thirty_cases_run_under_the_cap_and_a_model_that_is_right_passes(
    setup,  # noqa: F811
    committed,
):
    cases, base = committed
    model = FromTheCase(HAIKU)
    code, results = the_check(setup, model)
    assert code == 0
    assert sorted(model.asked) == sorted(ci.ids_of(cases)) and len(model.asked) == 30
    assert results["limits"]["max_usd_per_question"] == "0.05" and results["budget_usd"] == "0.25"
    assert results["limits"]["max_iterations"] == 3  # of the test's warehouse file
    assert Decimal(results["spent_usd"]) < Decimal("0.25")
    passed, lines = ci.check(results, cases, base)
    assert passed, "\n".join(lines)


def test_a_model_that_got_worse_fails_the_check_and_one_within_the_noise_does_not(
    setup,  # noqa: F811
    committed,
):
    cases, base = committed
    ids = ci.ids_of(cases)
    _, results = the_check(setup, FromTheCase(HAIKU, wrong=ids[:4]))
    passed, lines = ci.check(results, cases, base)
    assert not passed and "| Cases wrong | 4 | at most 3 | **no** |" in "\n".join(lines)
    setup["out"].unlink()
    _, results = the_check(setup, FromTheCase(HAIKU, wrong=ids[:3]))
    assert ci.check(results, cases, base)[0]


def test_a_question_that_ends_in_an_error_fails_the_check(setup, committed):  # noqa: F811
    cases, base = committed
    _, results = the_check(setup, FromTheCase(HAIKU, broken=ci.ids_of(cases)[:1]))
    passed, lines = ci.check(results, cases, base)
    assert not passed and "| No question ended in an error | 1 | 0 | **no** |" in "\n".join(lines)


def test_a_run_that_stops_on_its_budget_fails_the_check_it_is_not_a_score(setup, committed):  # noqa: F811
    cases, base = committed
    # A model that uses 90,000 input tokens a call: a question costs about 0.018 on Haiku,
    # so the run's 0.25 cannot hold a whole question's ceiling long before the thirtieth.
    model = FromTheCase(HAIKU, usage=llm.Usage(input_tokens=90_000, output_tokens=100))
    _, results = the_check(setup, model)
    assert 0 < len(model.asked) < 30
    passed, lines = ci.check(results, cases, base)
    text = "\n".join(lines)
    assert (
        not passed
        and f"| Every case was asked | {len(model.asked)} of 30 | all 30 | **no** |" in text
    )
