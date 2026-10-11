"""The golden set: questions whose right answer is computed, not written.

A case is a question, the query that answers it, and the answer that query gave on the
committed fixture. Nobody types an answer: the generator loads the fixture into a
throw-away ``test_*`` database, runs every ``reference_sql`` there and stores what came
back. So the ground truth is deterministic SQL on verified data, and it does not depend on
any model. It is never computed against the live warehouse.

This module is generic. It knows the shape of a case, how to turn a query result into a
stored answer, how to split cases and how to write the file. What the questions are about
lives under ``evals/``: a templates module that draws parametrised cases with a fixed
seed, and (optionally) a YAML of cases written by hand. Both give ``Spec`` objects, cases
without their answer.

    PYTHONPATH=src uv run python -m evalkit.golden \\
        --templates evals/golden_templates.py --out evals/golden.jsonl
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import random
import sys
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from agent import sql_guard
from agent.tools import json_safe
from evalkit import fixture
from univ3_indexer import clickhouse as ch

FIELDS = (
    "id",
    "question",
    "kind",
    "family",
    "split",
    "answer_type",
    "expected",
    "accepted",
    "unit",
    "tolerance",
    "reference_sql",
    "notes",
)
KINDS = ("template", "hand", "unanswerable")
SPLITS = ("dev", "test")
ANSWER_TYPES = ("number", "label", "date", "list", "refusal")
DEV_SHARE = 3  # one case in three goes to dev, the rest to test
DEFAULT_SEED = 20260925

# A number passes when it is within EITHER bound. Both zero means exact.
#   count     an integer that was counted: exact.
#   sum       an amount of money added up: a cent, or a tenth of a percent, whichever is
#             looser.
#   quantity  an amount added up in a unit that has no cent: a tenth of a percent, relative
#             only. One unit may be worth a cent or thousands of dollars, so an absolute
#             bound that suits one such unit accepts almost any number, zero included, for
#             another.
#   ratio     a ratio, a share or a price: half a percent, relative only.
TOLERANCES: dict[str, dict[str, str]] = {
    "count": {"abs": "0", "rel": "0"},
    "sum": {"abs": "0.01", "rel": "0.001"},
    "quantity": {"abs": "0", "rel": "0.001"},
    "ratio": {"abs": "0", "rel": "0.005"},
}


class GoldenError(ValueError):
    """A case is malformed, or its query did not give one usable answer."""


@dataclass(frozen=True)
class Spec:
    """A case before its answer is computed.

    ``tolerance`` is a key of ``TOLERANCES`` or a dict of its own (and then ``notes`` says
    why); None for an answer that is not a number. ``accepted_sql`` are queries for other
    reasonable readings of the question: their answers go into ``accepted``. ``unique_sql``
    returns how many rows share the maximum the question asks for, and must give 1.
    ``params`` is for tests; it is not written to the file.
    """

    id: str
    question: str
    kind: str
    family: str
    answer_type: str
    unit: str | None
    reference_sql: str | None
    notes: str
    tolerance: str | dict | None = None
    accepted_sql: tuple[str, ...] = ()
    unique_sql: str | None = None
    params: dict = field(default_factory=dict)


def plain_number(value: object) -> str:
    """A number as text in plain notation, every digit kept."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise GoldenError(f"not a number: {value!r}")
    if isinstance(value, float):
        value = Decimal(repr(value))
    if not Decimal(value).is_finite():
        raise GoldenError(f"not a finite number: {value!r}")
    return str(json_safe(value))


def _cell(value: object, answer_type: str) -> object:
    if value is None:
        raise GoldenError("the query returned NULL")
    if answer_type == "number":
        return plain_number(value)
    if answer_type == "date":
        if isinstance(value, datetime.datetime) or not isinstance(value, datetime.date):
            raise GoldenError(f"not a date: {value!r}")
        return value.isoformat()
    safe = json_safe(value)
    return safe if isinstance(safe, str) else str(safe)


