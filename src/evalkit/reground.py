"""Check the grounding of a results file again, from the transcripts of its run.

    PYTHONPATH=src uv run python -m evalkit.reground RESULTS --transcripts DIR --out FILE \\
        [--causes FILE.csv] [--split dev]

Whether an answer is grounded is decided by the agent's loop while the question is asked,
and written into the results as the status ``answered`` or ``ungrounded``. When that check
changes, the runs already paid for do not have to be paid for again: the transcripts hold
every row the model saw, so the check as it is now can be applied to them. This writes the
same results with the status of every answer decided again and every figure computed
again. Nothing is asked; no model and no database take part. Whether an answer is right
does not change here: only where its value came from.

``DIR`` is the directory of the run's transcripts, one file per question. They are not in
the repository, so the new file can only be made where they are. The new file says so
about itself: ``regrounded`` has one entry per time this was done, with how many answers
were ungrounded before and after. It names no case. The original file is not touched and a
file that is already there is not overwritten.

``--causes`` writes one row for every answer of one split (``dev`` unless said otherwise)
that the results file had as ungrounded, with where its value was found:

``the same number as a cell of the last turn, read as a double``
    the value was sent as a number and lost the digits a double cannot carry;
``a cell of another query of the last turn``
    several queries were sent in one turn and the value was not in the one that came last;
``a cell of an earlier turn``
    the value was read, and another query was run after it. Still ungrounded;
``in no result``
    the value is in nothing the model was shown. Still ungrounded.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime
import io
import json
import sys
from pathlib import Path

from agent import loop
from evalkit import score

QUERY, SUBMIT = "run_sql", "submit_answer"
AS_DOUBLE = "the same number as a cell of the last turn, read as a double"
SAME_TURN = "a cell of another query of the last turn"
EARLIER = "a cell of an earlier turn"
NOWHERE = "in no result"
UNDECIDED = "cannot be decided from the transcript"
COLUMNS = ("id", "kind", "family", "correct", "value", "cause", "still_ungrounded")
SETUP_ERROR = 2


class RegroundError(ValueError):
    """A transcript is missing or is not one."""


def query_results(turns: list[dict]) -> tuple[list[tuple[int, list[list]]], bool]:
    """``(results, complete)``: the rows of every query that ran, with the turn it was sent in.

    ``complete`` is false when a query was sent whose result the transcript does not hold:
    one sent in the same turn as the answer.
    """
    sent: dict[str, tuple[int, str]] = {}
    results: list[tuple[int, list[list]]] = []
    for index, turn in enumerate(turns):
        if not isinstance(turn.get("content"), list):
            continue
        for block in turn["content"]:
            if block.get("type") == "tool_use":
                sent[block["id"]] = (index, block["name"])
            elif block.get("type") == "tool_result":
                index_sent, name = sent.pop(block["tool_use_id"], (index, ""))
                content = block.get("content")
                output = json.loads(content) if isinstance(content, str) else content
                if name == QUERY and isinstance(output, dict) and output.get("ok"):
                    results.append((index_sent, output["rows"]))
    return results, not any(name == QUERY for _, name in sent.values())


def _exact(cell: object, value: object) -> bool:
    """The same cell without the allowance for doubles: the check as it used to be."""
    return loop.same_value(cell, str(value) if isinstance(value, float) else value)


def _found(value: object, rows: list[list], same) -> bool:
    return any(same(cell, value) for row in rows for cell in row)


def cause(value: object, results: list[tuple[int, list[list]]]) -> str:
    """Where one value is, among the results of a question. See the module's text."""
    if not results:
        return NOWHERE
    last_turn = results[-1][0]
    of_turn = [row for turn, rows in results if turn == last_turn for row in rows]
    if _found(value, results[-1][1], _exact):
        return "a cell of the last result"
    if _found(value, of_turn, _exact):
        return SAME_TURN
    if _found(value, of_turn, loop.same_value):
        return AS_DOUBLE
    earlier = [row for turn, rows in results if turn != last_turn for row in rows]
    return EARLIER if _found(value, earlier, loop.same_value) else NOWHERE


def causes(value: object, results: list[tuple[int, list[list]]]) -> str:
    values = value if isinstance(value, list) and value else [value]
    return "; ".join(sorted({cause(item, results) for item in values}))


def grounded(answer: dict, results: list[tuple[int, list[list]]]) -> bool:
    """The check of the loop, applied to what the transcript holds."""
    checked = loop.TurnRows()
    for turn, rows in results:
        checked.add(turn, rows)
    return loop.is_grounded(answer["type"], answer["value"], checked.rows)


def read_transcript(directory: Path, record: dict) -> list[dict]:
    path = directory / f"{record['id']}_{record['repetition']}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))["turns"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        raise RegroundError(f"no usable transcript at {path}") from None


def reground(results: dict, directory: Path, at: str, split: str = "dev") -> tuple[dict, list]:
    """``(the same results with grounding decided again, the rows for --causes)``."""
    new = copy.deepcopy(results)
    cases = new["cases"]
    rows, before, after, undecided = [], 0, 0, 0
    for record in new["records"]:
        if record["status"] != "ran":
            continue
        result = record["result"]
        if result["status"] not in ("answered", "ungrounded"):
            continue
        was = result["status"] == "ungrounded"
        found, complete = query_results(read_transcript(directory, record))
        if complete:
            now = not grounded(result["answer"], found)
            result["status"] = "ungrounded" if now else "answered"
            result["reason"] = "the value is not a cell of the last result" if now else ""
            for call in result.get("tool_calls") or []:
                if call.get("name") == SUBMIT and "grounded" in (call.get("summary") or {}):
                    call["summary"]["grounded"] = not now
            record["score"] = score.score_case(cases[record["id"]], result)
        else:
            now, undecided = was, undecided + 1
        before, after = before + was, after + now
        case = cases[record["id"]]
        if was and split in ("all", case["split"]):
            rows.append(
                {
                    "id": record["id"],
                    "kind": case["kind"],
                    "family": case["family"],
                    "correct": record["score"]["correct"],
                    "value": json.dumps(result["answer"]["value"]),
                    "cause": causes(result["answer"]["value"], found) if complete else UNDECIDED,
                    "still_ungrounded": now,
                }
            )
    new["summary"] = score.summarize(new["records"], cases)
    new["regrounded"] = [
        *results.get("regrounded", []),
        {"at": at, "ungrounded_before": before, "ungrounded_after": after, "undecided": undecided},
    ]
    return new, rows


def to_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.reground", description=__doc__.split("\n")[0]
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--causes", type=Path, default=None)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    args = parser.parse_args(argv)
    for path in (args.out, args.causes):
        if path is not None and path.exists():
            print(f"{path} already exists; nothing was written", file=sys.stderr)
            return SETUP_ERROR
    try:
        results = json.loads(args.results.read_text(encoding="utf-8"))
        at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        new, rows = reground(results, args.transcripts, at, args.split)
    except (OSError, json.JSONDecodeError, KeyError, RegroundError) as problem:
        print(f"{type(problem).__name__}: {problem}", file=sys.stderr)
        return SETUP_ERROR
    args.out.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    step = new["regrounded"][-1]
    print(
        f"ungrounded answers: {step['ungrounded_before']} before, {step['ungrounded_after']} "
        f"after; {step['undecided']} could not be decided from the transcript"
    )
    print(f"results: {args.out}")
    if args.causes is not None:
        args.causes.parent.mkdir(parents=True, exist_ok=True)
        args.causes.write_text(to_csv(rows), encoding="utf-8")
        print(f"causes ({args.split}, {len(rows)} answers): {args.causes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
