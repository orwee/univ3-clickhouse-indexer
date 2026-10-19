"""A small, fixed set of cases for a check on every change, and the rule it is judged by.

    PYTHONPATH=src uv run python -m evalkit.ci select --runs R1 R2 R3 \\
        --quota KIND=N [--quota KIND=N ...] [--seed N] --out cases.json
    PYTHONPATH=src uv run python -m evalkit.ci baseline --cases cases.json --runs R1 R2 R3 \\
        --repeats R4 R5 R6 --out baseline.json
    PYTHONPATH=src uv run python -m evalkit.ci check RESULTS --cases cases.json \\
        --baseline baseline.json [--summary FILE]

``select`` picks the cases, by code and with a fixed seed, from runs already made: only
cases that every one of those runs got right, so many of each kind, spread over the
families of the kind. Cases of the split named first are preferred; another split is used
only when the first cannot fill a kind, and the file says how many came from it.

``baseline`` writes what a later run is compared with: how often each case was right in
the runs it was picked from, what a question cost in them, and how many of these cases
each of a set of identical runs got wrong. That last list is the noise: runs of the same
thing do not all get the same cases right. The most cases a run may get wrong is the worst
of those counts, plus one. The threshold is read from runs, not chosen.

``check`` applies the rule to a new run of those cases, and exits 0 when it passes and 1
when it does not. A run fails when:

- it did not ask every case, whatever the reason: stopping on its budget is a failure of
  the run, not a score;
- any question ended in an error;
- more cases are wrong than the threshold;
- the mean cost of a question is over ``COST_FACTOR`` times the baseline's on these cases.

Nothing here asks a model, and nothing here asks twice: a run that fails is not run again
to see whether it passes.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from decimal import Decimal
from pathlib import Path

from evalkit import runs

DEFAULT_SEED = 20261013
COST_FACTOR = Decimal("1.5")
MARGIN = 1  # cases, added to the worst count among the identical runs
FORMAT = 1
SETUP_ERROR = 2


class CIError(ValueError):
    """The cases cannot be picked, or a file is not what it should be."""


def _scored(results: dict) -> dict[str, dict]:
    """Every record of a run that was asked and did not end in an error, by case id."""
    return {
        record["id"]: record
        for record in results["records"]
        if record["status"] == "ran" and not record["score"].get("error")
    }


def right_in_all(files: list[tuple[str, dict]]) -> list[str]:
    """The cases every one of the runs scored and got right."""
    per_run = [_scored(results) for _, results in files]
    shared = set(per_run[0]).intersection(*per_run[1:])
    return sorted(i for i in shared if all(run[i]["score"]["correct"] for run in per_run))


def spread(candidates: list[dict], wanted: int, seed: str) -> list[dict]:
    """``wanted`` of the candidates, one family at a time in turn, so that no family gives
    its second case before every family has given its first. A fixed seed decides the order
    of the families and of the cases inside each."""
    by_family: dict[str, list[dict]] = {}
    for case in sorted(candidates, key=lambda c: c["id"]):
        by_family.setdefault(case["family"], []).append(case)
    families = sorted(by_family)
    random.Random(f"{seed}:families").shuffle(families)  # noqa: S311 - a reproducible pick
    for family in families:
        random.Random(f"{seed}:{family}").shuffle(by_family[family])  # noqa: S311
    picked: list[dict] = []
    while len(picked) < wanted and any(by_family.values()):
        for family in families:
            if by_family[family] and len(picked) < wanted:
                picked.append(by_family[family].pop(0))
    return picked


def select(
    files: list[tuple[str, dict]],
    quotas: dict[str, int],
    seed: int = DEFAULT_SEED,
    prefer: tuple[str, ...] = ("dev", "test"),
) -> dict:
    """The cases of the check, and where they came from."""
    cases = files[0][1]["cases"]
    stable = [cases[case_id] for case_id in right_in_all(files)]
    chosen, borrowed = [], {}
    for kind, wanted in quotas.items():
        of_kind = [case for case in stable if case["kind"] == kind]
        picked: list[dict] = []
        for split in prefer:
            if len(picked) < wanted:
                here = [case for case in of_kind if case["split"] == split]
                more = spread(here, wanted - len(picked), f"{seed}:{kind}:{split}")
                if split != prefer[0] and more:
                    borrowed[kind] = len(more)
                picked += more
        if len(picked) < wanted:
            raise CIError(f"{kind}: {wanted} cases are wanted and {len(picked)} qualify")
        chosen += picked
    return {
        "format": FORMAT,
        "seed": seed,
        "picked_from": [name for name, _ in files],
        "rule": "right in every one of those runs; so many of each kind, spread over its families",
        "quotas": dict(quotas),
        "preferred_split": prefer[0],
        "from_another_split": borrowed,
        "golden_sha256": files[0][1]["golden_sha256"],
        "cases": [
            {"id": c["id"], "kind": c["kind"], "family": c["family"], "split": c["split"]}
            for c in sorted(chosen, key=lambda c: c["id"])
        ],
    }


def ids_of(cases_file: dict) -> list[str]:
    return [case["id"] for case in cases_file["cases"]]


def counts(results: dict, ids: list[str]) -> dict:
    """What one run did with the cases: how many it asked, got wrong, ended in an error,
    and what a question cost."""
    by_id = {record["id"]: record for record in results["records"] if record["id"] in set(ids)}
    asked = [r for r in by_id.values() if r["status"] == "ran"]
    scored = [r for r in asked if not r["score"].get("error")]
    spent = sum((Decimal(str(r["result"]["usd"])) for r in asked), Decimal(0))
    return {
        "cases": len(ids),
        "asked": len(asked),
        "not_asked": len(ids) - len(asked),
        "errors": len(asked) - len(scored),
        "wrong": sum(1 for r in scored if not r["score"]["correct"]),
        "usd": spent,
        "mean_usd": spent / len(asked) if asked else None,
    }


def _usd(value: Decimal) -> str:
    """Dollars as text, to ten decimals: the same text whatever the arithmetic context."""
    return str(value.quantize(Decimal("0.0000000001")))


def baseline(
    cases_file: dict, picked_from: list[tuple[str, dict]], repeats: list[tuple[str, dict]]
) -> dict:
    """What a run of the check is compared with. See the module's text."""
    ids = ids_of(cases_file)
    per_case = {
        case_id: {
            "right_in": sum(
                1 for _, results in picked_from if _scored(results)[case_id]["score"]["correct"]
            ),
            "runs": len(picked_from),
        }
        for case_id in ids
    }
    costs = [counts(results, ids)["mean_usd"] for _, results in picked_from]
    noise = []
    for name, results in (*picked_from, *repeats):
        made = counts(results, ids)
        if made["not_asked"] or made["errors"]:
            raise CIError(f"{name}: not every case was asked and scored")
        noise.append({"file": name, "variant": results["variant"], "wrong": made["wrong"]})
    worst = max(entry["wrong"] for entry in noise)
    mean_usd = sum(costs, Decimal(0)) / len(costs)
    return {
        "format": FORMAT,
        "cases": per_case,
        "cost": {
            "files": [name for name, _ in picked_from],
            "mean_usd_per_question_per_run": [_usd(c) for c in costs],
            "mean_usd_per_question": _usd(mean_usd),
            "factor": str(COST_FACTOR),
            "max_mean_usd_per_question": _usd(mean_usd * COST_FACTOR),
        },
        "noise": {
            "what": "cases of the check each of these runs got wrong; they sent the same text",
            "runs": noise,
            "worst": worst,
            "margin": MARGIN,
            "max_wrong": worst + MARGIN,
        },
    }


