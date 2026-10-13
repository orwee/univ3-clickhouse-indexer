"""What the runs cost, side by side, and two routers simulated from results already paid for.

    PYTHONPATH=src uv run python -m evalkit.cost \\
        --row baseline B1.json B2.json B3.json --row other O1.json ... \\
        [--cheap B1.json B2.json B3.json --strong S.json] [--out report.md]

Each ``--row`` is a label and the results files of its runs. For every split a row has runs
on, the report gives the mean cost of a question, the cost of a correct answer (everything
spent over everything answered right), the mean seconds of a question and how many answers
were right. A question that ended in an error is in no figure.

With ``--cheap`` and ``--strong`` it also simulates two ways of sending each question to
one of two variants, on the cases both were asked. Nothing is run: the answers and the
costs are the ones in the files.

``oracle``
    For each case the cheaper variant if it was right, or else the other one if that one
    was right, or else the cheaper one. It knows beforehand who will be right, which no
    real router does: it is the bound, not a design.
``cascade``
    The cheap variant first. Only when it ended without an answer or its answer was not
    grounded is the strong one asked too, and then both are paid for. It uses nothing a
    real router would not have.

One simulation is made for each run of the cheap variant against the one run of the strong
one. No case is named.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from evalkit import runs
from evalkit.runs import DASH, table

SETUP_ERROR = 2
ESCALATE = ("no_answer", "ungrounded")


def _scored(results: dict, split: str) -> list[dict]:
    return [
        record
        for record in runs.of_split(results, split)
        if record["status"] == "ran" and not record["score"].get("error")
    ]


def figures(results: dict, split: str) -> dict | None:
    """Dollars, seconds and right answers of one run on one split. None when it has none."""
    if results.get("split", "all") not in ("all", split):
        return None  # a run of one split is not a run of all cases, nor of the other split
    scored = _scored(results, split)
    if not scored:
        return None
    return {
        "questions": len(scored),
        "usd": sum(Decimal(str(record["result"]["usd"])) for record in scored),
        "seconds": sum(float(record["result"]["seconds"]) for record in scored),
        "correct": sum(1 for record in scored if record["score"]["correct"]),
    }


def usd(value: Decimal | None, digits: int = 5) -> str:
    return DASH if value is None else f"{value:.{digits}f}"


def _ends(values: list[Decimal], digits: int = 5) -> str:
    mean = sum(values) / len(values)
    if len(values) == 1:
        return usd(mean, digits)
    return f"{usd(mean, digits)} ({usd(min(values), digits)} to {usd(max(values), digits)})"


def row_of(label: str, files: list[tuple[str, dict]], split: str) -> list[str] | None:
    per_run = [made for _, results in files if (made := figures(results, split))]
    if not per_run:
        return None
    spent, right = sum(f["usd"] for f in per_run), sum(f["correct"] for f in per_run)
    asked = sum(f["questions"] for f in per_run)
    seconds = sum(f["seconds"] for f in per_run) / asked
    return [
        label,
        len(per_run),
        per_run[0]["questions"],
        _ends([f["usd"] / f["questions"] for f in per_run]),
        usd(spent / right) if right else DASH,
        f"{seconds:.2f}",
        f"{right} of {asked} = {100 * right / asked:.1f}%",
    ]


def simulate(cheap: dict, strong: dict, split: str) -> dict:
    """Both variants alone and the two routers, on the cases of ``split`` both scored."""
    first = {record["id"]: record for record in _scored(cheap, split)}
    second = {record["id"]: record for record in _scored(strong, split)}
    out = {
        name: {"usd": Decimal(0), "correct": 0, "to_strong": 0}
        for name in ("cheap alone", "strong alone", "oracle", "cascade")
    }
    shared = sorted(set(first) & set(second))
    for case_id in shared:
        a, b = first[case_id], second[case_id]
        cost_a, cost_b = Decimal(str(a["result"]["usd"])), Decimal(str(b["result"]["usd"]))
        right_a, right_b = bool(a["score"]["correct"]), bool(b["score"]["correct"])
        out["cheap alone"]["usd"] += cost_a
        out["cheap alone"]["correct"] += right_a
        out["strong alone"]["usd"] += cost_b
        out["strong alone"]["correct"] += right_b
        out["strong alone"]["to_strong"] += 1
        lower, lower_right = (cost_a, right_a) if cost_a <= cost_b else (cost_b, right_b)
        if right_a and right_b:
            picked, strong_picked = lower, cost_b < cost_a
        elif right_a or right_b:
            picked, strong_picked = (cost_a, False) if right_a else (cost_b, True)
        else:
            picked, strong_picked = lower, cost_b < cost_a
        out["oracle"]["usd"] += picked
        out["oracle"]["correct"] += right_a or right_b
        out["oracle"]["to_strong"] += strong_picked
        if a["result"]["status"] in ESCALATE:
            out["cascade"]["usd"] += cost_a + cost_b
            out["cascade"]["correct"] += right_b
            out["cascade"]["to_strong"] += 1
        else:
            out["cascade"]["usd"] += cost_a
            out["cascade"]["correct"] += right_a
    for made in out.values():
        made["cases"] = len(shared)
    return out


def render(
    rows: list[tuple[str, list[tuple[str, dict]]]],
    cheap: list[tuple[str, dict]] | None = None,
    strong: tuple[str, dict] | None = None,
    split: str = "dev",
) -> str:
    lines = ["# What the runs cost", ""]
    lines += table(
        ["Row", "Model", "Files"],
        [
            [
                label,
                ", ".join(sorted({r["model"] for _, r in files})),
                ", ".join(n for n, _ in files),
            ]
            for label, files in rows
        ],
    )
    header = ["Row", "Runs", "Questions per run", "USD per question, mean of the runs (range)"]
    header += ["USD per correct answer", "Seconds per question", "Right, all runs"]
    for name in runs.SPLITS:
        made = [row for label, files in rows if (row := row_of(label, files, name))]
        if made:
            title = "All cases" if name == "all" else f"`{name}` cases"
            lines += [f"## {title}", ""] + table(header, made)
    if cheap and strong:
        lines += [
            f"## Two routers, simulated on `{split}`",
            "",
            "Nothing here was run. Each line takes the answers and the costs already in the "
            f"files: one run of the cheap variant against the one run of the strong one "
            f"(`{strong[0]}`). The oracle knows beforehand which variant will be right, which "
            "no real router does. The cascade asks the strong variant only when the cheap one "
            "ended without an answer or with an answer that was not grounded, and then pays "
            "for both.",
            "",
        ]
        header = ["Cheap run", "Policy", "Cases", "Right", "USD, all cases", "USD per question"]
        header += ["USD per correct answer", "Sent to the strong variant"]
        body = []
        for name, results in cheap:
            for policy, made in simulate(results, strong[1], split).items():
                cases = made["cases"]
                body.append(
                    [
                        name,
                        policy,
                        cases,
                        f"{made['correct']} of {cases}",
                        usd(made["usd"], 4),
                        usd(made["usd"] / cases) if cases else DASH,
                        usd(made["usd"] / made["correct"]) if made["correct"] else DASH,
                        made["to_strong"],
                    ]
                )
        lines += table(header, body)
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.cost", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--row", nargs="+", action="append", required=True, metavar="LABEL FILE")
    parser.add_argument("--cheap", type=Path, nargs="+", default=None)
    parser.add_argument("--strong", type=Path, default=None)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if any(len(given) < 2 for given in args.row):
            raise runs.RunsError("--row takes a label and at least one results file")
        if (args.cheap is None) != (args.strong is None):
            raise runs.RunsError("--cheap and --strong go together")
        rows = []
        for label, *paths in args.row:
            files = runs.load([Path(p) for p in paths])
            differing = runs.differences(files)
            if differing:
                raise runs.RunsError(f"{label}: not runs of the same thing: {'; '.join(differing)}")
            rows.append((label, files))
        cheap = runs.load(args.cheap) if args.cheap else None
        strong = runs.load([args.strong])[0] if args.strong else None
    except (runs.RunsError, OSError) as problem:
        print(str(problem), file=sys.stderr)
        return SETUP_ERROR
    text = render(rows, cheap, strong, args.split)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
