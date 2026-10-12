"""Scoring a results file again against the golden file as it is now. No model, no server.

The example is the correction this command was written for: an amount of a token used to
pass within a cent, which for a small amount accepts almost any number.
"""

import hashlib
import json

import pytest

from evalkit import golden, rescore, score
from univ3_indexer import config

GOLDEN = config.REPO_ROOT / "evals" / "golden.jsonl"
OLD_SHA = "0" * 64
LOOSE = {"abs": "0.01", "rel": "0.001"}


def earlier_results():
    """Two cases as an older golden file had them, and what a run answered."""
    by_id = {case["id"]: case for case in golden.load(GOLDEN)}
    small = dict(by_id["t-token-volume-day-001"])  # expected is about 0.16 of a token
    exact = dict(by_id["t-swaps-day-001"])
    assert small["tolerance"] == {"abs": "0", "rel": "0.001"}  # what it is now
    small["tolerance"] = LOOSE  # what it was
    cases = {small["id"]: small, exact["id"]: exact}

    def result(value):
        return {"status": "answered", "answer": {"value": value}, "tool_calls": [],
                "usd": "0.01", "seconds": 1.0, "tokens": {"input_tokens": 10}}  # fmt: skip

    answers = [(small["id"], result("0.16")), (exact["id"], result(exact["expected"]))]
    records = [
        {"id": i, "repetition": 1, "status": "ran", "result": r}
        | {"score": score.score_case(cases[i], r)}
        for i, r in answers
    ]
    records.append({"id": exact["id"], "repetition": 2, "status": "not_run", "why": "budget"})
    return {
        "format": 2, "variant": "baseline", "golden_file": "golden.jsonl", "golden_sha256": OLD_SHA,
        "cases": cases, "records": records, "summary": score.summarize(records, cases),
    }  # fmt: skip


def test_the_same_answers_are_judged_again_and_both_golden_hashes_are_recorded():
    results = earlier_results()
    before = json.loads(json.dumps(results))
    assert results["summary"]["overall"]["correct"]["k"] == 2  # 0.16 passed within a cent
    now = hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    new = rescore.rescore(results, golden.load(GOLDEN), now, "2026-10-11T16:00:00+00:00")
    assert results == before  # the original is not touched
    assert new["golden_sha256"] == now
    assert new["rescored"] == [
        {
            "at": "2026-10-11T16:00:00+00:00",
            "from_golden_sha256": OLD_SHA,
            "to_golden_sha256": now,
            "changed": [
                {"id": "t-token-volume-day-001", "repetition": 1, "was": True, "now": False}
            ],
        }
    ]
    assert new["cases"]["t-token-volume-day-001"]["tolerance"] == {"abs": "0", "rel": "0.001"}
    assert [r["score"]["correct"] for r in new["records"] if r["status"] == "ran"] == [False, True]
    correct = new["summary"]["overall"]["correct"]
    assert (correct["k"], correct["n"]) == (1, 2)
    assert new["summary"]["not_run"] == 1 and new["records"][2] == results["records"][2]
    # What the agent answered is exactly what it was.
    answered = lambda file: [r.get("result") for r in file["records"]]  # noqa: E731
    assert answered(new) == answered(results)
    # Rescoring again adds a second entry and changes nothing.
    again = rescore.rescore(new, golden.load(GOLDEN), now, "later")
    assert len(again["rescored"]) == 2 and again["rescored"][1]["changed"] == []
    second = again["rescored"][1]
    assert second["from_golden_sha256"] == now == second["to_golden_sha256"]


def test_the_command_writes_a_new_file_and_never_overwrites(tmp_path, capsys):
    source = tmp_path / "2026-10-11_baseline_1.json"
    source.write_text(json.dumps(earlier_results()))
    kept = source.read_text()
    assert rescore.main([str(source)]) == 0
    out = tmp_path / "2026-10-11_baseline_1_rescored.json"
    written = json.loads(out.read_text())
    assert written["golden_sha256"] == hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    assert written["rescored"][0]["from_golden_sha256"] == OLD_SHA
    assert "1 scores changed" in capsys.readouterr().out and source.read_text() == kept
    assert rescore.main([str(source)]) == 2
    assert "already exists; nothing was written" in capsys.readouterr().err
    assert rescore.main([str(source), "--out", str(tmp_path / "other.json")]) == 0


def test_a_case_that_left_the_golden_file_cannot_be_rescored(tmp_path, capsys):
    results = earlier_results()
    results["cases"]["t-gone-001"] = results["cases"]["t-swaps-day-001"]
    with pytest.raises(golden.GoldenError, match="not in the golden file any more: t-gone-001"):
        rescore.rescore(results, golden.load(GOLDEN), "x", "now")
    source = tmp_path / "r.json"
    source.write_text(json.dumps(results))
    assert rescore.main([str(source)]) == 2 and not (tmp_path / "r_rescored.json").exists()
    assert "t-gone-001" in capsys.readouterr().err