def check(results: dict, cases_file: dict, base: dict) -> tuple[bool, list[str]]:
    """``(passed, lines of a Markdown summary)`` for one run of the cases."""
    ids = ids_of(cases_file)
    made = counts(results, ids)
    max_wrong = base["noise"]["max_wrong"]
    max_usd = Decimal(base["cost"]["max_mean_usd_per_question"])
    finished = results.get("state", "complete") == "complete"
    mean = made["mean_usd"]
    rows = [
        (
            "Every case was asked",
            f"{made['asked']} of {made['cases']}" + ("" if finished else ", run not finished"),
            f"all {made['cases']}",
            made["not_asked"] == 0 and finished,
        ),
        ("No question ended in an error", str(made["errors"]), "0", made["errors"] == 0),
        ("Cases wrong", str(made["wrong"]), f"at most {max_wrong}", made["wrong"] <= max_wrong),
        (
            "Mean USD per question",
            "none asked" if mean is None else f"{mean:.5f}",
            f"at most {max_usd:.5f}",
            mean is not None and mean <= max_usd,
        ),
    ]
    passed = all(row[3] for row in rows)
    lines = [
        "### The regression check: " + ("passed" if passed else "FAILED"),
        "",
        "| What is checked | This run | Allowed | Holds |",
        "|---|---|---|---|",
        *(
            f"| {what} | {got} | {allowed} | {'yes' if ok else '**no**'} |"
            for what, got, allowed, ok in rows
        ),
        "",
        f"The limit on wrong cases is the worst of {len(base['noise']['runs'])} runs that sent "
        f"the model the same text ({base['noise']['worst']}) plus {base['noise']['margin']}. "
        "A run that fails is not run again to make it pass.",
        "",
    ]
    return passed, lines


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as problem:
        raise CIError(f"{path}: cannot be read ({type(problem).__name__})") from None


