"""Scoring: a case, what the agent did with it, and whether that was right.

Deterministic, and no model takes part. ``score_case`` judges one result against one case;
``summarize`` turns the scored results of a run into the figures the report prints. Every
proportion comes with the two counts it is made of and a 95% Wilson interval.

The definitions, in one place:

correct
    For a case with an answer: the submitted value equals ``expected`` or one of
    ``accepted``. Numbers within the case's tolerance (within the absolute bound OR the
    relative one), labels exactly after trimming and case-folding, dates as dates, lists
    element by element and in order. Refusing such a case is wrong. For a case with no
    answer, refusing is right and anything else is wrong.
execution accuracy
    Correct cases over cases that have an answer.
valid SQL
    Queries that ran over all queries sent; and, separately, questions with at least one
    failed query over all questions.
refusals
    The two-by-two table of "should refuse" against "did refuse", with precision (of the
    refusals made, how many were due) and recall (of the refusals due, how many were made).
hallucination rate
    Cases answered when they should have been refused, plus answers marked ungrounded,
    over all cases. A value that is right and ungrounded counts as correct AND here:
    accuracy says what was answered, this says where it came from.
cost, tokens, seconds
    Per question: mean, median and 95th percentile (nearest rank). Cost per correct answer
    is the whole cost over the number of correct cases.

A case that was not run is in none of these: it is counted apart, and a run with any such
case is partial.
"""

from __future__ import annotations

import datetime
import math
import statistics
from decimal import Decimal, InvalidOperation

Z_95 = 1.959963984540054  # the 97.5th percentile of the standard normal


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _date(value: object) -> datetime.date | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment.date() if moment.time() == datetime.time(0) else None


