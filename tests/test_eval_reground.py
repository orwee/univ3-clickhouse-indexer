"""Grounding decided again from transcripts. No model, no server.

The questions are asked of the loop with a scripted model, so the transcripts are the
loop's own. The results are then made to look as the earlier check left them, and the
command has to bring back what the loop says today.
"""

import csv
import json

from agent import budget, llm, loop
from evalkit import reground, score

LONG = "17961.320063199079530937"
CASES = {
    "double": {"split": "dev", "expected": LONG},
    "parallel": {"split": "dev", "expected": "42"},
    "earlier": {"split": "dev", "expected": "42"},
    "typed": {"split": "dev", "expected": "42"},
    "held-out": {"split": "test", "expected": "42"},
    "refuses": {"split": "dev", "expected": None, "answer_type": "refusal"},
}


class Tools:
    def __init__(self, *results):
        self.results = list(results)

    def describe_schema(self, tables=None):
        return {"ok": True, "database": "d", "tables": {}}

    def run_sql(self, sql):
        rows = self.results.pop(0)
        return {
            "ok": True,
            "columns": [{"name": "v", "type": "String"}],
            "rows": rows,
            "row_count": len(rows),
            "truncated": False,
        }


def q(sql, id_=""):
    return llm.tool_use("run_sql", {"sql": sql}, id_)


def submit(**fields):
    return llm.response(llm.tool_use("submit_answer", fields))


def number(value):
    return {"type": "number", "value": value}


def scripts():
    two = llm.response(q("SELECT 42", "a"), q("SELECT 7", "b"))
    one = llm.response(q("SELECT 42"))
    return {
        "double": ([llm.response(q("SELECT v"))], [[[LONG]]], number(float(LONG))),
        "parallel": ([two], [[["42"]], [["7"]]], number("42")),
        "earlier": ([one, llm.response(q("SELECT 7"))], [[["42"]], [["7"]]], number("42")),
        "typed": ([one], [[["41"]]], number("42")),
        "held-out": ([two], [[["42"]], [["7"]]], number("42")),
        "refuses": ([], [], dict(type="refusal", refusal_reason="not in the data")),
    }


def a_run(directory):
    """Results and transcripts of six questions, then the results as the old check had them."""
    cases, records = {}, []
    for case_id, (turns, results, answer) in scripts().items():
        case = {
            "id": case_id,
            "kind": "hand",
            "family": "f",
            "answer_type": "number",
            "accepted": [],
            "tolerance": {"abs": "0", "rel": "0"},
        } | CASES[case_id]
        cases[case_id] = case
        transcript: list = []
        result = loop.run(
            "How much?",
            llm.ScriptedLLM([*turns, submit(**answer)], "claude-opus-5-5"),
            Tools(*results),
            budget.DollarBudget("5"),
            transcript=transcript,
        ).to_json()
        (directory / f"{case_id}_1.json").write_text(
            json.dumps({"id": case_id, "repetition": 1, "turns": transcript})
        )
        records.append({"id": case_id, "repetition": 1, "status": "ran", "result": result})
    today = {r["id"]: r["result"]["status"] for r in records}
    for record in records:  # the earlier check: only the last result, digit for digit
        if record["id"] in ("double", "parallel", "held-out"):
            record["result"]["status"] = "ungrounded"
            record["result"]["reason"] = "the value is not a cell of the last result"
        record["score"] = score.score_case(cases[record["id"]], record["result"])
    results = {"cases": cases, "records": records, "summary": score.summarize(records, cases)}
    return results, today


def test_the_loop_itself_grounds_what_the_earlier_check_did_not(tmp_path):
    _, today = a_run(tmp_path)
    assert today == {
        "double": "answered",
        "parallel": "answered",
        "earlier": "ungrounded",
        "typed": "ungrounded",
        "held-out": "answered",
        "refuses": "refused",
    }


def test_grounding_is_decided_again_and_nothing_else_changes(tmp_path):
    results, today = a_run(tmp_path)
    before = json.dumps(results, sort_keys=True)
    new, rows = reground.reground(results, tmp_path, "now")
    assert json.dumps(results, sort_keys=True) == before, "the original is not touched"
    assert {r["id"]: r["result"]["status"] for r in new["records"]} == today
    assert new["regrounded"] == [
        {"at": "now", "ungrounded_before": 5, "ungrounded_after": 2, "undecided": 0}
    ]
    # Right and wrong are as they were: only where the value came from is decided again.
    was = {r["id"]: r["score"]["correct"] for r in results["records"]}
    assert {r["id"]: r["score"]["correct"] for r in new["records"]} == was
    assert results["summary"]["overall"]["ungrounded"]["k"] == 5
    assert new["summary"]["overall"]["ungrounded"]["k"] == 2
    assert new["summary"]["overall"]["correct"] == results["summary"]["overall"]["correct"]
    # The record of the answer says the same as its status.
    for record in new["records"]:
        last = record["result"]["tool_calls"][-1]["summary"]
        if "grounded" in last:
            assert last["grounded"] == (record["result"]["status"] == "answered")


def test_the_causes_are_of_one_split_and_say_where_each_value_was(tmp_path):
    results, _ = a_run(tmp_path)
    _, rows = reground.reground(results, tmp_path, "now")
    assert {row["id"]: (row["cause"], row["still_ungrounded"]) for row in rows} == {
        "double": (reground.AS_DOUBLE, False),
        "parallel": (reground.SAME_TURN, False),
        "earlier": (reground.EARLIER, True),
        "typed": (reground.NOWHERE, True),
    }, "the test case is in no row"
    _, every = reground.reground(results, tmp_path, "now", split="all")
    assert "held-out" in {row["id"] for row in every}


def test_the_command_writes_both_files_and_overwrites_neither(tmp_path, capsys):
    results, _ = a_run(tmp_path)
    source, out, causes = tmp_path / "r.json", tmp_path / "new.json", tmp_path / "c" / "c.csv"
    source.write_text(json.dumps(results))
    args = [str(source), "--transcripts", str(tmp_path), "--out", str(out), "--causes", str(causes)]
    assert reground.main(args) == 0
    said = capsys.readouterr().out
    assert "5 before, 2 after" in said and "held-out" not in said
    with causes.open(newline="") as fh:
        listed = [row["id"] for row in csv.DictReader(fh)]
    assert listed == ["double", "parallel", "earlier", "typed"]
    assert json.loads(out.read_text())["regrounded"][0]["ungrounded_after"] == 2
    assert reground.main(args) == reground.SETUP_ERROR
    assert "already exists" in capsys.readouterr().err


def test_a_missing_transcript_stops_the_command(tmp_path, capsys):
    results, _ = a_run(tmp_path)
    (tmp_path / "parallel_1.json").unlink()
    source = tmp_path / "r.json"
    source.write_text(json.dumps(results))
    args = [str(source), "--transcripts", str(tmp_path), "--out", str(tmp_path / "new.json")]
    assert reground.main(args) == reground.SETUP_ERROR
    assert "no usable transcript" in capsys.readouterr().err
    assert not (tmp_path / "new.json").exists()
