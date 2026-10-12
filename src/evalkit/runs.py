"""Several runs of one variant, as one report: every figure per run and over all of them.

    PYTHONPATH=src uv run python -m evalkit.runs RESULTS RESULTS RESULTS [--out report.md]

One run of an evaluation is one draw: the model does not answer the same question the same
way twice. This puts several results files of the same variant side by side. For every
metric it prints each run, their mean, the lowest and the highest, and the spread between
them, three times: over all cases, over ``dev`` and over ``test``. What ended in an error is
in a table of its own and in no figure.

The files must be runs of the same thing: the same variant files, model, golden file,
system prompt, limits and cases. When they are not, nothing is written and the command
says what differs.

Every figure is computed here from the records of the files, with the scorer's own
definitions (``evalkit.score``). No per-case table is printed: the per-case detail is in
the report of each run, and this report can be read without learning which case failed.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from evalkit import score

SAME = ("variant", "variant_files", "model", "golden_sha256", "system_prompt_sha256", "limits")
SPLITS = ("all", "dev", "test")
RESAMPLES = 10_000
SEED = 20261011
DASH = "-"
SETUP_ERROR = 2

METRICS = (
    ("Correct, all cases", lambda f: f["correct"]),
    ("Execution accuracy (cases with an answer)", lambda f: f["execution_accuracy"]),
    ("Refusal recall (cases with no answer that were refused)", lambda f: f["refusals"]["recall"]),
    ("Refusal precision (refusals that were due)", lambda f: f["refusals"]["precision"]),
    ("Hallucination rate", lambda f: f["hallucination_rate"]),
    ("Ungrounded answers", lambda f: f["ungrounded"]),
    ("Valid SQL (queries that ran)", lambda f: f["valid_sql"]),
    ("Questions with a failed query", lambda f: f["questions_with_a_failed_query"]),
)
COSTS = (
    ("Cost per question, USD, mean", lambda f: f["usd"]["mean"], 5),
    ("Cost per question, USD, median", lambda f: f["usd"]["median"], 5),
    ("Cost per question, USD, 95th percentile", lambda f: f["usd"]["p95"], 5),
    ("Tokens per question, mean", lambda f: f["tokens"]["mean"], 0),
    ("Tokens per question, median", lambda f: f["tokens"]["median"], 0),
    ("Tokens per question, 95th percentile", lambda f: f["tokens"]["p95"], 0),
    ("Seconds per question, mean", lambda f: f["seconds"]["mean"], 2),
    ("Seconds per question, median", lambda f: f["seconds"]["median"], 2),
    ("Seconds per question, 95th percentile", lambda f: f["seconds"]["p95"], 2),
)


class RunsError(ValueError):
    """The files are not runs of the same thing, or are not results files."""


def load(paths: list[Path]) -> list[tuple[str, dict]]:
    files = []
    for path in paths:
        try:
            results = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as problem:
            raise RunsError(f"{path}: cannot be read ({type(problem).__name__})") from None
        if not isinstance(results, dict) or "records" not in results or "cases" not in results:
            raise RunsError(f"{path}: not a results file")
        files.append((Path(path).name, results))
    return files


def differences(files: list[tuple[str, dict]], fields: tuple[str, ...] = SAME) -> list[str]:
    """What is not the same in every file, in words. Empty when they are runs of one thing."""
    (first_name, first), found = files[0], []
    for name, results in files[1:]:
        found += [
            f"{field} is not the same in {first_name} and {name}"
            for field in fields
            if results.get(field) != first.get(field)
        ]
        if sorted(results["cases"]) != sorted(first["cases"]):
            found.append(f"the cases are not the same in {first_name} and {name}")
    return found


def of_split(results: dict, split: str) -> list[dict]:
    """The records of one split, or all of them."""
    cases = results["cases"]
    return [r for r in results["records"] if split == "all" or cases[r["id"]]["split"] == split]


def figures(results: dict, split: str) -> dict:
    """The scorer's summary of the records of one split of one file."""
    return score.summarize(of_split(results, split), results["cases"])


def outcomes(files: list[tuple[str, dict]], split: str, with_answer: bool) -> dict[str, list]:
    """Per case, one entry per run that scored it: True for correct, False for wrong.

    ``with_answer`` keeps only the cases that have an answer, which is what execution
    accuracy is over. A run in which the case ended in an error or was not run adds nothing.
    """
    per_case: dict[str, list[bool]] = {}
    for _, results in files:
        for record in of_split(results, split):
            if record["status"] != "ran" or record["score"].get("error"):
                continue
            if with_answer and record["score"]["should_refuse"]:
                continue
            per_case.setdefault(record["id"], []).append(bool(record["score"]["correct"]))
    return per_case


