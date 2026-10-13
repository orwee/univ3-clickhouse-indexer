"""The cost table and the two simulated routers, on results built by hand. No model.

The six cases and the three runs are the ones of tests/test_eval_runs.py: run n costs
0.0n USD and n seconds for every question. The strong variant's one run is written below.
"""

from decimal import Decimal

from evalkit import cost
from tests import test_eval_runs as base

#          d-1      d-2      t-1      t-2      d-u        t-u
STRONG = ("right", "right", "right", "right", "refused", "refused")


def strong_run(monkeypatch, split="all"):
    monkeypatch.setattr(base, "RUNS", [STRONG])
    results = base.a_run(1, "strong", model="a-bigger-model", split=split)
    for record in results["records"]:
        record["result"]["usd"] = "0.50"
    if split != "all":
        keep = [r for r in results["records"] if results["cases"][r["id"]]["split"] == split]
        results["records"] = keep
    return ("2026-10-11_strong_9.json", results)


def test_dollars_seconds_and_right_answers_per_split_with_errors_in_no_figure():
    files = base.three()
    # dev: d-1, d-2, d-u. Run 3 ended d-2 in an error, so it scores two questions there.
    assert cost.figures(files[0][1], "dev") == {
        "questions": 3, "usd": Decimal("0.03"), "seconds": 3.0, "correct": 3,
    }  # fmt: skip
    assert cost.figures(files[2][1], "dev")["questions"] == 2
    row = cost.row_of("baseline", files, "dev")
    # 0.01, 0.02 and 0.03 per question; 0.03 + 0.06 + 0.06 = 0.15 spent, 7 right answers
    # of 8; 3 x 1 + 3 x 2 + 2 x 3 = 15 seconds over 8 questions.
    assert row == [
        "baseline", 3, 3, "0.02000 (0.01000 to 0.03000)", "0.02143", "1.88", "7 of 8 = 87.5%",
        1, "-",
    ]  # fmt: skip
    # The question that ended in an error is in the column of its own and in no figure;
    # and when a provider said what it billed, that is summed over every question billed.
    for record in files[2][1]["records"]:
        record["result"]["billed_usd"] = "0.005"
    row = cost.row_of("baseline", files, "dev")
    assert row[-2:] == [1, "0.015000 over 3 questions"]


def test_a_run_of_one_split_is_in_that_split_and_in_no_other_table(monkeypatch):
    files = base.three()
    only_dev = strong_run(monkeypatch, split="dev")
    text = cost.render([("baseline", files), ("strong", [only_dev])])
    everything = text[text.index("## All cases") : text.index("## `dev` cases")]
    assert "| baseline |" in everything and "| strong |" not in everything
    dev = text[text.index("## `dev` cases") : text.index("## `test` cases")]
    assert "| strong | 1 | 3 | 0.50000 | 0.50000 |" in dev and "3 of 3 = 100.0%" in dev
    assert "| strong |" not in text[text.index("## `test` cases") :]
    assert "a-bigger-model" in text and "some-model" in text


def test_the_oracle_and_the_cascade_from_the_answers_already_in_the_files(monkeypatch):
    """Run 2 of the cheap variant on dev: d-1 right, d-2 wrong, d-u refused. Every question
    cost 0.02; the strong one is right on all three at 0.50 each."""
    cheap = base.three()[1][1]
    strong = strong_run(monkeypatch)[1]
    made = cost.simulate(cheap, strong, "dev")
    assert made["cheap alone"] == {"usd": Decimal("0.06"), "correct": 2, "to_strong": 0, "cases": 3}
    assert made["strong alone"] == {
        "usd": Decimal("1.50"), "correct": 3, "to_strong": 3, "cases": 3,
    }  # fmt: skip
    # Oracle: the cheap one where it was right (twice), the strong one for d-2.
    assert made["oracle"] == {"usd": Decimal("0.54"), "correct": 3, "to_strong": 1, "cases": 3}
    # Cascade: d-2 was answered, wrongly, and grounded: nothing tells it to ask again.
    assert made["cascade"] == {"usd": Decimal("0.06"), "correct": 2, "to_strong": 0, "cases": 3}
    # When the cheap one ends without an answer, both are paid for and the strong one counts.
    for record in cheap["records"]:
        if record["id"] == "d-2":
            record["result"]["status"] = "no_answer"
    made = cost.simulate(cheap, strong, "dev")
    assert made["cascade"] == {"usd": Decimal("0.56"), "correct": 3, "to_strong": 1, "cases": 3}
    # An ungrounded answer that was right is sent on too: the cascade cannot know it was.
    for record in cheap["records"]:
        if record["id"] == "d-1":
            record["result"]["status"] = "ungrounded"
    made = cost.simulate(cheap, strong, "dev")
    assert made["cascade"]["to_strong"] == 2 and made["cascade"]["usd"] == Decimal("1.06")


def test_the_report_says_the_routers_are_simulated_and_names_no_case(monkeypatch, tmp_path):
    files = base.three()
    strong = strong_run(monkeypatch)
    text = cost.render([("baseline", files)], files, strong)
    assert "## Two routers, simulated on `dev`" in text and "Nothing here was run." in text
    assert text.count("| oracle |") == 3 == text.count("| cascade |")  # one per cheap run
    for case_id in base.CASES:
        assert case_id not in text
    assert cost.main(["--row", "baseline"]) == cost.SETUP_ERROR
