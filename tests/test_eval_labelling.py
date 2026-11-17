"""The labelling kit (evalkit.labelling): what it shows, what it hides, and the scores of a
filled sheet. Synthetic files, plus one build from the committed sheet and cases. No model,
no network, and nothing labelled by the agent."""

import csv
import json

import pytest

from evalkit import calibration, labelling, retrieval
from evalkit.judge import SHEET_COLUMNS
from univ3_indexer import config

FACT = "a fact only the model's labels hold"


def write_sheet(path, rows=3):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for n in range(1, rows + 1):
            writer.writerow(
                {
                    "row": str(n),
                    "question": f"Question {n}?",
                    "earlier": "[]",
                    "sql": "SELECT 1",
                    "result": "{}",
                    "explanation": f"Explanation {n}.",
                    "label": "faithful",  # a model's label, which the kit must drop
                }
            )
    return path


def write_docs(root):
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text(
        "# Project\n\nIntro.\n\n## Apples\n\nApples are red fruit.\n\n"
        "## Pears\n\nPears are green fruit.\n",
        encoding="utf-8",
    )
    (root / "DECISIONS.md").write_text(
        "# Decisions\n\n## 1. Fruit\n\nWe sell apples and pears and plums.\n", encoding="utf-8"
    )
    (root / "docs" / "PLUMS.md").write_text(
        "# Plums\n\nPlums are purple fruit.\n", encoding="utf-8"
    )
    return root


CASES = [
    ("apples", "dev", "What colour are apples?", ["README.md#Apples"]),
    ("pears", "test", "What colour are pears?", ["README.md#Pears"]),
    ("plums", "test", "What colour are plums?", ["docs/PLUMS.md#Plums"]),
    ("fruit", "test", "Which fruit are sold?", ["DECISIONS.md#1. Fruit", "README.md#Apples"]),
]