def rate_over_runs(per_case: dict[str, list[bool]]) -> float | None:
    """Correct over scored, all runs together."""
    scored = sum(len(passed) for passed in per_case.values())
    return sum(sum(passed) for passed in per_case.values()) / scored if scored else None


def interval(
    per_case: dict[str, list[bool]], resamples: int = RESAMPLES, seed: int = SEED
) -> tuple[float, float] | None:
    """A 95% interval for ``rate_over_runs``, by a bootstrap that resamples cases, not answers.

    The runs of one case are not independent draws: a case the agent gets wrong it tends to
    get wrong every time. So the unit that is resampled is the case, with all of its runs.
    Percentile method, a fixed seed: the same files give the same interval.
    """
    ids = sorted(per_case)
    if not ids:
        return None
    rng = random.Random(seed)  # noqa: S311 - a reproducible resampling, not security
    counts = [(sum(per_case[i]), len(per_case[i])) for i in ids]
    values = []
    for _ in range(resamples):
        drawn = rng.choices(counts, k=len(counts))
        scored = sum(n for _, n in drawn)
        if scored:
            values.append(sum(k for k, _ in drawn) / scored)
    values.sort()
    if not values:
        return None
    return values[int(0.025 * (len(values) - 1))], values[int(round(0.975 * (len(values) - 1)))]


def majority(passed: list[bool]) -> bool | None:
    """Correct in more than half of the runs that scored the case. None when none did."""
    return sum(passed) * 2 > len(passed) if passed else None


def stability(per_case: dict[str, list[bool]], runs: int) -> dict[str, int]:
    """How many cases were correct in every run, in some, in none; and scored in fewer."""
    full = {i: p for i, p in per_case.items() if len(p) == runs}
    return {
        "in every run": sum(1 for p in full.values() if all(p)),
        "in some runs": sum(1 for p in full.values() if any(p) and not all(p)),
        "in no run": sum(1 for p in full.values() if not any(p)),
        "scored in fewer runs than there were": len(per_case) - len(full),
    }


# --- Markdown --------------------------------------------------------------------------------


def pct(value: float | None) -> str:
    return DASH if value is None else f"{100 * value:.1f}%"


def points(value: float | None) -> str:
    return DASH if value is None else f"{100 * value:.1f} points"


def prop(p: dict) -> str:
    return f"0 of 0 = {DASH}" if not p["n"] else f"{p['k']} of {p['n']} = {pct(p['value'])}"


def num(value: object, digits: int) -> str:
    return DASH if value is None else f"{float(value):,.{digits}f}"


def cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def table(header: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return [*lines, ""]


def _spread(values: list[float | None]) -> tuple[float | None, float | None, float | None]:
    known = [v for v in values if v is not None]
    if not known:
        return None, None, None
    return sum(known) / len(known), min(known), max(known)


def metric_rows(per_run: list[dict]) -> list[list[str]]:
    """One row per metric: each run, then the mean, the lowest, the highest and the spread."""
    rows = []
    for name, pick in METRICS:
        proportions = [pick(f) for f in per_run]
        mean, low, high = _spread([p["value"] for p in proportions])
        gap = None if mean is None else high - low
        rows.append(
            [name, *(prop(p) for p in proportions), pct(mean), pct(low), pct(high), points(gap)]
        )
    return rows  # fmt: skip


def cost_rows(per_run: list[dict]) -> list[list[str]]:
    rows = []
    for name, pick, digits in COSTS:
        values = [pick(f) for f in per_run]
        mean, low, high = _spread(values)
        rows.append(
            [name, *(num(v, digits) for v in values), *(num(v, digits) for v in (mean, low, high))]
        )
    return rows  # fmt: skip


def what_was_run(files: list[tuple[str, dict]]) -> list[str]:
    def row(label, pick):
        return [label, *(pick(results) for _, results in files)]

    rows = [
        ["File", *(name for name, _ in files)],
        row("Run", lambda r: r["run_id"]),
        row("Commit", lambda r: r["commit"]),
        row("State", lambda r: r.get("state", "complete")),
        row("Started", lambda r: r["started"]),
        row("Ended", lambda r: r["ended"] or "not finished"),
        row("Split", lambda r: r["split"]),
        row("Questions asked", lambda r: f"{r['summary']['ran']} of {r['summary']['records']}"),
        row("Not run", lambda r: r["summary"]["not_run"]),
        row("Ended in an error", lambda r: r["summary"]["errors"]["count"]),
        row("Budget, USD", lambda r: r["budget_usd"]),
        row("Spent, USD", lambda r: r["spent_usd"]),
    ]
    first = files[0][1]
    limits = first["limits"]
    same = [
        ["Variant", first["variant"]],
        *([f"Variant file {p}", f"SHA-256 {sha}"] for p, sha in first["variant_files"].items()),
        ["Model", first["model"]],
        ["Golden file", f"{first['golden_file']}, SHA-256 {first['golden_sha256']}"],
        ["System prompt", f"SHA-256 {first['system_prompt_sha256']}"],
        ["Per question", f"${limits['max_usd_per_question']}, {limits['max_iterations']} model "
                         f"calls, {limits['row_cap']} rows"],
        ["Cases", len(first["cases"])],
    ]  # fmt: skip
    header = ["What was run", *(f"run {n}" for n in range(1, len(files) + 1))]
    return table(["The same in every run", ""], same) + table(header, rows)


def errors_apart(files: list[tuple[str, dict]]) -> list[str]:
    header = ["Errors, apart", *(f"run {n}" for n in range(1, len(files) + 1)), "All runs"]
    summaries = [results["summary"] for _, results in files]

    def row(label, pick, digits=None):
        values = [pick(s) for s in summaries]
        total = sum(values)
        shown = (lambda v: num(v, digits)) if digits is not None else str
        return [label, *(shown(v) for v in values), shown(total)]

    lines = table(
        header,
        [
            row("Questions asked", lambda s: s["ran"]),
            row("Ended in an error (in no figure of this report)", lambda s: s["errors"]["count"]),
            row("Scored", lambda s: s["scored"]),
            row("Not run", lambda s: s["not_run"]),
            row("What the errors cost, USD", lambda s: float(s["errors"]["usd"]), 5),
            row("Waits after a 429 or a 529", lambda s: s["waits"]["count"]),
            row("Seconds waited", lambda s: s["waits"]["seconds"], 0),
        ],
    )
    reasons: dict[str, list[int]] = {}
    for n, s in enumerate(summaries):
        for reason, count in s["errors"]["reasons"].items():
            reasons.setdefault(reason, [0] * len(summaries))[n] = count
    if reasons:
        lines += table(
            ["Why a question ended in an error", *header[1:]],
            [[reason, *counts, sum(counts)] for reason, counts in sorted(reasons.items())],
        )
    return lines


def render(files: list[tuple[str, dict]]) -> str:
    runs = len(files)
    names = [f"run {n}" for n in range(1, runs + 1)]
    variant = files[0][1]["variant"]
    lines = [f"# Evaluation over {runs} runs: {cell(variant)}", ""]
    unfinished = [name for name, r in files if r.get("state", "complete") != "complete"]
    partial = [name for name, r in files if r["summary"]["partial"]]
    with_errors = [name for name, r in files if r["summary"]["errors"]["count"]]
    warnings = []
    if unfinished:
        warnings.append([f"UNFINISHED: {', '.join(unfinished)} did not finish."])
    if partial:
        warnings.append([f"PARTIAL: in {', '.join(partial)} some questions were not asked."])
    if with_errors:
        warnings.append(
            [f"ERRORS: in {', '.join(with_errors)} some questions ended in an error. They are "
             "counted in the table of errors and are in no figure below."]
        )  # fmt: skip
    if warnings:
        lines += table(["Read this first"], warnings)
    lines += what_was_run(files)
    lines += errors_apart(files)
    for split in SPLITS:
        title = {"all": "All cases", "dev": "`dev` cases", "test": "`test` cases"}[split]
        per_run = [figures(results, split)["overall"] for _, results in files]
        lines += [f"## {title}", ""]
        lines += table(
            ["Metric", *names, "Mean", "Lowest", "Highest", "Spread between runs"],
            metric_rows(per_run),
        )
        over = []
        for label, with_answer in (
            ("Correct, all cases", False),
            ("Execution accuracy (cases with an answer)", True),
        ):
            per_case = outcomes(files, split, with_answer)
            bounds = interval(per_case)
            scored = sum(len(p) for p in per_case.values())
            over.append(
                [
                    label,
                    f"{sum(sum(p) for p in per_case.values())} of {scored} = "
                    f"{pct(rate_over_runs(per_case))}",
                    DASH if bounds is None else f"[{pct(bounds[0])}, {pct(bounds[1])}]",
                    *stability(per_case, runs).values(),
                ]
            )
        lines += table(
            [
                f"Over the {runs} runs together",
                "Correct of scored",
                "95% interval (bootstrap over cases)",
                "Cases correct in every run",
                "in some runs",
                "in no run",
                "scored in fewer runs",
            ],
            over,
        )
        lines += table(["Per question", *names, "Mean", "Lowest", "Highest"], cost_rows(per_run))
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.runs", description=__doc__.split("\n")[0]
    )
    parser.add_argument("results", type=Path, nargs="+", help="results files of one variant")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        files = load(args.results)
        differing = differences(files)
        if differing:
            raise RunsError("not runs of the same thing: " + "; ".join(differing))
    except RunsError as problem:
        print(str(problem), file=sys.stderr)
        return SETUP_ERROR
    text = render(files)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