def _label(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    return str(value).strip().casefold()


def number_matches(value: object, expected: str, tolerance: dict) -> bool:
    """Within the absolute bound, or within the relative one. Both zero means exact."""
    got, want = _number(value), _number(expected)
    if got is None or want is None:
        return False
    off = abs(got - want)
    return off <= Decimal(tolerance["abs"]) or off <= Decimal(tolerance["rel"]) * abs(want)


def _element_matches(value: object, expected: str) -> bool:
    """One element of a list: as a date when both are dates, as a number when both are
    numbers (exactly), otherwise as a label."""
    if _date(expected) is not None and _date(value) is not None:
        return _date(value) == _date(expected)
    if _number(expected) is not None and _number(value) is not None:
        return _number(value) == _number(expected)
    return _label(value) is not None and _label(value) == _label(expected)


def value_matches(
    value: object, expected: object, answer_type: str, tolerance: dict | None
) -> bool:
    if answer_type == "number":
        return number_matches(value, expected, tolerance)
    if answer_type == "date":
        return _date(value) is not None and _date(value) == _date(expected)
    if answer_type == "list":
        return (
            isinstance(value, list)
            and isinstance(expected, list)
            and len(value) == len(expected)
            and all(_element_matches(v, e) for v, e in zip(value, expected, strict=True))
        )
    return _label(value) is not None and _label(value) == _label(expected)


def score_case(case: dict, result: dict) -> dict:
    """Judge one result of the agent against one case."""
    should_refuse = case["answer_type"] == "refusal"
    status = result.get("status")
    refused = status == "refused"
    gave_value = status in ("answered", "ungrounded")
    answer = result.get("answer") or {}
    if should_refuse:
        correct = refused
    else:
        correct = gave_value and any(
            value_matches(answer.get("value"), wanted, case["answer_type"], case["tolerance"])
            for wanted in (case["expected"], *case["accepted"])
        )
    queries = [call for call in result.get("tool_calls") or [] if call.get("name") == "run_sql"]
    ran = sum(1 for call in queries if (call.get("summary") or {}).get("ok"))
    tokens = result.get("tokens") or {}
    return {
        "correct": bool(correct),
        "should_refuse": should_refuse,
        "refused": refused,
        "gave_value": gave_value,
        "ungrounded": status == "ungrounded",
        "hallucinated": (should_refuse and gave_value) or status == "ungrounded",
        "queries": len(queries),
        "queries_ok": ran,
        "usd": str(result.get("usd", "0")),
        "tokens": sum(int(tokens.get(name, 0)) for name in tokens),
        "seconds": float(result.get("seconds", 0)),
    }


def wilson(successes: int, total: int, z: float = Z_95) -> tuple[float, float] | None:
    """The Wilson score interval for a proportion. None when there is nothing to count."""
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion(successes: int, total: int) -> dict:
    """A proportion with the counts it is made of and its 95% Wilson interval."""
    interval = wilson(successes, total)
    return {
        "k": successes,
        "n": total,
        "value": successes / total if total else None,
        "low": interval[0] if interval else None,
        "high": interval[1] if interval else None,
    }


def percentile_95(values: list[float]) -> float | None:
    """The 95th percentile by nearest rank: the smallest value with 95% at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def distribution(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "median": None, "p95": None}
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile_95(values),
    }


def _figures(scores: list[dict]) -> dict:
    """Every figure for one group of scored results."""
    with_answer = [s for s in scores if not s["should_refuse"]]
    due = [s for s in scores if s["should_refuse"]]
    made = [s for s in scores if s["refused"]]
    queries = sum(s["queries"] for s in scores)
    correct = sum(1 for s in scores if s["correct"])
    spent = sum((Decimal(s["usd"]) for s in scores), Decimal(0))
    return {
        "cases": len(scores),
        "correct": proportion(correct, len(scores)),
        "execution_accuracy": proportion(
            sum(1 for s in with_answer if s["correct"]), len(with_answer)
        ),
        "valid_sql": proportion(sum(s["queries_ok"] for s in scores), queries),
        "questions_with_a_failed_query": proportion(
            sum(1 for s in scores if s["queries_ok"] < s["queries"]), len(scores)
        ),
        "refusals": {
            "should_and_did": sum(1 for s in due if s["refused"]),
            "should_and_did_not": sum(1 for s in due if not s["refused"]),
            "should_not_and_did": sum(1 for s in with_answer if s["refused"]),
            "should_not_and_did_not": sum(1 for s in with_answer if not s["refused"]),
            "precision": proportion(sum(1 for s in made if s["should_refuse"]), len(made)),
            "recall": proportion(sum(1 for s in due if s["refused"]), len(due)),
        },
        "hallucination_rate": proportion(sum(1 for s in scores if s["hallucinated"]), len(scores)),
        "ungrounded": proportion(sum(1 for s in scores if s["ungrounded"]), len(scores)),
        "usd": {
            "total": str(spent),
            "per_correct_answer": str(spent / correct) if correct else None,
            **distribution([float(s["usd"]) for s in scores]),
        },
        "tokens": distribution([float(s["tokens"]) for s in scores]),
        "seconds": distribution([s["seconds"] for s in scores]),
    }


def summarize(records: list[dict], cases: dict[str, dict]) -> dict:
    """The figures of a run. ``records`` are its lines; ``cases`` the cases by id.

    A record that was not run has no score and enters no figure. It is counted in
    ``not_run``, and ``partial`` is true when there is at least one.
    """
    ran = [r for r in records if r["status"] == "ran"]
    scores = [r["score"] for r in ran]
    by_kind: dict[str, list[dict]] = {}
    by_family: dict[str, list[dict]] = {}
    for record in ran:
        case = cases[record["id"]]
        by_kind.setdefault(case["kind"], []).append(record["score"])
        by_family.setdefault(f"{case['kind']} / {case['family']}", []).append(record["score"])
    summary = {
        "records": len(records),
        "ran": len(ran),
        "not_run": len(records) - len(ran),
        "partial": len(ran) < len(records),
        "overall": _figures(scores),
        "by_kind": {kind: _figures(group) for kind, group in sorted(by_kind.items())},
        "by_family": {family: _figures(group) for family, group in sorted(by_family.items())},
    }
    repetitions = sorted({r["repetition"] for r in records})
    if len(repetitions) > 1:
        per_case: dict[str, list[bool]] = {}
        for record in ran:
            per_case.setdefault(record["id"], []).append(record["score"]["correct"])
        per_run = [
            proportion(
                sum(1 for r in ran if r["repetition"] == n and r["score"]["correct"]),
                sum(1 for r in ran if r["repetition"] == n),
            )
            for n in repetitions
        ]
        rates = [run["value"] for run in per_run if run["value"] is not None]
        summary["repetitions"] = {
            "count": len(repetitions),
            "per_case": {
                case_id: {"passed": sum(passed), "runs": len(passed)}
                for case_id, passed in sorted(per_case.items())
            },
            "always_passed": sum(1 for passed in per_case.values() if all(passed)),
            "never_passed": sum(1 for passed in per_case.values() if not any(passed)),
            "sometimes_passed": sum(
                1 for passed in per_case.values() if any(passed) and not all(passed)
            ),
            "correct_per_run": per_run,
            "spread": {
                "lowest": min(rates) if rates else None,
                "highest": max(rates) if rates else None,
                "range": max(rates) - min(rates) if rates else None,
            },
        }
    return summary