def _write(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.ci", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    picking = commands.add_parser("select", help="pick the cases from runs already made")
    picking.add_argument("--runs", type=Path, nargs="+", required=True)
    picking.add_argument("--quota", action="append", required=True, metavar="KIND=N")
    picking.add_argument("--seed", type=int, default=DEFAULT_SEED)
    picking.add_argument("--out", type=Path, required=True)
    basing = commands.add_parser("baseline", help="write what a run of the check is compared with")
    basing.add_argument("--cases", type=Path, required=True)
    basing.add_argument("--runs", type=Path, nargs="+", required=True)
    basing.add_argument("--repeats", type=Path, nargs="+", required=True)
    basing.add_argument("--out", type=Path, required=True)
    checking = commands.add_parser("check", help="apply the rule to a run of the cases")
    checking.add_argument("results", type=Path)
    checking.add_argument("--cases", type=Path, required=True)
    checking.add_argument("--baseline", type=Path, required=True)
    checking.add_argument("--summary", type=Path, default=None, help="append the summary here")
    args = parser.parse_args(argv)
    try:
        if args.command == "select":
            quotas = {}
            for given in args.quota:
                kind, _, number = given.partition("=")
                if not kind or not number.isdigit():
                    raise CIError("--quota takes KIND=N")
                quotas[kind] = int(number)
            files = runs.load(args.runs)
            differing = runs.differences(files)
            if differing:
                raise CIError("not runs of the same thing: " + "; ".join(differing))
            picked = select(files, quotas, args.seed)
            _write(args.out, picked)
            print(f"{len(picked['cases'])} cases written to {args.out}")
            return 0
        if args.command == "baseline":
            made = baseline(_load(args.cases), runs.load(args.runs), runs.load(args.repeats))
            _write(args.out, made)
            wrong = ", ".join(str(entry["wrong"]) for entry in made["noise"]["runs"])
            print(f"wrong per run: {wrong}; at most {made['noise']['max_wrong']} allowed")
            return 0
        passed, lines = check(_load(args.results), _load(args.cases), _load(args.baseline))
        text = "\n".join(lines)
        sys.stdout.write(text)
        if args.summary is not None:
            with args.summary.open("a", encoding="utf-8") as fh:
                fh.write(text)
        return 0 if passed else 1
    except (CIError, runs.RunsError, KeyError) as problem:
        print(f"{type(problem).__name__}: {problem}", file=sys.stderr)
        return SETUP_ERROR


if __name__ == "__main__":
    sys.exit(main())