def answer(client, sql: str, answer_type: str) -> object:
    """Run one reference query and return its answer in the form the file stores.

    A number, a label and a date are one row of one column. A list is one column, one row
    per element, in the order of the query; its elements are stored as text.
    """
    verdict = sql_guard.check(sql)
    if not verdict.allowed:
        raise GoldenError(f"not one SELECT statement: {verdict.message}")
    rows = client.query(sql).result_rows
    if any(len(row) != 1 for row in rows):
        raise GoldenError("the query must return exactly one column")
    if answer_type == "list":
        if not rows:
            raise GoldenError("the query returned no rows for a list")
        return [_list_item(row[0]) for row in rows]
    if len(rows) != 1:
        raise GoldenError(f"the query returned {len(rows)} rows, not one")
    return _cell(rows[0][0], answer_type)


def _list_item(value: object) -> str:
    if value is None:
        raise GoldenError("the query returned NULL inside a list")
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return plain_number(value)
    safe = json_safe(value)
    return safe if isinstance(safe, str) else str(safe)


def tolerance_of(spec: Spec) -> dict | None:
    if spec.answer_type != "number":
        if spec.tolerance is not None:
            raise GoldenError(f"{spec.id}: only a number has a tolerance")
        return None
    chosen = spec.tolerance
    if isinstance(chosen, str):
        if chosen not in TOLERANCES:
            raise GoldenError(f"{spec.id}: unknown tolerance {chosen!r}")
        return dict(TOLERANCES[chosen])
    if not isinstance(chosen, dict) or set(chosen) != {"abs", "rel"}:
        raise GoldenError(f"{spec.id}: a number needs a tolerance with abs and rel")
    return {key: plain_number(Decimal(str(chosen[key]))) for key in ("abs", "rel")}


def assign_splits(specs: list[Spec], seed: int = DEFAULT_SEED) -> dict[str, str]:
    """dev or test for every case: stratified by family, one third dev, a fixed seed.

    Within a family, ``round(n / 3)`` cases go to dev. The draw depends on the seed and on
    the ids of that family only, so adding a family does not move the others.
    """
    by_family: dict[str, list[str]] = {}
    for spec in specs:
        by_family.setdefault(f"{spec.kind}:{spec.family}", []).append(spec.id)
    splits = {}
    for family, ids in by_family.items():
        ids = sorted(ids)
        dev = set(random.Random(f"{seed}:{family}").sample(ids, round(len(ids) / DEV_SHARE)))  # noqa: S311
        splits.update({case_id: "dev" if case_id in dev else "test" for case_id in ids})
    return splits


def build(specs: list[Spec], client, seed: int = DEFAULT_SEED) -> list[dict]:
    """Compute every answer with ``client``, whose default database holds the fixture."""
    ids = [spec.id for spec in specs]
    if len(set(ids)) != len(ids):
        raise GoldenError("two cases have the same id")
    splits = assign_splits(specs, seed)
    cases = []
    for spec in specs:
        try:
            expected, accepted = None, []
            if spec.answer_type != "refusal":
                expected = answer(client, spec.reference_sql or "", spec.answer_type)
                for other in spec.accepted_sql:
                    also = answer(client, other, spec.answer_type)
                    if also != expected and also not in accepted:
                        accepted.append(also)
            elif spec.reference_sql is not None or spec.accepted_sql:
                raise GoldenError("a refusal has no query")
            if spec.unique_sql is not None:
                sharing = client.query(spec.unique_sql).result_rows
                if sharing != [(1,)]:
                    raise GoldenError(f"the maximum is not unique: {sharing}")
        except GoldenError as problem:
            raise GoldenError(f"{spec.id}: {problem}") from None
        case = {
            "id": spec.id,
            "question": spec.question,
            "kind": spec.kind,
            "family": spec.family,
            "split": splits[spec.id],
            "answer_type": spec.answer_type,
            "expected": expected,
            "accepted": accepted,
            "unit": spec.unit,
            "tolerance": tolerance_of(spec),
            "reference_sql": spec.reference_sql,
            "notes": spec.notes,
        }
        validate(case)
        cases.append(case)
    return cases


def _is_number_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return Decimal(value).is_finite()
    except ArithmeticError:
        return False


def _is_answer(value: object, answer_type: str) -> bool:
    if answer_type == "number":
        return _is_number_text(value)
    if answer_type == "date":
        try:
            return (
                isinstance(value, str) and datetime.date.fromisoformat(value).isoformat() == value
            )
        except ValueError:
            return False
    if answer_type == "list":
        return isinstance(value, list) and bool(value) and all(isinstance(v, str) for v in value)
    return isinstance(value, str) and bool(value.strip())


