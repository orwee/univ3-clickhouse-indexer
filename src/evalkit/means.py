"""Guards read from per-run means: the baseline's runs against the variant's runs.

``spread.guards`` compares counts by majority of the runs with a margin of whole cases. A
majority throws away what the runs say: a case that three runs split 2 to 1 counts as a full
case, so two sets of runs that differ by nothing a person would call a difference can sit on
either side of a one-case threshold (the ``cache`` runs refused 15, 17 and 16 of 21 against
the baseline's 16, 19 and 17; the coverage default refused 55, 54 and 55 of 60, the same
per run as ``zero-day``). This module compares what each side did per run.

For each measure, on one split, over the cases that measure is about:

- ``right``: cases that have an answer, answered right (higher is better);
- ``refusal_recall``: cases with no answer, refused (higher is better);
- ``wrongly_refused``: cases that have an answer, refused (lower is better).

Each side's count is taken per run, then averaged. The rule, fixed here so that a report
cannot choose it after the fact:

    margin = max(1, spread of the baseline's runs on that measure)

where the spread is the highest count minus the lowest. The guard holds when the variant's
mean is worse than the baseline's mean by at most the margin. Better never fails it.

The margin comes from the baseline's runs alone, so it can be written down before the
variant has run. The variant's spread is reported and is not used. The floor of one case is
the one ``spread.guards`` already uses: three identical runs do not prove that a fourth
would be identical.
"""

from __future__ import annotations

from evalkit import runs, spread

#: measure -> (label, the cases it is over, higher is better)
MEASURES = {
    "right": ("Right, cases with an answer", "answer", True),
    "refusal_recall": ("Refused, cases with no answer", "no_answer", True),
    "wrongly_refused": ("Refused, cases with an answer", "answer", False),
}


def _count(results: dict, split: str, measure: str) -> tuple[int, int]:
    """The count of one run for one measure, and how many cases it is over."""
    _, over, _ = MEASURES[measure]
    due = over == "no_answer"
    kept = [r for r in spread._records(results, split) if r["score"]["should_refuse"] == due]
    key = "refused" if measure != "right" else "correct"
    return sum(bool(r["score"][key]) for r in kept), len(kept)


def _side(files: list[tuple[str, dict]], split: str, measure: str) -> dict:
    counts = [_count(results, split, measure) for _, results in files]
    per_run = [k for k, _ in counts]
    return {
        "files": [name for name, _ in files],
        "per_run": per_run,
        "over": counts[0][1],
        "mean": sum(per_run) / len(per_run),
        "spread": spread._spread(per_run),
    }


def _check(side: list[tuple[str, dict]], role: str) -> None:
    if not side:
        raise runs.RunsError(f"no {role} runs")
    partial = [name for name, results in side if spread.partial_run(results)]
    if partial:
        raise runs.RunsError(f"{role} runs did not ask every case: {', '.join(partial)}")
    problems = runs.differences(side, ("variant", "golden_sha256", "model", "system_prompt_sha256"))
    if problems:
        raise runs.RunsError("; ".join(problems))


def compare(
    baseline: list[tuple[str, dict]], variant: list[tuple[str, dict]], split: str = "test"
) -> dict[str, dict]:
    """Per measure: each side's per-run counts, mean and spread, the margin, and the verdict.

    ``shortfall`` is how far the variant's mean is on the worse side of the baseline's, in
    cases per run; negative when it is better. The rule is in the module docstring.
    """
    _check(baseline, "baseline")
    _check(variant, "variant")
    if baseline[0][1]["golden_sha256"] != variant[0][1]["golden_sha256"]:
        raise runs.RunsError("baseline and variant were run on different golden files")
    out = {}
    for measure, (label, _, higher_is_better) in MEASURES.items():
        base, var = _side(baseline, split, measure), _side(variant, split, measure)
        shortfall = base["mean"] - var["mean"] if higher_is_better else var["mean"] - base["mean"]
        margin = max(1, base["spread"])
        out[measure] = {
            "label": label,
            "split": split,
            "higher_is_better": higher_is_better,
            "baseline": base,
            "variant": var,
            "margin": margin,
            "shortfall": shortfall,
            "holds": shortfall <= margin,
        }
    return out


def render(result: dict[str, dict]) -> str:
    """The comparison as a table, for a pull request or a report."""
    lines = [
        "| Measure | Baseline, per run | Mean | Variant, per run | Mean "
        "| Margin | Shortfall | Holds |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in result.values():
        b, v = row["baseline"], row["variant"]
        lines.append(
            f"| {row['label']} (of {b['over']}) | {', '.join(map(str, b['per_run']))} "
            f"| {b['mean']:.2f} | {', '.join(map(str, v['per_run']))} | {v['mean']:.2f} "
            f"| {row['margin']} | {row['shortfall']:+.2f} | {'yes' if row['holds'] else '**no**'} |"
        )
    return "\n".join(lines)
