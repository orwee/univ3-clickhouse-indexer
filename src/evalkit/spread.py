"""Identical runs of one variant on one golden file: per case, the spread, and the guards.

    PYTHONPATH=src uv run python -m evalkit.spread RUN1 RUN2 RUN3 [--out report.md] \\
        [--cases-csv per_case.csv]

A guard on a change to the agent has to leave room for the variation between runs of the same
thing, and that variation has to be read from runs, not assumed (the lesson of the caching
runs, which failed a guard set at "the baseline minus one case"). This reads three or more
runs of one variant and prints:

- per case, on every split: right or wrong in each run, and whether the runs agree;
- per run, on ``test``, the counts the guards are made of, and the spread (highest minus
  lowest) of each;
- the guard thresholds those spreads give, with the rule that makes them.

The rule, fixed here so that a report cannot choose it after the fact. On ``test``, by
majority of the runs, ``right`` is the number of cases that have an answer and were answered
right, and ``wrongly refused`` the number that have an answer and were refused. The variant
may lose at most ``max(1, spread of right)`` cases net, and may have at most
``wrongly refused of the baseline + max(1, spread of wrongly refused)``.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

from evalkit import compare, runs
from evalkit.runs import table


def _records(results: dict, split: str) -> list[dict]:
    ran = (r for r in runs.of_split(results, split) if r["status"] == "ran")
    return [r for r in ran if not r["score"].get("error")]


def per_case(files: list[tuple[str, dict]], split: str = "all") -> list[dict]:
    """One row per case: its kind, and per run whether it was right, plus what it was."""
    rows: dict[str, dict] = {}
    for _, results in files:
        cases = results["cases"]
        for record in _records(results, split):
            case = cases[record["id"]]
            row = rows.setdefault(
                record["id"],
                {
                    "id": record["id"],
                    "split": case["split"],
                    "should_refuse": record["score"]["should_refuse"],
                    "right": [],
                    "refused": [],
                },
            )
            row["right"].append(bool(record["score"]["correct"]))
            row["refused"].append(bool(record["score"]["refused"]))
    out = []
    for row in rows.values():
        row["majority_right"] = runs.majority(row["right"])
        row["majority_refused"] = runs.majority(row["refused"])
        row["agree"] = len(set(row["right"])) == 1
        out.append(row)
    return sorted(out, key=lambda r: r["id"])


def _spread(values: list[int]) -> int:
    return max(values) - min(values)


def guards(files: list[tuple[str, dict]], split: str = "test") -> dict:
    """The counts the guards are made of, per run and by majority, and the thresholds."""
    per_run = []
    for name, results in files:
        right = wrong_refusal = 0
        for record in _records(results, split):
            score = record["score"]
            if score["should_refuse"]:
                continue
            right += bool(score["correct"])
            wrong_refusal += bool(score["refused"])
        per_run.append({"file": name, "right": right, "wrongly_refused": wrong_refusal})
    rows = [r for r in per_case(files, split) if not r["should_refuse"]]
    right_majority = sum(1 for r in rows if r["majority_right"])
    refused_majority = sum(1 for r in rows if r["majority_refused"])
    spread_right = _spread([p["right"] for p in per_run])
    spread_refused = _spread([p["wrongly_refused"] for p in per_run])
    lose = max(1, spread_right)
    allowed = refused_majority + max(1, spread_refused)
    return {
        "split": split,
        "answerable": len(rows),
        "per_run": per_run,
        "right_by_majority": right_majority,
        "wrongly_refused_by_majority": refused_majority,
        "spread_right": spread_right,
        "spread_wrongly_refused": spread_refused,
        "may_lose": lose,
        "may_have_wrongly_refused": allowed,
    }


def refusal_recall(files: list[tuple[str, dict]], split: str = "test") -> dict:
    """Per run and by majority, of the cases with no answer: how many were refused."""
    per_run = []
    for name, results in files:
        due = [r for r in _records(results, split) if r["score"]["should_refuse"]]
        per_run.append(
            {
                "file": name,
                "refused": sum(bool(r["score"]["refused"]) for r in due),
                "due": len(due),
            }
        )
    majority = compare.refusals_due(files, split)["by_majority"]
    return {
        "per_run": per_run,
        "spread": _spread([p["refused"] for p in per_run]),
        "by_majority": majority,
    }


def csv_text(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    header = ["id", "split", "has_answer", "runs_right", "runs", "agree"]
    writer.writerow(header + ["majority_right", "majority_refused"])
    for r in rows:
        writer.writerow([
            r["id"], r["split"], json.dumps(not r["should_refuse"]), sum(r["right"]),
            len(r["right"]), json.dumps(r["agree"]), r["majority_right"], r["majority_refused"],
        ])  # fmt: skip
    return out.getvalue()


def render(files: list[tuple[str, dict]]) -> str:
    first = files[0][1]
    lines = [
        f"# {first['variant']} on `{first['golden_file']}`: {len(files)} identical runs",
        "",
        f"Golden file SHA-256 `{first['golden_sha256']}`. Runs: "
        + ", ".join(f"`{name}`" for name, _ in files)
        + ".",
        "",
    ]
    for split in ("test", "dev"):
        rows = per_case(files, split)
        answerable = [r for r in rows if not r["should_refuse"]]
        refusal = [r for r in rows if r["should_refuse"]]
        lines += [f"## `{split}`: cases whose runs disagree", ""]
        lines += table(
            ["Cases", "Count", "Of which the runs do not agree"],
            [
                ["With an answer", len(answerable), sum(not r["agree"] for r in answerable)],
                ["With no answer", len(refusal), sum(not r["agree"] for r in refusal)],
            ],
        )
        lines.append("")
    g = guards(files, "test")
    lines += ["## Guards, from the spread between these runs (`test`, cases with an answer)", ""]
    lines += table(
        ["Run", "Right", "Refused although they have an answer"],
        [[p["file"], p["right"], p["wrongly_refused"]] for p in g["per_run"]],
    )
    lines += [
        "",
        f"- Cases with an answer on `test`: {g['answerable']}.",
        f"- Right by majority of the runs: {g['right_by_majority']}. Spread between runs "
        f"(highest minus lowest): {g['spread_right']}. The variant may lose at most "
        f"max(1, {g['spread_right']}) = {g['may_lose']} cases net.",
        f"- Refused by majority although they have an answer: {g['wrongly_refused_by_majority']}. "
        f"Spread: {g['spread_wrongly_refused']}. The variant may have at most "
        f"{g['wrongly_refused_by_majority']} + max(1, {g['spread_wrongly_refused']}) = "
        f"{g['may_have_wrongly_refused']}.",
        "",
    ]
    r = refusal_recall(files, "test")
    p = r["by_majority"]
    lines += ["## Refusal recall on `test` (the metric of the next entry)", ""]
    lines += table(
        ["Run", "Refused", "Cases with no answer"],
        [[x["file"], x["refused"], x["due"]] for x in r["per_run"]],
    )
    lines += [
        "",
        f"- Spread between runs: {r['spread']} cases.",
        f"- By majority of the runs: {p['k']} of {p['n']} = {runs.pct(p['value'])}, 95% Wilson "
        f"interval [{runs.pct(p['low'])}, {runs.pct(p['high'])}].",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evalkit.spread", description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cases-csv", type=Path)
    args = parser.parse_args(argv)
    try:
        files = runs.load(args.results)
        same = ("variant", "golden_sha256", "model", "system_prompt_sha256")
        problems = runs.differences(files, same)
    except runs.RunsError as problem:
        print(problem, file=sys.stderr)
        return 2
    if problems or len(files) < 2:
        print("\n".join(problems or ["need at least two runs"]), file=sys.stderr)
        return 2
    text = render(files)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.cases_csv:
        args.cases_csv.write_text(csv_text(per_case(files)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
