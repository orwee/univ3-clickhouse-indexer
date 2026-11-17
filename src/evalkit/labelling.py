"""A labelling kit for a person: one sheet with the judge's rows and some retrieval cases.

    PYTHONPATH=src uv run python -m evalkit.labelling kit [--out FILE]
    PYTHONPATH=src uv run python -m evalkit.labelling score FILLED --verdicts VERDICTS
    PYTHONPATH=src uv run python -m evalkit.labelling to-sheet FILLED --who TEXT

``kit`` writes one CSV under the data directory, never in the working copy, with two kinds
of row (the guide is ``evals/calibration/LABELLING.md``):

``judge``      the rows of the judge's calibration sheet, with the label column empty. The
               sheet does not say which rows were altered; the kit does not either.
``retrieval``  for each of ``--count`` cases of the retrieval file, drawn with a fixed seed
               from ``dev`` and ``test`` in the proportion of the file, one row per section
               to judge: the sections the model labelled as answering the question mixed,
               in an order drawn with the seed, with the first ``--top`` sections the search
               ranks for it. Each row has the question, the section and its text. Nothing
               says which sections the model labelled, and no key fact is shown.

The person writes ``faithful`` or ``unfaithful`` on a judge row and ``yes`` or ``no`` (does
this section answer the question?) on a retrieval row.

``score`` reads the filled CSV. The judge rows go to ``calibration.agree`` with the judge's
verdicts on the same sheet: percent agreement, Cohen's kappa and the table. The retrieval
rows are compared with the model's labels, section by section (agreement, kappa, table),
and case by case: whether a section the person said answers is one the model labelled.
Altered rows caught needs the sheet's key, which is not here: ``to-sheet`` copies the judge
labels into the sheet, so that ``calibration agree --key`` can be run where the key is.

No model and no network take part.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from pathlib import Path

from agent import docs_index
from evalkit import calibration, retrieval
from evalkit.judge import SHEET_COLUMNS, VERDICTS
from univ3_indexer import config

DEFAULT_SHEET = calibration.DEFAULT_SHEET
DEFAULT_CASES = config.REPO_ROOT / "evals" / "rag_cases.jsonl"
DEFAULT_SEED = 20261027
DEFAULT_COUNT = 20
DEFAULT_TOP = 3
JUDGE, RETRIEVAL = "judge", "retrieval"
ANSWERS = ("yes", "no")
SHEET_FIELDS = tuple(column for column in SHEET_COLUMNS if column not in ("row", "label"))
COLUMNS = ("item", "kind", *SHEET_FIELDS, "case", "section", "section_text", "label", "note")
SETUP_ERROR = 2


class LabellingError(ValueError):
    """The kit cannot be written, or the filled sheet cannot be scored."""


def default_out() -> Path:
    """``<data dir>/labelling/labelling.csv``. The data directory is never inside the repository."""
    return config.data_dir() / "labelling" / "labelling.csv"


# --- the kit ---------------------------------------------------------------------------------


def judge_rows(sheet: Path) -> list[dict]:
    """The rows of the judge's sheet, as kit rows, without their label."""
    with sheet.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != SHEET_COLUMNS:
            raise LabellingError(f"{sheet}: the columns must be {', '.join(SHEET_COLUMNS)}")
        rows = list(reader)
    return [
        {"item": f"j{row['row']}", "kind": JUDGE, **{f: row[f] for f in SHEET_FIELDS}}
        for row in rows
    ]


def draw_cases(cases: list[dict], count: int, seed: int) -> list[dict]:
    """``count`` cases, from ``dev`` and ``test`` in the proportion of the file, drawn with a
    seed. Depends on the ids, the splits and the seed only, not on the order of the file."""
    if not 0 < count <= len(cases):
        raise LabellingError(f"--count must be from 1 to {len(cases)}")
    by_split = {
        split: sorted((c for c in cases if c["split"] == split), key=lambda c: c["id"])
        for split in ("dev", "test")
    }
    dev = min(len(by_split["dev"]), round(count * len(by_split["dev"]) / len(cases)))
    wanted = {"dev": dev, "test": count - dev}
    if wanted["test"] > len(by_split["test"]):
        wanted = {"dev": count - len(by_split["test"]), "test": len(by_split["test"])}
    drawn = []
    for split in ("dev", "test"):
        rng = random.Random(f"{seed}:{split}")  # noqa: S311 - a reproducible draw
        drawn += rng.sample(by_split[split], wanted[split])
    return sorted(drawn, key=lambda c: c["id"])


