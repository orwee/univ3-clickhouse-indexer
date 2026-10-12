"""Calibrating the judge against a person: the sheet to label, and the agreement.

    PYTHONPATH=src uv run python -m evalkit.calibration build RESULTS [RESULTS ...] \\
        [--split dev] [--seed 20261011] [--sheet evals/calibration/sheet.csv] [--key FILE]
    PYTHONPATH=src uv run python -m evalkit.calibration agree SHEET VERDICTS [--key FILE]

``build`` makes the sheet a person labels. From the results of real runs it takes thirty
answered questions, each a different case. Fifteen keep the explanation the agent wrote.
The other fifteen get an explanation altered on purpose, by code and not by a model, in
one of four ways:

``number``        a number in the explanation is replaced by another;
``unit``          the unit is replaced by the unit of another case;
``name_or_date``  a date is moved, or a name the query filters on is replaced by a name
                  from another case's query;
``claim``         a sentence is added that no query here supports.

So fifteen rows are known to be unfaithful, and how. The thirty are drawn with a fixed
seed, stratified by the kind of case, and written in random order with an empty column for
the label. Nothing in the sheet says which rows were altered: that is the key, a second
file, which is written under the data directory and stays out of the repository until the
labels are committed. A person who could see the key would not be labelling.

``agree`` compares the labels a person wrote in the sheet with the verdicts of
``python -m evalkit.judge`` on the same sheet: percent agreement, Cohen's kappa and the
two-by-two table. With the key it also says how many of the altered rows each of the two
called unfaithful, by kind of alteration.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import io
import json
import random
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from evalkit.judge import SHEET_COLUMNS, VERDICTS
from univ3_indexer import config

DEFAULT_SHEET = config.REPO_ROOT / "evals" / "calibration" / "sheet.csv"
DEFAULT_SEED = 20261011
REAL, ALTERED = 15, 15
ALTERATIONS = ("number", "unit", "name_or_date", "claim")
# A sentence no query supports: a query returns rows, it does not check them elsewhere.
CLAIM = "The figure was also checked against a second, independent source, and it matched."
SETUP_ERROR = 2

_DATE = re.compile(r"\b(\d{4})-(\d\d)-(\d\d)\b")
_NUMBER = re.compile(r"(?<![\w.,-])\d[\d,]*(?:\.\d+)?(?![\w-])")
_LITERAL = re.compile(r"'([^']+)'")


class CalibrationError(ValueError):
    """The sheet cannot be built, or the labels cannot be compared."""


def default_key() -> Path:
    """``<data dir>/calibration/key.json``. The data directory is never inside the repository."""
    return config.data_dir() / "calibration" / "key.json"


# --- the four alterations --------------------------------------------------------------------


def alter_number(text: str) -> str | None:
    """Replace the first number that is not part of a date by a different one."""
    dates = [match.span() for match in _DATE.finditer(text)]
    for match in _NUMBER.finditer(text):
        if any(start <= match.start() < end for start, end in dates):
            continue
        written = match.group()
        try:
            value = Decimal(written.replace(",", ""))
        except InvalidOperation:
            continue
        decimals = len(written.partition(".")[2])
        changed = value * Decimal("1.37") + 3  # never the same number, never a rounding of it
        shown = f"{changed:,.{decimals}f}" if "," in written else f"{changed:.{decimals}f}"
        return text[: match.start()] + shown + text[match.end() :]
    return None


def alter_unit(text: str, unit: str | None, units: list[str]) -> str | None:
    """Replace the case's unit, where the explanation states it, by another case's unit."""
    if not unit or not re.search(rf"(?<!\w){re.escape(unit)}(?!\w)", text):
        return None
    others = [other for other in units if other != unit and other not in unit and unit not in other]
    if not others:
        return None
    return re.sub(rf"(?<!\w){re.escape(unit)}(?!\w)", others[0], text)


def alter_name_or_date(text: str, sql: str, names: list[str]) -> str | None:
    """Move the first date by a week; with no date, replace a name the query filters on."""
    match = _DATE.search(text)
    if match:
        try:
            day = datetime.date(*(int(part) for part in match.groups()))
        except ValueError:
            day = None
        if day is not None:
            moved = (day + datetime.timedelta(days=7)).isoformat()
            return text[: match.start()] + moved + text[match.end() :]
    for name in _LITERAL.findall(sql):
        if _DATE.fullmatch(name) or name not in text:
            continue
        others = [other for other in names if other != name and other not in text]
        if others:
            return text.replace(name, others[0])
    return None


def add_claim(text: str) -> str:
    return text.rstrip() + " " + CLAIM


def alter(text: str, how: str, sql: str, unit: str | None, units: list[str], names: list[str]):
    """The explanation altered in one way, or None when that way does not apply to it."""
    if how == "number":
        return alter_number(text)
    if how == "unit":
        return alter_unit(text, unit, units)
    if how == "name_or_date":
        return alter_name_or_date(text, sql, names)
    return add_claim(text)


# --- the sheet -------------------------------------------------------------------------------


def candidates(files: list[tuple[str, dict]], split: str) -> list[dict]:
    """One answered record per case, the first found, with its explanation and its result."""
    found: dict[str, dict] = {}
    for name, results in files:
        for record in results["records"]:
            case = results["cases"][record["id"]]
            result = record.get("result") or {}
            answer = result.get("answer") or {}
            explanation = answer.get("explanation")
            if record["status"] != "ran" or result.get("status") != "answered":
                continue
            if split != "all" and case.get("split") != split:
                continue
            if not isinstance(explanation, str) or not explanation.strip():
                continue
            if record["id"] in found or not result.get("final_sql"):
                continue
            found[record["id"]] = {
                "id": record["id"],
                "repetition": record["repetition"],
                "source": name,
                "kind": case["kind"],
                "unit": case.get("unit"),
                "question": case["question"],
                "sql": result["final_sql"],
                "result": result.get("last_result") or {"columns": [], "rows": [], "row_count": 0},
                "explanation": " ".join(explanation.split()),
            }
    return [found[case_id] for case_id in sorted(found)]


def stratified(population: list[dict], wanted: int, seed: int) -> list[dict]:
    """``wanted`` of them, each kind with its share (largest remainder), a fixed seed.

    Within a kind the order is a seeded shuffle. The result alternates down each kind, so
    that taking every other one splits every kind in two.
    """
    if len(population) < wanted:
        raise CalibrationError(
            f"{wanted} answered cases with an explanation are needed, and there are "
            f"{len(population)}"
        )
    kinds: dict[str, list[dict]] = {}
    for candidate in population:
        kinds.setdefault(candidate["kind"], []).append(candidate)
    shares = {kind: wanted * len(group) / len(population) for kind, group in kinds.items()}
    take = {kind: int(share) for kind, share in shares.items()}
    by_remainder = sorted(kinds, key=lambda kind: (take[kind] - shares[kind], kind))
    for kind in by_remainder[: wanted - sum(take.values())]:
        take[kind] += 1
    chosen = []
    for kind in sorted(kinds):
        group = sorted(kinds[kind], key=lambda candidate: candidate["id"])
        random.Random(f"{seed}:{kind}").shuffle(group)  # noqa: S311 - a reproducible draw
        chosen += group[: take[kind]]
    return chosen


def build(files: list[tuple[str, dict]], *, split: str = "dev", seed: int = DEFAULT_SEED):
    """The rows of the sheet, in the order they are written, and the key.

    Returns ``(rows, key)``. A row has the columns of the sheet, the label empty. The key
    has one entry per row: which case it is, whether its explanation was altered, how, and
    what it said before.
    """
    population = candidates(files, split)
    chosen = stratified(population, REAL + ALTERED, seed)
    units = sorted({c["unit"] for c in population if c["unit"]})
    names = sorted(
        {
            name
            for c in population
            for name in _LITERAL.findall(c["sql"])
            if not _DATE.fullmatch(name)
        }
    )
    entries = []
    altered = 0
    for position, candidate in enumerate(chosen):
        entry = {**candidate, "altered": False, "how": None, "original_explanation": None}
        if position % 2 == 1:  # every other one, so each kind is split in two
            for attempt in range(len(ALTERATIONS)):
                how = ALTERATIONS[(altered + attempt) % len(ALTERATIONS)]
                text = alter(
                    candidate["explanation"], how, candidate["sql"], candidate["unit"], units, names
                )
                if text is not None and text != candidate["explanation"]:
                    break
            entry.update(
                altered=True,
                how=how,
                original_explanation=candidate["explanation"],
                explanation=text,
            )
            altered += 1
        entries.append(entry)
    random.Random(f"{seed}:order").shuffle(entries)  # noqa: S311 - a reproducible order
    rows, key = [], []
    for number, entry in enumerate(entries, start=1):
        rows.append(
            {
                "row": str(number),
                "question": entry["question"],
                "sql": entry["sql"],
                "result": json.dumps(entry["result"], ensure_ascii=False),
                "explanation": entry["explanation"],
                "label": "",
            }
        )
        key.append(
            {
                "row": str(number),
                "id": entry["id"],
                "repetition": entry["repetition"],
                "source": entry["source"],
                "altered": entry["altered"],
                "how": entry["how"],
                "original_explanation": entry["original_explanation"],
            }
        )
    return rows, key


def sheet_text(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=SHEET_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


# --- the agreement ---------------------------------------------------------------------------


def kappa(table: dict[tuple[str, str], int]) -> float | None:
    """Cohen's kappa of a square table ``{(first, second): count}``.

    ``(po - pe) / (1 - pe)``: ``po`` is the share of items the two agree on, ``pe`` the share
    they would agree on by chance, given how often each uses each label. None when there is
    nothing to compare, or when chance agreement is already complete (both always give the
    same single label), where the ratio is not defined.
    """
    total = sum(table.values())
    if total == 0:
        return None
    labels = sorted({label for pair in table for label in pair})
    observed = sum(table.get((label, label), 0) for label in labels) / total
    chance = sum(
        (sum(n for (first, _), n in table.items() if first == label) / total)
        * (sum(n for (_, second), n in table.items() if second == label) / total)
        for label in labels
    )
    if chance == 1:
        return None
    return (observed - chance) / (1 - chance)


def read_labels(sheet: Path) -> dict[str, str]:
    """The labels a person wrote, by row. Every row needs one of the two verdicts."""
    with sheet.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != SHEET_COLUMNS:
            raise CalibrationError(f"{sheet}: the columns must be {', '.join(SHEET_COLUMNS)}")
        rows = list(reader)
    labels = {row["row"]: row["label"].strip() for row in rows}
    bad = [row for row, label in labels.items() if label not in VERDICTS]
    if bad:
        raise CalibrationError(
            f"{sheet}: rows {', '.join(bad)} have no label; write {' or '.join(VERDICTS)}"
        )
    return labels


def agree(labels: dict[str, str], verdicts: list[dict], key: list[dict] | None = None) -> dict:
    """Agreement between a person's labels and the judge's verdicts on the same rows."""
    judged = {v["key"]: v["verdict"] for v in verdicts if v.get("verdict") in VERDICTS}
    both = sorted(set(labels) & set(judged), key=lambda row: (len(row), row))
    table = {(person, judge): 0 for person in VERDICTS for judge in VERDICTS}
    for row in both:
        table[(labels[row], judged[row])] += 1
    same = sum(table[(label, label)] for label in VERDICTS)
    out = {
        "rows": len(labels),
        "compared": len(both),
        "without_a_verdict": sorted(set(labels) - set(judged), key=lambda row: (len(row), row)),
        "table": {f"{person}/{judge}": n for (person, judge), n in table.items()},
        "agreement": same / len(both) if both else None,
        "kappa": kappa(table),
    }
    if key is not None:
        against = {}
        for how in (*ALTERATIONS, None):
            rows = [entry["row"] for entry in key if entry["how"] == how]
            wanted = "faithful" if how is None else "unfaithful"
            against[how or "not altered"] = {
                "rows": len(rows),
                "expected": wanted,
                "person": sum(1 for row in rows if labels.get(row) == wanted),
                "judge": sum(1 for row in rows if judged.get(row) == wanted),
            }
        out["against_the_key"] = against
    return out


def render(result: dict) -> str:
    def share(value: float | None) -> str:
        return "not defined" if value is None else f"{value:.3f}"

    t = result["table"]
    lines = [
        "| Agreement between the person and the judge | |",
        "|---|---|",
        f"| Rows of the sheet | {result['rows']} |",
        f"| Rows with a label and a verdict | {result['compared']} |",
        f"| Rows the judge gave no verdict on | {len(result['without_a_verdict'])} |",
        f"| Percent agreement | {share(result['agreement'])} |",
        f"| Cohen's kappa | {share(result['kappa'])} |",
        "",
        "| Person, down; judge, across | faithful | unfaithful |",
        "|---|---|---|",
        f"| faithful | {t['faithful/faithful']} | {t['faithful/unfaithful']} |",
        f"| unfaithful | {t['unfaithful/faithful']} | {t['unfaithful/unfaithful']} |",
        "",
    ]
    if "against_the_key" in result:
        lines += [
            "| Rows, by what the key says | Rows | Expected | Person | Judge |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {how} | {v['rows']} | {v['expected']} | {v['person']} | {v['judge']} |"
            for how, v in result["against_the_key"].items()
        ]
        lines.append("")
    return "\n".join(lines)


# --- the command -----------------------------------------------------------------------------


def _stop(text: str) -> int:
    print(text, file=sys.stderr)
    return SETUP_ERROR


def _outside_the_repository(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != config.REPO_ROOT and config.REPO_ROOT not in resolved.parents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.calibration", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    making = commands.add_parser("build", help="write the sheet to label, and its key")
    making.add_argument("results", type=Path, nargs="+", help="results files of real runs")
    making.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    making.add_argument("--seed", type=int, default=DEFAULT_SEED)
    making.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    making.add_argument("--key", type=Path, default=None, help="default: under the data directory")
    comparing = commands.add_parser("agree", help="compare the labels with the judge's verdicts")
    comparing.add_argument("sheet", type=Path)
    comparing.add_argument("verdicts", type=Path, help="the output of python -m evalkit.judge")
    comparing.add_argument("--key", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            key_path = args.key or default_key()
            if not _outside_the_repository(key_path):
                return _stop(f"the key goes outside the repository, not to {key_path}")
            if args.sheet.exists() or key_path.exists():
                return _stop("the sheet or the key already exists; nothing was written")
            files = [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in args.results]
            rows, key = build(files, split=args.split, seed=args.seed)
            text = sheet_text(rows)
            args.sheet.parent.mkdir(parents=True, exist_ok=True)
            args.sheet.write_text(text, encoding="utf-8")
            key_path.parent.mkdir(parents=True, exist_ok=True)
            about = {
                "seed": args.seed,
                "split": args.split,
                "sheet_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "rows": key,
            }
            key_path.write_text(json.dumps(about, indent=1) + "\n", encoding="utf-8")
            how = [entry["how"] for entry in key if entry["altered"]]
            counted = ", ".join(f"{name} {how.count(name)}" for name in ALTERATIONS)
            print(f"{len(rows)} rows written to {args.sheet}; {len(how)} altered ({counted})")
            print(f"key: {key_path} (outside the repository)")
            return 0
        labels = read_labels(args.sheet)
        verdicts = json.loads(args.verdicts.read_text(encoding="utf-8"))["verdicts"]
        key = None
        if args.key is not None:
            key = json.loads(args.key.read_text(encoding="utf-8"))["rows"]
        sys.stdout.write(render(agree(labels, verdicts, key)))
        return 0
    except CalibrationError as problem:
        return _stop(str(problem))
    except (OSError, json.JSONDecodeError, KeyError) as problem:
        return _stop(f"{type(problem).__name__}: {problem}")


if __name__ == "__main__":
    sys.exit(main())
