"""The cases one split got wrong, as a table to classify by hand.

    PYTHONPATH=src uv run python -m evalkit.failures RESULTS RESULTS RESULTS \\
        --out failures.csv --unstable unstable.csv [--split dev]

Reading failures is what a change is designed from, so it is done on one split only, and by
default that split is ``dev``. Nothing about a case of another split is read into the output
or printed: the ``test`` cases stay unseen, which is what keeps their number honest.

Two files are written from several runs of the same variant:

``--out``       one row for every case that was wrong in at least two of the runs: its id,
                kind and family, what happened in each run, an empty ``category`` to fill in
                by hand, and one line of evidence (the final SQL of the first run that was
                wrong, or the reason it gave for refusing).
``--unstable``  the cases that were wrong in exactly one run. They are listed and not
                classified: one failure in three is as likely to be the draw as the agent.

``--refusals``  optional: one row for every case of the split that has no answer, missed or
                not: how each run ended and in how many model calls, in how many runs it was
                not refused, and whether it
                was refused by majority. A case missed in one run of three is the draw; one
                missed in all three is a failure.

A question that ended in an error is not a failure of the agent and is in neither file. The
category is a person's judgement and is not computed here; ``--keep`` carries the categories
and notes already written in an earlier file over to the new one, by case id.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

from evalkit import runs

COLUMNS = ("id", "kind", "family", "what_happened", "category", "note", "evidence")
UNSTABLE_COLUMNS = ("id", "kind", "family", "what_happened", "evidence")
REFUSAL_COLUMNS = ("id", "family", "runs", "not_refused_in", "refused_by_majority", "each_run")
EVIDENCE_CHARS = 600
SETUP_ERROR = 2


def _shown(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return "nothing" if value is None else str(value)


def _one_line(text: object, limit: int = EVIDENCE_CHARS) -> str:
    return " ".join(str(text or "").split())[:limit]


def what_happened(case: dict, record: dict) -> str:
    """One run of one case, in a few words: how it ended and what it submitted."""
    result = record["result"]
    status = result["status"]
    answer = result.get("answer") or {}
    if record["score"]["correct"]:
        return "right"
    if status == "refused":
        return "refused"
    if status == "no_answer":
        return f"no answer ({_one_line(result.get('reason'), 80)})"
    wanted = "a refusal" if case["answer_type"] == "refusal" else _shown(case["expected"])
    said = f"answered {_one_line(_shown(answer.get('value')), 120)}, expected {wanted}"
    return said + (" (ungrounded)" if status == "ungrounded" else "")


def evidence(record: dict) -> str:
    """The final SQL, or for a refusal the reason given; one line."""
    result = record["result"]
    if result["status"] == "refused":
        return "refusal: " + _one_line((result.get("answer") or {}).get("refusal_reason"))
    if result.get("final_sql"):
        return _one_line(result["final_sql"])
    return "no query ran: " + _one_line(result.get("reason"))


def collect(files: list[tuple[str, dict]], split: str) -> tuple[list[dict], list[dict]]:
    """``(failures, unstable)`` of one split: wrong in at least two runs, and in exactly one.

    A run in which the case ended in an error, or was not run, is not counted as wrong and
    not as right: it is left out, and said so in what happened.
    """
    cases = files[0][1]["cases"]
    per_case: dict[str, list[tuple[int, dict]]] = {}
    for number, (_, results) in enumerate(files, start=1):
        for record in runs.of_split(results, split):
            per_case.setdefault(record["id"], []).append((number, record))
    failures, unstable = [], []
    for case_id in sorted(per_case):
        case = cases[case_id]
        scored = [
            (n, r)
            for n, r in per_case[case_id]
            if r["status"] == "ran" and not r["score"].get("error")
        ]
        wrong = [(n, r) for n, r in scored if not r["score"]["correct"]]
        if not wrong:
            continue
        told = [f"run {n}: {what_happened(case, r)}" for n, r in scored]
        left_out = len(files) - len(scored)
        if left_out:
            told.append(f"{left_out} run(s) ended in an error or did not ask it")
        row = {
            "id": case_id,
            "kind": case["kind"],
            "family": case["family"],
            "what_happened": f"wrong in {len(wrong)} of {len(scored)}. " + "; ".join(told),
            "evidence": f"run {wrong[0][0]}: {evidence(wrong[0][1])}",
        }
        if len(wrong) >= 2:
            failures.append({**row, "category": "", "note": ""})
        else:
            unstable.append(row)
    return failures, unstable


def refusals(files: list[tuple[str, dict]], split: str) -> list[dict]:
    """Every case of one split that has no answer, with how each run ended."""
    cases = files[0][1]["cases"]
    per_case: dict[str, list[str]] = {}
    for _, results in files:
        for record in runs.of_split(results, split):
            if cases[record["id"]]["answer_type"] != "refusal":
                continue
            if record["status"] != "ran" or record["score"].get("error"):
                continue
            status, calls = record["result"]["status"], record["result"].get("iterations")
            told = f"{status} in {calls} model calls" if calls else status
            per_case.setdefault(record["id"], []).append(told)
    rows = []
    for case_id in sorted(per_case):
        ended = per_case[case_id]
        refused = [text.split()[0] == "refused" for text in ended]
        rows.append(
            {
                "id": case_id,
                "family": cases[case_id]["family"],
                "runs": len(ended),
                "not_refused_in": len(ended) - sum(refused),
                "refused_by_majority": runs.majority(refused),
                "each_run": "; ".join(f"run {n}: {text}" for n, text in enumerate(ended, 1)),
            }
        )
    return rows


def to_csv(rows: list[dict], columns: tuple[str, ...]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.failures", description=__doc__.split("\n")[0]
    )
    parser.add_argument("results", type=Path, nargs="+", help="results files of one variant")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unstable", type=Path, required=True)
    parser.add_argument("--refusals", type=Path, default=None, help="every case with no answer")
    parser.add_argument("--keep", type=Path, default=None, help="an earlier file with categories")
    args = parser.parse_args(argv)
    try:
        files = runs.load(args.results)
        differing = runs.differences(files)
        if differing:
            raise runs.RunsError("not runs of the same thing: " + "; ".join(differing))
        kept = {row["id"]: row for row in read_csv(args.keep)} if args.keep else {}
    except (runs.RunsError, OSError, KeyError) as problem:
        print(str(problem), file=sys.stderr)
        return SETUP_ERROR
    failures, unstable = collect(files, args.split)
    for row in failures:
        earlier = kept.get(row["id"], {})
        row["category"], row["note"] = earlier.get("category", ""), earlier.get("note", "")
    args.out.write_text(to_csv(failures, COLUMNS), encoding="utf-8")
    args.unstable.write_text(to_csv(unstable, UNSTABLE_COLUMNS), encoding="utf-8")
    if args.refusals is not None:
        due = refusals(files, args.split)
        args.refusals.write_text(to_csv(due, REFUSAL_COLUMNS), encoding="utf-8")
        missed = sum(1 for row in due if not row["refused_by_majority"])
        print(
            f"{args.split}: {len(due)} cases with no answer, {missed} not refused by majority "
            f"({args.refusals})"
        )
    print(
        f"{args.split}: {len(failures)} cases wrong in at least two of {len(files)} runs "
        f"({args.out}), {len(unstable)} wrong in one ({args.unstable})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