def validate(case: dict) -> None:
    """Every field present and of the right type. Raises ``GoldenError`` naming the case."""

    def bad(what: str) -> GoldenError:
        return GoldenError(f"{case.get('id', '?')}: {what}")

    if tuple(case) != FIELDS:
        raise bad(f"the fields must be exactly {', '.join(FIELDS)}, in that order")
    for name in ("id", "question", "family", "notes"):
        if not isinstance(case[name], str) or not case[name].strip():
            raise bad(f"{name} must be a non-empty text")
    if case["kind"] not in KINDS or case["split"] not in SPLITS:
        raise bad("unknown kind or split")
    answer_type = case["answer_type"]
    if answer_type not in ANSWER_TYPES:
        raise bad("unknown answer_type")
    if not isinstance(case["accepted"], list):
        raise bad("accepted must be a list")
    if case["unit"] is not None and not isinstance(case["unit"], str):
        raise bad("unit must be a text or null")
    if (case["kind"] == "unanswerable") != (answer_type == "refusal"):
        raise bad("a case with no answer is a refusal, and only such a case is")
    if answer_type == "refusal":
        if case["expected"] is not None or case["accepted"] or case["reference_sql"] is not None:
            raise bad("a refusal has no expected value, no accepted values and no query")
        if case["tolerance"] is not None:
            raise bad("a refusal has no tolerance")
        return
    sql = case["reference_sql"]
    if not isinstance(sql, str) or not sql_guard.check(sql).allowed:
        raise bad("reference_sql must be one SELECT statement")
    for value in (case["expected"], *case["accepted"]):
        if not _is_answer(value, answer_type):
            raise bad(f"{value!r} is not a {answer_type}")
    tolerance = case["tolerance"]
    if answer_type == "number":
        if (
            not isinstance(tolerance, dict)
            or set(tolerance) != {"abs", "rel"}
            or not all(_is_number_text(v) and Decimal(v) >= 0 for v in tolerance.values())
        ):
            raise bad("a number needs a tolerance with abs and rel, both as text")
    elif tolerance is not None:
        raise bad("only a number has a tolerance")


def dumps(cases: list[dict]) -> str:
    """One case per line, fields in the fixed order. The same cases give the same bytes."""
    return "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases)


def load(path: Path) -> list[dict]:
    cases = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
    for case in cases:
        validate(case)
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise GoldenError(f"{path}: two cases have the same id")
    return cases


def load_module(path: Path):
    """Import a file under evals/ by its path: it is not a package."""
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def collect(templates: Path, hand: Path | None, seed: int) -> list[Spec]:
    """Every case without its answer. Needs no server: the draws read the fixture files."""
    specs = list(load_module(templates).draw(seed))
    if hand is not None:
        from evalkit import hand_cases

        specs += hand_cases.load(hand)
    return specs


def generate(admin, templates: Path, hand: Path | None = None, seed: int = DEFAULT_SEED) -> str:
    """The whole file as text. ``admin`` may create and drop a ``test_*`` database.

    The fixture is loaded into a database that exists only for this call; the answers are
    computed there and the database is dropped, also when something fails.
    """
    specs = collect(templates, hand, seed)
    database = f"test_{uuid.uuid4().hex[:12]}"
    admin.command(f"CREATE DATABASE {database}")
    try:
        fixture.load(admin, database)
        return dumps(build(specs, ch.connect(database=database), seed))
    finally:
        admin.command(f"DROP DATABASE IF EXISTS {database}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.golden", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--hand", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    text = generate(ch.connect(database="default"), args.templates, args.hand, args.seed)
    args.out.write_text(text, encoding="utf-8")
    cases = load(args.out)
    counts: dict[tuple[str, str], int] = {}
    for case in cases:
        counts[(case["kind"], case["split"])] = counts.get((case["kind"], case["split"]), 0) + 1
    summary = ", ".join(f"{kind} {split} {n}" for (kind, split), n in sorted(counts.items()))
    print(f"{len(cases)} cases written to {args.out}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