def write_cases(path, order=None):
    lines = [json.dumps({"_header": "synthetic"})]
    for case_id, split, question, relevant in order or CASES:
        lines.append(
            json.dumps(
                {
                    "id": case_id,
                    "question": question,
                    "split": split,
                    "relevant": relevant,
                    "key_facts": [
                        {"fact": FACT, "any_of": ["zzz-hidden"]},
                        {"fact": FACT, "any_of": ["yyy-hidden"]},
                    ],
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path):
    root = write_docs(tmp_path / "repo")
    return {
        "sheet": write_sheet(tmp_path / "sheet.csv"),
        "cases": write_cases(tmp_path / "cases.jsonl"),
        "root": root,
    }


def kit(files, count=3, top=2, seed=1):
    return labelling.build(
        files["sheet"], files["cases"], count=count, top=top, seed=seed, root=files["root"]
    )


def test_the_kit_has_every_judge_row_without_its_label(files):
    rows = kit(files)
    judged = [r for r in rows if r["kind"] == labelling.JUDGE]
    assert [r["item"] for r in judged] == ["j1", "j2", "j3"]
    text = labelling.kit_text(rows)
    assert all(row["label"] == "" for row in csv.DictReader(text.splitlines()))
    assert "faithful" not in text


def test_the_kit_shows_every_labelled_section_but_not_which_and_no_key_fact(files):
    rows = kit(files, count=4)
    text = labelling.kit_text(rows)
    assert FACT not in text and "hidden" not in text and "relevant" not in text
    for case_id, _, question, relevant in CASES:
        mine = [r for r in rows if r.get("case") == case_id]
        assert {r["question"] for r in mine} == {question}
        assert set(relevant) <= {r["section"] for r in mine}
        assert all(r["section_text"] for r in mine)
    assert next(r for r in rows if r.get("section") == "README.md#Apples")["section_text"] == (
        "Apples\n\nApples are red fruit."
    )


def test_the_draw_follows_the_splits_and_the_seed_and_not_the_order_of_the_file(files, tmp_path):
    drawn = labelling.draw_cases(retrieval.load_cases(files["cases"]), 3, 7)
    assert sorted(c["split"] for c in drawn) == ["dev", "test", "test"]
    reversed_cases = write_cases(tmp_path / "reversed.jsonl", list(reversed(CASES)))
    again = labelling.draw_cases(retrieval.load_cases(reversed_cases), 3, 7)
    assert [c["id"] for c in again] == [c["id"] for c in drawn]
    assert kit(files, seed=3) == kit(files, seed=3)
    with pytest.raises(labelling.LabellingError):
        labelling.draw_cases(retrieval.load_cases(files["cases"]), 5, 7)


def test_a_labelled_section_no_document_has_is_refused(files, tmp_path):
    files["cases"] = write_cases(
        tmp_path / "bad.jsonl", [("x", "test", "What?", ["README.md#Nowhere"])]
    )
    with pytest.raises(labelling.LabellingError, match="Nowhere"):
        kit(files, count=1)


def fill(rows, path, judge, answer):
    """A filled kit: ``judge(row)`` and ``answer(row)`` give the labels a person would."""
    for row in rows:
        row["label"] = judge(row) if row["kind"] == labelling.JUDGE else answer(row)
    path.write_text(labelling.kit_text(rows), encoding="utf-8")
    return path


def test_the_scores_of_a_filled_kit(files, tmp_path):
    rows = kit(files, count=4, top=2)
    labelled = {case_id: set(relevant) for case_id, _, _, relevant in CASES}
    retrieval_rows = [r for r in rows if r["kind"] == labelling.RETRIEVAL]
    flipped = retrieval_rows[0]["item"]

    def answer(row):
        right = "yes" if row["section"] in labelled[row["case"]] else "no"
        if row["item"] != flipped:
            return right
        return "no" if right == "yes" else "yes"

    filled = fill(rows, tmp_path / "filled.csv", lambda r: "faithful", answer)
    got = labelling.retrieval_agreement(
        labelling.read_filled(filled), retrieval.load_cases(files["cases"])
    )
    assert got["sections"] == len(retrieval_rows) and got["cases"] == 4
    assert got["agreement"] == (len(retrieval_rows) - 1) / len(retrieval_rows)
    assert sum(got["table"].values()) == len(retrieval_rows)
    assert got["table"]["yes/no"] + got["table"]["no/yes"] == 1
    verdicts = [{"key": "1", "verdict": "faithful"}, {"key": "2", "verdict": "unfaithful"}]
    report = labelling.score(filled, verdicts, retrieval.load_cases(files["cases"]))
    assert "| Rows with a label and a verdict | 2 |" in report
    assert "| Percent agreement | 0.500 |" in report
    assert f"| Sections judged | {len(retrieval_rows)} |" in report
    assert "NOT A HUMAN CALIBRATION" not in report


def test_a_row_without_its_label_is_refused(files, tmp_path):
    rows = kit(files)
    filled = fill(rows, tmp_path / "filled.csv", lambda r: "faithful", lambda r: "maybe")
    with pytest.raises(labelling.LabellingError, match="have no label"):
        labelling.read_filled(filled)


def test_to_sheet_copies_the_judge_labels_and_says_a_person_wrote_them(files, tmp_path):
    rows = kit(files)
    filled = fill(
        rows,
        tmp_path / "filled.csv",
        lambda r: "unfaithful" if r["item"] == "j2" else "faithful",
        lambda r: "no",
    )
    assert labelling.to_sheet(filled, files["sheet"], "The owner, on 2026-11-01") == 3
    assert calibration.read_labels(files["sheet"]) == {
        "1": "faithful", "2": "unfaithful", "3": "faithful",
    }  # fmt: skip
    assert calibration.read_labeller(files["sheet"])["labelled_by"] == "person"


def test_the_command_writes_outside_the_repository_only_and_never_over_a_file(files, tmp_path):
    common = ["--sheet", str(files["sheet"]), "--cases", str(files["cases"]), "--count", "2"]
    inside = config.REPO_ROOT / "labelling.csv"
    assert labelling.main(["kit", *common, "--out", str(inside)]) == labelling.SETUP_ERROR
    assert not inside.exists()
    out = tmp_path / "out" / "kit.csv"
    out.parent.mkdir()
    out.write_text("already here", encoding="utf-8")
    assert labelling.main(["kit", *common, "--out", str(out)]) == labelling.SETUP_ERROR
    assert out.read_text(encoding="utf-8") == "already here"


def test_the_kit_from_the_committed_sheet_and_cases(tmp_path):
    """Thirty judge rows and twenty cases, every section the model labelled among the rows,
    and no label of the model in the file."""
    out = tmp_path / "kit.csv"
    assert labelling.main(["kit", "--out", str(out)]) == 0
    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    judged = [r for r in rows if r["kind"] == labelling.JUDGE]
    shown = [r for r in rows if r["kind"] == labelling.RETRIEVAL]
    assert len(judged) == 30
    assert all(r["label"] == "" for r in rows)
    cases = {c["id"]: c for c in retrieval.load_cases(labelling.DEFAULT_CASES)}
    drawn = {r["case"] for r in shown}
    assert len(drawn) == 20
    splits = [cases[c]["split"] for c in drawn]
    assert splits.count("dev") == round(20 * 15 / 44) == 7
    for case_id in drawn:
        assert set(cases[case_id]["relevant"]) <= {
            r["section"] for r in shown if r["case"] == case_id
        }
