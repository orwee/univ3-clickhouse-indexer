"""Cases written by hand: a question and its query, never its answer.

The YAML holds, for each case, what a person has to decide: how the question is worded,
which query answers it, which other queries answer another reasonable reading of it, and
why the case exists. The answer is not in the file and cannot be: a case that carries
``expected`` or ``accepted`` is refused. The generator computes both by running the queries
on the fixture, exactly as it does for the template cases.

A case with no answer (``kind: unanswerable``) has no query at all; its ``notes`` say what
a wrong answer would look like.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from evalkit.golden import GoldenError, Spec

REQUIRED = ("id", "question", "kind", "family", "notes")
OPTIONAL = ("answer_type", "unit", "tolerance", "reference_sql", "accepted_sql")
COMPUTED = ("expected", "accepted", "split")
KINDS = ("hand", "unanswerable")


def _one_line(sql: object, case_id: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise GoldenError(f"{case_id}: a query must be a non-empty text")
    return " ".join(sql.split())


def load(path: Path) -> list[Spec]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise GoldenError(f"{path}: expected a list of cases")
    specs = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise GoldenError(f"{path}: every case is a mapping with an id")
        case_id = entry["id"]
        written = [name for name in COMPUTED if name in entry]
        if written:
            raise GoldenError(
                f"{case_id}: {', '.join(written)} cannot be written by hand: the generator "
                "computes them"
            )
        unknown = set(entry) - set(REQUIRED) - set(OPTIONAL)
        missing = [name for name in REQUIRED if not entry.get(name)]
        if unknown or missing:
            raise GoldenError(f"{case_id}: unknown {sorted(unknown)}, missing {missing}")
        if entry["kind"] not in KINDS:
            raise GoldenError(f"{case_id}: kind must be one of {', '.join(KINDS)}")
        notes = " ".join(str(entry["notes"]).split())
        question = " ".join(str(entry["question"]).split())
        if entry["kind"] == "unanswerable":
            given = [name for name in OPTIONAL if name in entry]
            if given:
                raise GoldenError(f"{case_id}: a case with no answer has no {', '.join(given)}")
            specs.append(
                Spec(
                    case_id, question, "unanswerable", entry["family"], "refusal", None, None, notes
                )
            )
            continue
        if "answer_type" not in entry or "reference_sql" not in entry:
            raise GoldenError(
                f"{case_id}: a case with an answer needs answer_type and reference_sql"
            )
        others = entry.get("accepted_sql") or []
        if not isinstance(others, list):
            raise GoldenError(f"{case_id}: accepted_sql must be a list of queries")
        specs.append(
            Spec(
                id=case_id,
                question=question,
                kind="hand",
                family=entry["family"],
                answer_type=entry["answer_type"],
                unit=entry.get("unit"),
                reference_sql=_one_line(entry["reference_sql"], case_id),
                notes=notes,
                tolerance=entry.get("tolerance"),
                accepted_sql=tuple(_one_line(sql, case_id) for sql in others),
            )
        )
    return specs
