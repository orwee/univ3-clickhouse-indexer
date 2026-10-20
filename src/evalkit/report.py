"""A results file as Markdown: tables only, and nothing that is not in the file.

    PYTHONPATH=src uv run python -m evalkit.report results.json [--out report.md] [--top]

Every figure printed here is read from the file ``python -m evalkit.run`` wrote. Nothing
is recomputed from elsewhere, compared with another run or commented on. A proportion is
shown with the two counts it is made of and its 95% Wilson interval. ``--top`` prints only
the first tables, for a job summary.

A run that did not finish, a run that stopped on its budget and a run in which questions
ended in an error each say so in a table of their own, before anything else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DASH = "—"


def _pct(value: float | None) -> str:
    return DASH if value is None else f"{100 * value:.1f}%"


def _prop(p: dict) -> str:
    """`12 of 20 = 60.0% [38.7%, 78.1%]`."""
    if not p["n"]:
        return f"0 of 0 = {DASH}"
    return f"{p['k']} of {p['n']} = {_pct(p['value'])} [{_pct(p['low'])}, {_pct(p['high'])}]"


def _num(value: object, digits: int = 4) -> str:
    if value is None:
        return DASH
    return f"{float(value):,.{digits}f}"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return [*lines, ""]


def _what_was_run(r: dict) -> list[str]:
    fingerprint = r["fixture_fingerprint"]
    s = r["summary"]
    files = [[f"Variant file {path}", f"SHA-256 {sha}"] for path, sha in r["variant_files"].items()]
    rescored = [
        ["Rescored", f"at {step['at']}, from golden SHA-256 {step['from_golden_sha256']} to "
                     f"{step['to_golden_sha256']}; {len(step['changed'])} scores changed"]
        for step in r.get("rescored", [])
    ]  # fmt: skip
    reruns = [
        ["Errors asked again", f"{len(step['asked_again'])} in run {step['run_id']} at commit "
                               f"{step['commit']}, for ${step['spent_usd']}; "
                               f"{len(step['not_asked_again'])} not asked again"]
        for step in r.get("reruns", [])
    ]  # fmt: skip
    provider = []
    if r.get("provider", "anthropic") != "anthropic" or r.get("billed_usd"):
        billed = r.get("billed_usd")
        provider = [
            ["Provider", r.get("provider", "anthropic")],
            ["Model the responses named", ", ".join(r.get("served_models") or []) or "not said"],
            ["Billed by the provider", "not reported" if billed is None else
             f"${billed} over {r.get('billed_questions', 0)} questions"],
        ]  # fmt: skip
    rows = [
        ["Variant", r["variant"]],
        *files,
        ["Model", r["model"]],
        ["Commit", r["commit"]],
        ["Started", r["started"]],
        ["Ended", r["ended"] or f"not finished; file last written {r['written']}"],
        ["Golden file", f"{r['golden_file']}, SHA-256 {r['golden_sha256']}"],
        *rescored,
        ["System prompt", f"SHA-256 {r['system_prompt_sha256']}"],
        ["Fixture", f"exported {fingerprint.get('exported_on')}, marts built from "
                    f"{fingerprint.get('built_from_commit')}"],
        ["Split", r["split"]],
        ["Cases selected", r["cases_selected"]],
        ["Repetitions", r["repetitions"]],
        ["Questions asked", f"{s['ran']} of {s['records']}"],
        ["Not run", s["not_run"]],
        ["Ended in an error, in no figure below", s["errors"]["count"]],
        ["Scored", s["scored"]],
        ["Waits after a 429 or a 529", f"{s['waits']['count']} in {s['waits']['questions']} "
                                       f"questions, {s['waits']['seconds']:.0f} s in all"],
        *reruns,
        ["Budget", f"${r['budget_usd']}"],
        ["Spent", f"${r['spent_usd']}" + (" by the price table" if r.get("billed_usd") else "")],
        *provider,
        ["Per question", f"${r['limits']['max_usd_per_question']}, {r['limits']['max_iterations']} "
                         f"model calls, {r['limits']['row_cap']} rows"],
    ]  # fmt: skip
    return _table(["What was run", ""], rows)


def _warnings(r: dict) -> list[str]:
    """What a reader has to know before any figure: unfinished, partial, errors."""
    s = r["summary"]
    lines = []
    if r["state"] != "complete":
        reached = s["records"] - len(r["not_reached"])
        lines += _table(
            ["UNFINISHED RUN"],
            [[f"This file was written while the run was going, after {reached} of "
              f"{s['records']} questions, and the run never wrote a later one. "
              f"{len(r['not_reached'])} questions were not reached; they are the ones marked "
              "not run below."]],
        )  # fmt: skip
    elif s["partial"]:
        lines += _table(
            ["PARTIAL RUN"],
            [[f"{s['not_run']} of {s['records']} questions were not asked. Every "
              "figure below is over the ones that were."]],
        )  # fmt: skip
    errors = s["errors"]
    if errors["count"]:
        lines += _table(
            ["RUN WITH ERRORS"],
            [[f"{errors['count']} of {s['ran']} questions asked ended in an error (the API, the "
              f"network or the budget), not in an answer. They are counted here and in no "
              f"figure below: every accuracy is over the other {s['scored']}. They cost "
              f"${errors['usd']}."]],
        )  # fmt: skip
        lines += _table(
            ["Why a question ended in an error", "Questions"],
            [[reason, count] for reason, count in errors["reasons"].items()],
        )
    return lines


def _headline(figures: dict) -> list[str]:
    refusals = figures["refusals"]
    return _table(
        ["Metric", "Value, with its 95% Wilson interval"],
        [
            ["Correct, all cases", _prop(figures["correct"])],
            ["Execution accuracy (cases with an answer)", _prop(figures["execution_accuracy"])],
            ["Refusal recall (cases with no answer that were refused)", _prop(refusals["recall"])],
            ["Refusal precision (refusals that were due)", _prop(refusals["precision"])],
            ["Hallucination rate", _prop(figures["hallucination_rate"])],
            ["Ungrounded answers", _prop(figures["ungrounded"])],
            ["Valid SQL (queries that ran)", _prop(figures["valid_sql"])],
            ["Questions with a failed query", _prop(figures["questions_with_a_failed_query"])],
        ],
    )


def _refusals(figures: dict) -> list[str]:
    t = figures["refusals"]
    return _table(
        ["Refusals", "Refused", "Did not refuse"],
        [
            ["Should refuse", t["should_and_did"], t["should_and_did_not"]],
            ["Should not refuse", t["should_not_and_did"], t["should_not_and_did_not"]],
        ],
    )


def _costs(figures: dict) -> list[str]:
    usd, tokens, seconds = figures["usd"], figures["tokens"], figures["seconds"]
    return _table(
        ["Per question", "Mean", "Median", "95th percentile"],
        [
            ["Cost, USD", _num(usd["mean"], 5), _num(usd["median"], 5), _num(usd["p95"], 5)],
            ["Tokens", _num(tokens["mean"], 0), _num(tokens["median"], 0), _num(tokens["p95"], 0)],
            ["Seconds", *(_num(seconds[k], 2) for k in ("mean", "median", "p95"))],
        ],
    ) + _table(
        ["Cost", "USD"],
        [
            ["Total", _num(usd["total"], 5)],
            ["Per correct answer", _num(usd["per_correct_answer"], 5)],
        ],
    )  # fmt: skip


def _breakdown(title: str, groups: dict) -> list[str]:
    rows = [
        [
            name,
            _prop(f["correct"]),
            _prop(f["hallucination_rate"]),
            _prop(f["valid_sql"]),
            _num(f["usd"]["mean"], 5),
            _num(f["seconds"]["mean"], 2),
        ]
        for name, f in groups.items()
    ]
    header = [title, "Correct", "Hallucination rate", "Valid SQL", "Mean USD", "Mean seconds"]
    return _table(header, rows)


def _repetitions(rep: dict) -> list[str]:
    spread = rep["spread"]
    lines = _table(
        ["Repetitions", ""],
        [
            ["Runs of each case", rep["count"]],
            ["Cases that passed every run", rep["always_passed"]],
            ["Cases that passed some runs", rep["sometimes_passed"]],
            ["Cases that passed no run", rep["never_passed"]],
            ["Correct, lowest run", _pct(spread["lowest"])],
            ["Correct, highest run", _pct(spread["highest"])],
            ["Spread between runs", _pct(spread["range"])],
        ],
    )
    lines += _table(
        ["Run", "Correct"],
        [[n + 1, _prop(p)] for n, p in enumerate(rep["correct_per_run"])],
    )
    unstable = [
        [case_id, f"{v['passed']} of {v['runs']}"]
        for case_id, v in rep["per_case"].items()
        if 0 < v["passed"] < v["runs"]
    ]
    if unstable:
        lines += _table(["Case that passed only some runs", "Passed"], unstable)
    return lines


def _shown(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return DASH if value is None else str(value)


def _cases(r: dict) -> list[str]:
    rows = []
    for record in r["records"]:
        case = r["cases"][record["id"]]
        if record["status"] != "ran":
            rows.append([record["id"], record["repetition"], "not run", "", DASH, DASH])
            continue
        result = record["result"]
        answer = result.get("answer") or {}
        got = answer.get("refusal_reason") if result["status"] == "refused" else answer.get("value")
        status = result["status"] + (f" ({result['reason']})" if result.get("reason") else "")
        if result["status"] == "error":
            correct = "not scored"
        else:
            correct = "yes" if record["score"]["correct"] else "NO"
        rows.append(
            [
                record["id"],
                record["repetition"],
                status,
                correct,
                "refusal" if case["answer_type"] == "refusal" else _shown(case["expected"]),
                _shown(got)[:200],
            ]
        )
    return _table(["Case", "Run", "How it ended", "Correct", "Expected", "Submitted"], rows)


def render(results: dict, top_only: bool = False) -> str:
    if results.get("suite") == "docs":  # the documentation suite has its own figures
        from evalkit import rag_run

        return rag_run.render(results)
    summary = results["summary"]
    lines = [f"# Evaluation: {_cell(results['variant'])}", ""]
    lines += _warnings(results)
    lines += _what_was_run(results)
    lines += _headline(summary["overall"])
    lines += _refusals(summary["overall"])
    lines += _costs(summary["overall"])
    if not top_only:
        lines += _breakdown("By split", summary["by_split"])
        lines += _breakdown("By kind", summary["by_kind"])
        lines += _breakdown("By family", summary["by_family"])
        if "repetitions" in summary:
            lines += _repetitions(summary["repetitions"])
        lines += _cases(results)
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.report", description=__doc__.split("\n")[0]
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--top", action="store_true", help="only the first tables")
    args = parser.parse_args(argv)
    text = render(json.loads(args.results.read_text(encoding="utf-8")), args.top)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