def section_texts(chunks: list[docs_index.Chunk]) -> dict[str, str]:
    """The whole text of each section, its chunks joined in order, under its heading."""
    out: dict[str, list[str]] = {}
    headings: dict[str, str] = {}
    for chunk in chunks:
        out.setdefault(chunk.section, []).append(chunk.text)
        headings.setdefault(chunk.section, chunk.heading)
    return {s: f"{headings[s]}\n\n" + "\n\n".join(texts) for s, texts in out.items()}


def retrieval_rows(
    cases: list[dict], chunks: list[docs_index.Chunk], top: int, seed: int
) -> list[dict]:
    """One row per section to judge, the labelled and the ranked ones mixed by the seed."""
    texts = section_texts(chunks)
    unknown = retrieval.unknown_sections(chunks, cases)
    if unknown:
        named = ", ".join(f"{case} {section!r}" for case, section in unknown)
        raise LabellingError(f"sections no document has: {named}")
    index = docs_index.Index(chunks)
    rows = []
    for case in cases:
        sections = list(dict.fromkeys([*case["relevant"], *index.sections(case["question"], top)]))
        random.Random(f"{seed}:{case['id']}").shuffle(sections)  # noqa: S311 - reproducible
        for n, section in enumerate(sections, start=1):
            rows.append(
                {
                    "item": f"r-{case['id']}-{n}",
                    "kind": RETRIEVAL,
                    "question": case["question"],
                    "case": case["id"],
                    "section": section,
                    "section_text": texts[section],
                }
            )
    return rows


