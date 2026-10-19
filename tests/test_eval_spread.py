"""evalkit.spread: the spread between identical runs, and the guards read from it.

Checked on the three committed baseline runs of golden set v1, whose numbers the first entry
of docs/EVAL_PREREGISTRATION.md already states: 105 of 106 right and 1 refused although it has
an answer on `test`, and 17 of 21 refused by majority.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from evalkit import runs, spread
from univ3_indexer import config

PATTERN = str(config.REPO_ROOT / "evals/results/2026-10-12_baseline-regrounded_*.json")


@pytest.fixture(scope="module")
def files():
    return runs.load([Path(p) for p in sorted(glob.glob(PATTERN))])


def test_the_guards_of_the_first_entry_are_reproduced(files):
    assert len(files) == 3
    g = spread.guards(files, "test")
    assert g["answerable"] == 106
    assert (g["right_by_majority"], g["wrongly_refused_by_majority"]) == (105, 1)
    assert [p["right"] for p in g["per_run"]] == [104, 104, 105]
    assert g["spread_right"] == 1 and g["may_lose"] == 1
    assert g["spread_wrongly_refused"] == 0 and g["may_have_wrongly_refused"] == 2


def test_refusal_recall_by_majority_and_the_spread_between_runs(files):
    r = spread.refusal_recall(files, "test")
    assert [p["refused"] for p in r["per_run"]] == [16, 19, 17]
    assert r["spread"] == 3
    assert (r["by_majority"]["k"], r["by_majority"]["n"]) == (17, 21)


def test_per_case_rows_and_the_report(files):
    rows = spread.per_case(files, "all")
    assert len(rows) == 180 and all(len(r["right"]) == 3 for r in rows)
    text = spread.csv_text(rows)
    assert text.splitlines()[0].startswith("id,split,has_answer,runs_right")
    assert len(text.splitlines()) == 181
    report = spread.render(files)
    assert "17 of 21" in report and "max(1, 1) = 1" in report


def test_runs_of_different_things_are_refused(tmp_path, files, capsys):
    import json

    name, results = files[0]
    other = dict(results, golden_sha256="0" * 64)
    path = tmp_path / "other.json"
    path.write_text(json.dumps(other))
    first = config.REPO_ROOT / "evals/results" / name
    assert spread.main([str(first), str(path)]) == 2
    assert "golden_sha256" in capsys.readouterr().err
