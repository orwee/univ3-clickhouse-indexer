"""Two variants, each run several times: what the change did, and whether it is noise.

    PYTHONPATH=src uv run python -m evalkit.compare --baseline B1 B2 B3 --variant V1 V2 V3 \\
        [--failures CSV] [--out report.md]

The number that is reported is execution accuracy on ``test``: the cases the change was not
designed on. For each variant it prints every run, the mean, the lowest and the highest,
and a 95% interval; then the difference with an interval of its own, and case by case, by
majority of the runs, how many cases the change fixed, how many it broke and how many
stayed as they were. The cases with no answer have a table of their own: how many each
variant refused by majority of its runs, with a Wilson interval, and how the answers that
were not refusals ended. Refusals, hallucination rate, valid SQL, dollars and seconds are
printed for both. ``dev`` is in a table of its own, and is labelled for what it is: the
cases the change was designed on.

One sentence then says, in plain words, whether the difference is larger than the spread
between runs of the same variant. When it is not, the sentence says that it is not.

The two variants must have been run on the same golden file and the same cases, or nothing
is written. What else differs between them (the variant files, the system prompt, the
model, the limits) is printed, so that "one change" can be read off the report.

No case is named. ``--failures`` is a CSV with a ``category`` column, the classified
failures of the variant on ``dev``; its counts are printed as they are.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from evalkit import runs, score
from evalkit.runs import DASH, pct, points, table

BETWEEN = ("variant_files", "model", "system_prompt_sha256", "limits")
MUST_MATCH = ("golden_sha256",)
SETUP_ERROR = 2

BOTH = (
    ("Correct, all cases", lambda f: f["correct"]["value"], pct),
    ("Execution accuracy (cases with an answer)", lambda f: f["execution_accuracy"]["value"], pct),
    ("Refusal recall", lambda f: f["refusals"]["recall"]["value"], pct),
    ("Refusal precision", lambda f: f["refusals"]["precision"]["value"], pct),
    ("Refusals made", lambda f: _refusals_made(f["refusals"]), None),
    ("Hallucination rate", lambda f: f["hallucination_rate"]["value"], pct),
    ("Valid SQL (queries that ran)", lambda f: f["valid_sql"]["value"], pct),
    ("Dollars per question, mean", lambda f: f["usd"]["mean"], lambda v: runs.num(v, 5)),
    ("Seconds per question, mean", lambda f: f["seconds"]["mean"], lambda v: runs.num(v, 2)),
)  # fmt: skip


def _refusals_made(refusals: dict) -> int:
    return refusals["should_and_did"] + refusals["should_not_and_did"]


def difference_interval(
    before: dict[str, list[bool]],
    after: dict[str, list[bool]],
    resamples: int = runs.RESAMPLES,
    seed: int = runs.SEED,
) -> tuple[float, float] | None:
    """A 95% interval for ``after - before``, resampling the cases both were scored on.

    Paired: one draw of cases is used for both variants, so a case that is hard for both
    moves both rates together and not their difference.
    """
    ids = sorted(set(before) & set(after))
    if not ids:
        return None
    counts = [(sum(before[i]), len(before[i]), sum(after[i]), len(after[i])) for i in ids]
    rng = random.Random(seed)  # noqa: S311 - a reproducible resampling, not security
    values = []
    for _ in range(resamples):
        drawn = rng.choices(counts, k=len(counts))
        scored_before, scored_after = sum(d[1] for d in drawn), sum(d[3] for d in drawn)
        if scored_before and scored_after:
            values.append(
                sum(d[2] for d in drawn) / scored_after - sum(d[0] for d in drawn) / scored_before
            )
    if not values:
        return None
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(round(0.975 * (len(values) - 1)))]


def moves(before: dict[str, list[bool]], after: dict[str, list[bool]]) -> dict[str, int]:
    """Case by case, by majority of the runs: fixed, broke, stayed right, stayed wrong."""
    out = {"fixed": 0, "broke": 0, "stayed right": 0, "stayed wrong": 0, "not comparable": 0}
    for case_id in sorted(set(before) | set(after)):
        was, now = runs.majority(before.get(case_id, [])), runs.majority(after.get(case_id, []))
        if was is None or now is None:
            out["not comparable"] += 1
        elif was and now:
            out["stayed right"] += 1
        elif not was and not now:
            out["stayed wrong"] += 1
        elif now:
            out["fixed"] += 1
        else:
            out["broke"] += 1
    return out


def refusals_due(files: list[tuple[str, dict]], split: str) -> dict:
    """The cases of one split that have no answer: per case, whether each run refused it,
    and over all runs how the answers that were not refusals ended."""
    per_case: dict[str, list[bool]] = {}
    ended = {"no_answer": 0, "gave a value": 0, "answers": 0}
    for _, results in files:
        for record in runs.of_split(results, split):
            if record["status"] != "ran" or record["score"].get("error"):
                continue
            if not record["score"]["should_refuse"]:
                continue
            per_case.setdefault(record["id"], []).append(bool(record["score"]["refused"]))
            ended["answers"] += 1
            ended["no_answer"] += record["result"]["status"] == "no_answer"
            ended["gave a value"] += bool(record["score"]["gave_value"])
    by_majority = [runs.majority(refused) for refused in per_case.values()]
    return {
        "per_case": per_case,
        "by_majority": score.proportion(sum(1 for m in by_majority if m), len(by_majority)),
        "ended": ended,
    }


def refusals_table(before: dict, after: dict, names: tuple[str, str], split: str) -> list[str]:
    def by_majority(due: dict) -> str:
        p = due["by_majority"]
        if not p["n"]:
            return DASH
        return f"{runs.prop(p)} [{pct(p['low'])}, {pct(p['high'])}]"

    def over(due: dict, what: str) -> str:
        return f"{due['ended'][what]} of {due['ended']['answers']}"

    return table(
        [f"Cases with no answer on `{split}`", names[0], names[1]],
        [
            ["Refused, by majority of the runs, with its 95% Wilson interval",
             by_majority(before), by_majority(after)],
            ["Ended without an answer (the cap, or the model stopped), all runs",
             over(before, "no_answer"), over(after, "no_answer")],
            ["Gave a value where a refusal was due, all runs",
             over(before, "gave a value"), over(after, "gave a value")],
        ],
    )  # fmt: skip


def accuracy(files: list[tuple[str, dict]], split: str) -> dict:
    """Execution accuracy of one variant on one split: per run, and over the runs."""
    per_run = [
        runs.figures(results, split)["overall"]["execution_accuracy"] for _, results in files
    ]
    mean, low, high = runs._spread([p["value"] for p in per_run])
    per_case = runs.outcomes(files, split, with_answer=True)
    return {
        "per_run": per_run,
        "mean": mean,
        "lowest": low,
        "highest": high,
        "spread": None if mean is None else high - low,
        "interval": runs.interval(per_case),
        "per_case": per_case,
    }


def verdict(before: dict, after: dict) -> str:
    """One sentence: is the difference on ``test`` larger than the spread between runs?"""
    if before["mean"] is None or after["mean"] is None:
        return "There is nothing to compare on `test`: one of the two has no scored case there."
    change = after["mean"] - before["mean"]
    noise = max(before["spread"], after["spread"])
    start = (
        f"On `test`, execution accuracy went from {pct(before['mean'])} to {pct(after['mean'])}, "
        f"a difference of {100 * change:+.1f} points; the runs of one variant differ among "
        f"themselves by up to {points(noise)}"
    )
    if abs(change) > noise:
        return start + ", so the difference is larger than the spread between runs."
    return (
        start + ", so the difference is not larger than the spread between runs: these runs "
        "do not show that the change did anything."
    )


def _range(mean, low, high, show) -> str:
    if mean is None:
        return DASH
    return f"{show(mean)} ({show(low)} to {show(high)})"


def both_rows(before: list[tuple[str, dict]], after: list[tuple[str, dict]], split: str) -> list:
    rows = []
    for name, pick, show in BOTH:
        cells = []
        for files in (before, after):
            values = [pick(runs.figures(results, split)["overall"]) for _, results in files]
            if show is None:
                cells.append(" / ".join(str(v) for v in values))
            else:
                cells.append(_range(*runs._spread(values), show))
        rows.append([name, *cells])
    return rows


def accuracy_table(before: dict, after: dict, names: tuple[str, str], count: int) -> list[str]:
    header = ["Execution accuracy", *(f"run {n}" for n in range(1, count + 1))]
    header += ["Mean", "Lowest", "Highest", "95% interval (bootstrap over cases)"]
    rows = []
    for name, a in zip(names, (before, after), strict=True):
        per_run = [runs.prop(p) for p in a["per_run"]]
        per_run += [DASH] * (count - len(per_run))
        bounds = a["interval"]
        rows.append(
            [
                name,
                *per_run,
                pct(a["mean"]),
                pct(a["lowest"]),
                pct(a["highest"]),
                DASH if bounds is None else f"[{pct(bounds[0])}, {pct(bounds[1])}]",
            ]
        )
    return table(header, rows)


def render(
    before: list[tuple[str, dict]],
    after: list[tuple[str, dict]],
    failures: list[dict] | None = None,
) -> str:
    one, two = before[0][1], after[0][1]
    names = (one["variant"], two["variant"])
    count = max(len(before), len(after))
    lines = [f"# {runs.cell(names[0])} against {runs.cell(names[1])}", ""]
    with_errors = [n for n, r in (*before, *after) if r["summary"]["errors"]["count"]]
    unfinished = [n for n, r in (*before, *after) if r.get("state", "complete") != "complete"]
    partial = [n for n, r in (*before, *after) if r["summary"]["partial"]]
    warnings = []
    if unfinished:
        warnings.append([f"UNFINISHED: {', '.join(unfinished)} did not finish."])
    if partial:
        warnings.append([f"PARTIAL: in {', '.join(partial)} some questions were not asked."])
    if with_errors:
        warnings.append(
            [f"ERRORS: in {', '.join(with_errors)} some questions ended in an error. They are "
             "in no figure below."]
        )  # fmt: skip
    if warnings:
        lines += table(["Read this first"], warnings)

    lines += table(
        ["What is compared", names[0], names[1]],
        [
            ["Files", ", ".join(n for n, _ in before), ", ".join(n for n, _ in after)],
            ["Runs", len(before), len(after)],
            ["Commit", ", ".join(sorted({r["commit"] for _, r in before})),
             ", ".join(sorted({r["commit"] for _, r in after}))],
            ["Model", one["model"], two["model"]],
            ["System prompt, SHA-256", one["system_prompt_sha256"], two["system_prompt_sha256"]],
            ["Variant files", "; ".join(f"{p} {s}" for p, s in one["variant_files"].items()),
             "; ".join(f"{p} {s}" for p, s in two["variant_files"].items())],
            ["Per question", str(one["limits"]), str(two["limits"])],
        ],
    )  # fmt: skip
    differing = [f for f in BETWEEN if one.get(f) != two.get(f)]
    lines += table(
        ["The same in both", ""],
        [
            ["Golden file", f"{one['golden_file']}, SHA-256 {one['golden_sha256']}"],
            ["Cases", len(one["cases"])],
            ["What differs between the two", ", ".join(differing) or "nothing"],
        ],
    )

    test_before, test_after = accuracy(before, "test"), accuracy(after, "test")
    lines += ["## On `test`: the cases the change was not designed on", ""]
    lines += accuracy_table(test_before, test_after, names, count)
    change = None
    if test_before["mean"] is not None and test_after["mean"] is not None:
        change = test_after["mean"] - test_before["mean"]
    bounds = difference_interval(test_before["per_case"], test_after["per_case"])
    between = DASH
    if bounds is not None:
        between = f"[{100 * bounds[0]:+.1f}, {100 * bounds[1]:+.1f}] points"
    lines += table(
        ["The difference in execution accuracy on `test`", ""],
        [
            [f"{names[1]} minus {names[0]}, means of the runs",
             DASH if change is None else f"{100 * change:+.1f} points"],
            ["95% interval of the difference (paired bootstrap over cases)", between],
            [f"Spread between the runs of {names[0]}", points(test_before["spread"])],
            [f"Spread between the runs of {names[1]}", points(test_after["spread"])],
        ],
    )  # fmt: skip
    lines += [verdict(test_before, test_after), ""]

    header = ["Case by case on `test`, by majority of the runs", "Fixed", "Broke"]
    header += ["Stayed right", "Stayed wrong", "Not comparable"]
    rows = []
    for label, with_answer in (("Cases with an answer", True), ("All cases", False)):
        moved = moves(
            runs.outcomes(before, "test", with_answer), runs.outcomes(after, "test", with_answer)
        )
        rows.append([label, *moved.values()])
    due_before, due_after = refusals_due(before, "test"), refusals_due(after, "test")
    rows.append(
        ["Cases with no answer", *moves(due_before["per_case"], due_after["per_case"]).values()]
    )
    lines += table(header, rows)
    lines += refusals_table(due_before, due_after, names, "test")
    both = ["mean of the runs (lowest to highest)", names[0], names[1]]
    lines += table(["On `test`, " + both[0], *both[1:]], both_rows(before, after, "test"))

    dev_before, dev_after = accuracy(before, "dev"), accuracy(after, "dev")
    lines += [
        "## On `dev`: the cases the change was designed on",
        "",
        "These are the cases that were looked at to choose the change. A gain here is expected "
        "and is not evidence that the change works.",
        "",
    ]
    lines += accuracy_table(dev_before, dev_after, names, count)
    lines += table(["On `dev`, " + both[0], *both[1:]], both_rows(before, after, "dev"))
    lines += refusals_table(refusals_due(before, "dev"), refusals_due(after, "dev"), names, "dev")

    lines += ["## The largest failure category left on `dev`", ""]
    if failures is None:
        lines += ["Not classified: no failures file was given.", ""]
    else:
        counted: dict[str, int] = {}
        for row in failures:
            counted[row["category"]] = counted.get(row["category"], 0) + 1
        ordered = sorted(counted.items(), key=lambda item: (-item[1], item[0]))
        lines += table([f"Category, {names[1]} on `dev`", "Cases"], [list(i) for i in ordered])
        if ordered:
            top = [name for name, n in ordered if n == ordered[0][1]]
            lines += [f"Largest: {' and '.join(top)}, with {ordered[0][1]} cases.", ""]
        else:
            lines += ["No case is left in the file.", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.compare", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--baseline", type=Path, nargs="+", required=True)
    parser.add_argument("--variant", type=Path, nargs="+", required=True)
    parser.add_argument("--failures", type=Path, default=None, help="a CSV with a category column")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        before, after = runs.load(args.baseline), runs.load(args.variant)
        problems = runs.differences(before) + runs.differences(after)
        problems += runs.differences([before[0], after[0]], MUST_MATCH)
        if problems:
            raise runs.RunsError("cannot be compared: " + "; ".join(problems))
        failures = None
        if args.failures is not None:
            with args.failures.open(newline="", encoding="utf-8") as fh:
                failures = list(csv.DictReader(fh))
            if failures and "category" not in failures[0]:
                raise runs.RunsError(f"{args.failures}: no category column")
    except (runs.RunsError, OSError) as problem:
        print(str(problem), file=sys.stderr)
        return SETUP_ERROR
    text = render(before, after, failures)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