def kit_text(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, restval="", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def build(
    sheet: Path, cases_path: Path, *, count: int, top: int, seed: int, root: Path
) -> list[dict]:
    cases = draw_cases(retrieval.load_cases(cases_path), count, seed)
    return judge_rows(sheet) + retrieval_rows(cases, docs_index.load_chunks(root), top, seed)


# --- the filled kit --------------------------------------------------------------------------


def read_filled(path: Path) -> list[dict]:
    """The rows of a filled kit. Every row needs a label of its kind."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise LabellingError(f"{path}: the columns must be {', '.join(COLUMNS)}")
        rows = list(reader)
    allowed = {JUDGE: VERDICTS, RETRIEVAL: ANSWERS}
    for row in rows:
        row["label"] = row["label"].strip()
        if row["kind"] not in allowed:
            raise LabellingError(f"{path}: item {row['item']} has kind {row['kind']!r}")
    bad = [row["item"] for row in rows if row["label"] not in allowed[row["kind"]]]
    if bad:
        raise LabellingError(
            f"{path}: items {', '.join(bad)} have no label; write {' or '.join(VERDICTS)} on a "
            f"judge row and {' or '.join(ANSWERS)} on a retrieval row"
        )
    return rows


def judge_labels(rows: list[dict]) -> dict[str, str]:
    """The labels of the judge rows, by the sheet's row number."""
    return {row["item"][1:]: row["label"] for row in rows if row["kind"] == JUDGE}


def retrieval_agreement(rows: list[dict], cases: list[dict]) -> dict:
    """The person's answers against the model's labels, section by section and by case."""
    labelled = {case["id"]: set(case["relevant"]) for case in cases}
    table = {(person, model): 0 for person in ANSWERS for model in ANSWERS}
    by_case: dict[str, dict] = {}
    for row in (r for r in rows if r["kind"] == RETRIEVAL):
        if row["case"] not in labelled:
            raise LabellingError(f"item {row['item']}: case {row['case']!r} is not in the cases")
        model = "yes" if row["section"] in labelled[row["case"]] else "no"
        table[(row["label"], model)] += 1
        case = by_case.setdefault(row["case"], {"person": set(), "model": set()})
        if row["label"] == "yes":
            case["person"].add(row["section"])
        if model == "yes":
            case["model"].add(row["section"])
    compared = sum(table.values())
    same = sum(table[(answer, answer)] for answer in ANSWERS)
    return {
        "sections": compared,
        "cases": len(by_case),
        "table": {f"{person}/{model}": n for (person, model), n in table.items()},
        "agreement": same / compared if compared else None,
        "kappa": calibration.kappa(table),
        "cases_a_labelled_section_answers": sum(
            1 for c in by_case.values() if c["person"] & c["model"]
        ),
        "cases_no_section_answers": sum(1 for c in by_case.values() if not c["person"]),
        "cases_same_sections": sum(1 for c in by_case.values() if c["person"] == c["model"]),
    }


def render_retrieval(result: dict) -> str:
    def share(value: float | None) -> str:
        return "not defined" if value is None else f"{value:.3f}"

    t = result["table"]
    return "\n".join(
        [
            "| The person's answers against the model's labels | |",
            "|---|---|",
            f"| Cases | {result['cases']} |",
            f"| Sections judged | {result['sections']} |",
            f"| Percent agreement, by section | {share(result['agreement'])} |",
            f"| Cohen's kappa, by section | {share(result['kappa'])} |",
            "| Cases where a section the model labelled answers, for the person "
            f"| {result['cases_a_labelled_section_answers']} |",
            f"| Cases where no section shown answers, for the person "
            f"| {result['cases_no_section_answers']} |",
            f"| Cases where the two chose the same sections | {result['cases_same_sections']} |",
            "",
            "| Person, down; model's labels, across | yes | no |",
            "|---|---|---|",
            f"| yes | {t['yes/yes']} | {t['yes/no']} |",
            f"| no | {t['no/yes']} | {t['no/no']} |",
            "",
        ]
    )


def score(filled: Path, verdicts: list[dict], cases: list[dict]) -> str:
    rows = read_filled(filled)
    person = {"labelled_by": "person", "who": f"the person who filled {filled.name}"}
    lines = [
        f"Labels: {filled.name}, {len(rows)} rows.",
        "",
        "## The judge",
        "",
        calibration.render(calibration.agree(judge_labels(rows), verdicts), person),
        "Altered rows caught: not computed here, because it needs the sheet's key; see "
        "evals/calibration/LABELLING.md.",
        "",
        "## Retrieval",
        "",
        render_retrieval(retrieval_agreement(rows, cases)),
    ]
    return "\n".join(lines)


def to_sheet(filled: Path, sheet: Path, who: str) -> int:
    """Write the person's judge labels into the sheet and say, beside it, that a person did."""
    if not who.strip():
        raise LabellingError("--who must say who labelled")
    labels = judge_labels(read_filled(filled))
    with sheet.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != SHEET_COLUMNS:
            raise LabellingError(f"{sheet}: the columns must be {', '.join(SHEET_COLUMNS)}")
        rows = list(reader)
    if set(labels) != {row["row"] for row in rows}:
        raise LabellingError(f"{filled}: its judge rows are not the rows of {sheet}")
    for row in rows:
        row["label"] = labels[row["row"]]
    sheet.write_text(calibration.sheet_text(rows), encoding="utf-8")
    about = {
        "labelled_by": "person",
        "who": who.strip(),
        "note": f"Copied from {filled.name} by python -m evalkit.labelling to-sheet.",
    }
    calibration.labels_file(sheet).write_text(json.dumps(about, indent=1) + "\n", encoding="utf-8")
    return len(rows)


# --- the command -----------------------------------------------------------------------------


def _stop(text: str) -> int:
    print(text, file=sys.stderr)
    return SETUP_ERROR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.labelling", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    making = commands.add_parser("kit", help="write the sheet a person fills")
    making.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    making.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    making.add_argument("--count", type=int, default=DEFAULT_COUNT)
    making.add_argument("--top", type=int, default=DEFAULT_TOP)
    making.add_argument("--seed", type=int, default=DEFAULT_SEED)
    making.add_argument("--out", type=Path, default=None, help="default: under the data directory")
    scoring = commands.add_parser("score", help="the agreements of a filled sheet")
    scoring.add_argument("filled", type=Path)
    scoring.add_argument("--verdicts", type=Path, required=True)
    scoring.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    copying = commands.add_parser("to-sheet", help="copy the judge labels into the sheet")
    copying.add_argument("filled", type=Path)
    copying.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    copying.add_argument("--who", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "kit":
            out = args.out or default_out()
            if not calibration._outside_the_repository(out):
                return _stop(f"the kit goes outside the repository, not to {out}")
            if out.exists():
                return _stop(f"{out} already exists; nothing was written")
            rows = build(
                args.sheet,
                args.cases,
                count=args.count,
                top=args.top,
                seed=args.seed,
                root=config.REPO_ROOT,
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(kit_text(rows), encoding="utf-8")
            judged = sum(1 for row in rows if row["kind"] == JUDGE)
            cases = len({row["case"] for row in rows if row["kind"] == RETRIEVAL})
            print(
                f"{out}: {judged} judge rows and {len(rows) - judged} retrieval rows "
                f"for {cases} cases"
            )
            return 0
        if args.command == "score":
            verdicts = json.loads(args.verdicts.read_text(encoding="utf-8"))["verdicts"]
            cases = retrieval.load_cases(args.cases)
            sys.stdout.write(score(args.filled, verdicts, cases))
            return 0
        n = to_sheet(args.filled, args.sheet, args.who)
        said = calibration.labels_file(args.sheet).name
        print(f"{args.sheet}: {n} labels written; {said} says person")
        return 0
    except (LabellingError, calibration.CalibrationError, retrieval.CasesError) as problem:
        return _stop(str(problem))
    except (OSError, json.JSONDecodeError, KeyError) as problem:
        return _stop(f"{type(problem).__name__}: {problem}")


if __name__ == "__main__":
    sys.exit(main())
