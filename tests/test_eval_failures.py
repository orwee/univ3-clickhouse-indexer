"""The cases one split got wrong, listed for classification. No model, no server.

The six cases are the ones of tests/test_eval_runs.py; what each of three runs did with
them is the table below.
"""

import csv
import json

from evalkit import failures
from tests import test_eval_runs as base

#        d-1      d-2        t-1      t-2      d-u         t-u
MATRIX = [
    ("right", "refused", "right", "wrong", "refused", "refused"),
    ("right", "wrong", "right", "wrong", "answered", "answered"),
    ("wrong", "error", "right", "right", "answered", "answered"),
]


def three(monkeypatch):
    monkeypatch.setattr(base, "RUNS", MATRIX)
    files = []
    for n in (1, 2, 3):
        results = base.a_run(n)
        for record in results["records"]:
            if record["result"]["status"] == "answered":
                record["result"]["final_sql"] = f"SELECT v  FROM t\nWHERE run = {n}"
        files.append((f"2026-10-11_baseline_{n}.json", results))
    return files


def test_dev_cases_wrong_in_two_runs_are_listed_and_wrong_in_one_are_unstable(monkeypatch):
    wrong, unstable = failures.collect(three(monkeypatch), "dev")
    assert [row["id"] for row in wrong] == ["d-2", "d-u"]
    assert wrong[0] == {
        "id": "d-2",
        "kind": "template",
        "family": "f",
        "what_happened": (
            "wrong in 2 of 2. run 1: refused; run 2: answered 1, expected 100; "
            "1 run(s) ended in an error or did not ask it"
        ),
        "evidence": "run 1: refusal: No such thing.",
        "category": "",
        "note": "",
    }
    assert wrong[1]["what_happened"] == (
        "wrong in 2 of 3. run 1: right; run 2: answered 1, expected a refusal; "
        "run 3: answered 1, expected a refusal"
    )
    assert wrong[1]["evidence"] == "run 2: SELECT v FROM t WHERE run = 2"  # one line
    assert unstable == [
        {
            "id": "d-1",
            "kind": "template",
            "family": "f",
            "what_happened": (
                "wrong in 1 of 3. run 1: right; run 2: right; run 3: answered 1, expected 100"
            ),
            "evidence": "run 3: SELECT v FROM t WHERE run = 3",
        }
    ]


def test_nothing_of_another_split_is_read_into_the_output(monkeypatch, tmp_path, capsys):
    """t-2 and t-u were wrong in two runs too. With the default split they are not listed,
    not counted and not printed."""
    paths = []
    for name, results in three(monkeypatch):
        (tmp_path / name).write_text(json.dumps(results))
        paths.append(str(tmp_path / name))
    out, unstable = tmp_path / "failures.csv", tmp_path / "unstable.csv"
    assert failures.main([*paths, "--out", str(out), "--unstable", str(unstable)]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("dev: 2 cases wrong in at least two of 3 runs")
    written = out.read_text() + unstable.read_text()
    assert "t-1" not in written and "t-2" not in written and "t-u" not in written
    # What is printed is two counts and two paths: no case of any split is named.
    assert printed.replace(str(tmp_path), "") == (
        "dev: 2 cases wrong in at least two of 3 runs (/failures.csv), "
        "1 wrong in one (/unstable.csv)\n"
    )
    with out.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert tuple(rows[0]) == failures.COLUMNS
    assert [row["id"] for row in rows] == ["d-2", "d-u"] and rows[0]["category"] == ""
    # Asked for by name, the other split is listed: the tool is the same, the default is not.
    listed, _ = failures.collect(three(monkeypatch), "test")
    assert [row["id"] for row in listed] == ["t-2", "t-u"]


def test_categories_already_written_are_carried_over_by_case_id(monkeypatch, tmp_path):
    paths = []
    for name, results in three(monkeypatch):
        (tmp_path / name).write_text(json.dumps(results))
        paths.append(str(tmp_path / name))
    earlier = tmp_path / "earlier.csv"
    earlier.write_text(
        "id,kind,family,what_happened,category,note,evidence\n"
        "d-2,template,f,x,date filter,also fits units; the date is what made it wrong,y\n"
        "d-9,template,f,x,other,,y\n"
    )
    out = tmp_path / "failures.csv"
    arguments = [*paths, "--out", str(out), "--unstable", str(tmp_path / "u.csv")]
    assert failures.main([*arguments, "--keep", str(earlier)]) == 0
    rows = {row["id"]: row for row in failures.read_csv(out)}
    assert rows["d-2"]["category"] == "date filter"
    assert rows["d-2"]["note"].startswith("also fits units")
    assert rows["d-u"]["category"] == "" and "d-9" not in rows


def test_runs_of_different_things_are_refused(monkeypatch, tmp_path, capsys):
    paths = []
    for n, (name, results) in enumerate(three(monkeypatch)):
        if n == 1:
            results["model"] = "another-model"
        (tmp_path / name).write_text(json.dumps(results))
        paths.append(str(tmp_path / name))
    out = tmp_path / "failures.csv"
    code = failures.main([*paths, "--out", str(out), "--unstable", str(tmp_path / "u.csv")])
    assert code == 2 and not out.exists()
    assert "model is not the same" in capsys.readouterr().err
