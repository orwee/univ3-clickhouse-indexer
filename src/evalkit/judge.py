"""A judge for the one thing code cannot check: is the explanation faithful?

    PYTHONPATH=src uv run --group agent python -m evalkit.judge SOURCE \\
        [--rubric evals/judge_rubric.md] [--model ID] [--max-usd 2] [--limit N] [--out FILE]

The scorer decides whether an answer is right, deterministically. What it cannot read is
the explanation in words that comes with the answer: whether those words say only what the
query and its result support. That one question goes to a model, and nothing else does.

- One call per case. The judge is given the question, every query that ran for it with
  the rows it returned (as the results file kept them), in order, the last one marked as
  the final one, and the explanation. It is shown what the answerer saw: an explanation
  may rightly cite a value from an earlier query.
- The verdict comes back through a tool, ``submit_verdict``, with one of two values and
  one sentence of reason. A response with no such call is recorded as ``no_verdict``: free
  text is never read for a verdict.
- The rubric is a file. Its text is the system prompt, word for word, and its SHA-256 is in
  the output.
- Its own budget, checked before every call against the worst case of that call, with the
  same ledger as the agent's. When a call does not fit, the cases left are recorded as
  ``not_judged``.
- A model stronger than the agent's default, taken from the same price table.

SOURCE is a results file of ``python -m evalkit.run`` (every answered question that has an
explanation is judged) or a calibration sheet of ``python -m evalkit.calibration`` (every
row is judged). The output is written after every case and replaced in one step.

A judge is only as good as its agreement with a person. Until ``evalkit.calibration agree``
has been run on labels a person wrote, a verdict from here is not a measurement.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agent import budget, loop
from agent import llm as llm_module
from evalkit import run
from univ3_indexer import config

DEFAULT_RUBRIC = config.REPO_ROOT / "evals" / "judge_rubric.md"
# The strongest model of the price table: the judge reads another model's words.
DEFAULT_MODEL = "claude-opus-5-5"
API_KEY_NAME = "ANTHROPIC_API_KEY"  # noqa: S105 - the name of a variable, not a value
VERDICTS = ("faithful", "unfaithful")
MAX_TOKENS = 2048
FORMAT = 1
SETUP_ERROR = 2
SHEET_COLUMNS = ("row", "question", "earlier", "sql", "result", "explanation", "label")
NO_RESULT = {"columns": [], "rows": [], "row_count": 0}

TOOL = {
    "name": "submit_verdict",
    "description": "Give the verdict on the explanation. Call it exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "reason": {
                "type": "string",
                "description": "One sentence: what is unsupported, or that nothing is.",
            },
        },
        "required": ["verdict", "reason"],
    },
}


class JudgeError(ValueError):
    """The source cannot be judged: not a results file, not a sheet, or nothing in it."""


@dataclass(frozen=True)
class Item:
    """One explanation to judge, with what it has to be faithful to."""

    key: str
    question: str
    sql: str
    result: dict  # {"columns": [...], "rows": [...], "row_count": n}
    explanation: str
    # The queries that ran before the final one, in order: [{"sql": ..., "result": {...}}].
    earlier: tuple = ()
    # A message built by the caller, for what is not a query and its rows (cited passages of
    # documents). When set it is sent as it is and the fields above are not read.
    text: str = ""


def earlier_of(queries: object) -> tuple:
    """The queries before the last, as the judge is shown them. ``queries`` is what a
    result keeps: every statement that ran, each with its columns and its kept rows."""
    if not isinstance(queries, list):
        return ()
    return tuple(
        {
            "sql": str(query.get("sql") or ""),
            "result": {
                "columns": query.get("columns", []),
                "rows": query.get("rows", []),
                "row_count": query.get("row_count", len(query.get("rows", []))),
            },
        }
        for query in queries[:-1]
        if isinstance(query, dict)
    )


def items_from_results(results: dict) -> list[Item]:
    """Every answered question of a results file that has an explanation."""
    items = []
    for record in results.get("records", []):
        result = record.get("result") or {}
        answer = result.get("answer") or {}
        explanation = answer.get("explanation")
        if record.get("status") != "ran" or result.get("status") not in ("answered", "ungrounded"):
            continue
        if not isinstance(explanation, str) or not explanation.strip():
            continue
        items.append(
            Item(
                key=f"{record['id']}#{record['repetition']}",
                question=results["cases"][record["id"]]["question"],
                sql=result.get("final_sql") or "",
                result=result.get("last_result") or dict(NO_RESULT),
                explanation=explanation.strip(),
                earlier=earlier_of(result.get("queries")),
            )
        )
    return items


def items_from_sheet(path: Path) -> list[Item]:
    """Every row of a calibration sheet. The label column is not read: the judge never sees
    what a person answered."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != SHEET_COLUMNS:
            raise JudgeError(f"{path}: the columns must be {', '.join(SHEET_COLUMNS)}")
        rows = list(reader)
    try:
        return [
            Item(
                key=row["row"],
                question=row["question"],
                sql=row["sql"],
                result=json.loads(row["result"]),
                explanation=row["explanation"],
                earlier=tuple(
                    {"sql": str(query["sql"]), "result": query["result"]}
                    for query in json.loads(row["earlier"] or "[]")
                ),
            )
            for row in rows
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise JudgeError(f"{path}: a result or an earlier cell is not what it should be") from None


def load_items(source: Path) -> tuple[list[Item], dict]:
    """The items of a source and what the output says about it."""
    content = source.read_bytes()
    about = {"file": source.name, "sha256": hashlib.sha256(content).hexdigest()}
    if source.suffix == ".csv":
        return items_from_sheet(source), {**about, "kind": "sheet"}
    try:
        results = json.loads(content)
    except json.JSONDecodeError:
        raise JudgeError(f"{source}: neither a results file nor a sheet") from None
    if not isinstance(results, dict) or "records" not in results or "cases" not in results:
        raise JudgeError(f"{source}: not a results file")
    about = {**about, "kind": "results", "run_id": results.get("run_id")}
    return items_from_results(results), about


def _shown(result: dict) -> tuple[str, str]:
    """The attributes of a result block, and its body."""
    shown = len(result.get("rows", []))
    return (
        f'rows_in_all="{result.get("row_count", shown)}" rows_shown="{shown}"',
        json.dumps(
            {"columns": result.get("columns", []), "rows": result.get("rows", [])},
            ensure_ascii=False,
        ),
    )


def message(item: Item) -> str:
    """The four things, each in its own block. What is in them is data for the judge.

    Every query that ran is there, in order: the ones before the last as numbered
    ``earlier_query`` and ``earlier_result`` blocks, then the final one as it always was.
    An item with its own ``text`` is sent as that text.
    """
    if item.text:
        return item.text
    before: list[str] = []
    for number, query in enumerate(item.earlier, start=1):
        attributes, body = _shown(query["result"])
        before += [
            f'<earlier_query number="{number}">',
            query["sql"],
            "</earlier_query>",
            "",
            f'<earlier_result number="{number}" {attributes}>',
            body,
            "</earlier_result>",
            "",
        ]
    result = item.result
    shown = len(result.get("rows", []))
    return "\n".join(
        [
            "<question>",
            item.question,
            "</question>",
            "",
            *before,
            "<final_sql>",
            item.sql or "(no query ran)",
            "</final_sql>",
            "",
            f'<result rows_in_all="{result.get("row_count", shown)}" rows_shown="{shown}">',
            json.dumps(
                {"columns": result.get("columns", []), "rows": result.get("rows", [])},
                ensure_ascii=False,
            ),
            "</result>",
            "",
            "<explanation>",
            item.explanation,
            "</explanation>",
        ]
    )


def _verdict(response: llm_module.Response) -> tuple[str | None, str]:
    """The verdict and the reason of the first well-formed ``submit_verdict`` call."""
    for block in response.content:
        if block["type"] != "tool_use" or block["name"] != TOOL["name"]:
            continue
        given = block.get("input") or {}
        verdict, reason = given.get("verdict"), given.get("reason")
        if verdict in VERDICTS and isinstance(reason, str) and reason.strip():
            return verdict, " ".join(reason.split())
    return None, ""


def judge_one(
    item: Item,
    llm: llm_module.LLM,
    purse: budget.DollarBudget,
    rubric: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """One call for one item. Raises ``BudgetExceeded`` before the call when it does not fit.

    The outcome is ``judged`` (a verdict and a reason), ``no_verdict`` (the model answered
    without a well-formed call of the tool) or ``error`` (the call failed). A request the
    API answered with 429 or 529 is sent again as the agent's loop does it: the same waits,
    the same three times at most.
    """
    messages = [{"role": "user", "content": message(item)}]
    ceiling = llm_module.input_token_ceiling(rubric, messages, [TOOL])
    worst = llm_module.worst_case_usd(llm.model, ceiling, MAX_TOKENS)
    purse.check(worst)
    out = {
        "key": item.key,
        "status": "error",
        "verdict": None,
        "reason": "",
        "usd": "0",
        "waits": [],
    }
    for resend in range(loop.MAX_RESENDS + 1):
        try:
            response = llm.complete(
                system=rubric, messages=messages, tools=[TOOL], max_tokens=MAX_TOKENS
            )
            break
        except Exception as exc:  # noqa: BLE001 - whatever failed is recorded
            known = isinstance(exc, llm_module.LLMError)
            if known and exc.rate_limited and resend < loop.MAX_RESENDS:
                seconds = loop.wait_seconds(exc.retry_after, resend + 1)
                purse.fail(Decimal(0), f"{item.key}: HTTP {exc.status_code}, not served")
                out["waits"].append({"status_code": exc.status_code, "seconds": seconds})
                sleep(seconds)
                continue
            booked = Decimal(0) if known and exc.rejected else worst
            purse.fail(booked, f"{item.key}: {type(exc).__name__}", model=llm.model)
            out["usd"] = str(booked)
            out["reason"] = str(exc) if known else type(exc).__name__
            return out
    cost = llm_module.cost_usd(llm.model, response.usage)
    purse.record(cost, item.key, model=llm.model, **asdict(response.usage))
    verdict, reason = _verdict(response)
    out.update(
        status="judged" if verdict else "no_verdict",
        verdict=verdict,
        reason=reason or f"no well-formed {TOOL['name']} call (stop: {response.stop_reason})",
        usd=str(cost),
        tokens=asdict(response.usage),
    )
    return out


def summarize(verdicts: list[dict]) -> dict:
    count = lambda **want: sum(  # noqa: E731
        1 for v in verdicts if all(v.get(k) == x for k, x in want.items())
    )
    return {
        "items": len(verdicts),
        "judged": count(status="judged"),
        "faithful": count(verdict="faithful"),
        "unfaithful": count(verdict="unfaithful"),
        "no_verdict": count(status="no_verdict"),
        "errors": count(status="error"),
        "not_judged": count(status="not_judged"),
    }


def judge_all(
    items: list[Item],
    llm: llm_module.LLM,
    rubric: str,
    *,
    max_usd: Decimal,
    ledger: Path | None,
    scope: str,
    after_each: Callable[[list[dict]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict], Decimal]:
    """Judge every item, in order, until done or until the budget refuses a call."""
    purse = budget.DollarBudget(max_usd, ledger, scope=scope)
    verdicts: list[dict] = []
    stopped = ""
    for item in items:
        if not stopped:
            try:
                verdicts.append(judge_one(item, llm, purse, rubric, sleep=sleep))
            except budget.BudgetExceeded as refusal:
                stopped = f"the judge's budget: {refusal}"
            else:
                if after_each is not None:
                    after_each(verdicts)
                continue
        verdicts.append(
            {"key": item.key, "status": "not_judged", "verdict": None, "reason": stopped}
        )
    return verdicts, purse.spent


def _stop(text: str) -> int:
    print(text, file=sys.stderr)
    return SETUP_ERROR


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def main(
    argv: list[str] | None = None,
    *,
    make_llm: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.judge", description=__doc__.split("\n")[0]
    )
    parser.add_argument("source", type=Path, help="a results file (.json) or a sheet (.csv)")
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="a model with a price")
    parser.add_argument("--max-usd", default="2", help="dollars for all the verdicts")
    parser.add_argument("--limit", type=int, default=None, help="only the first N items")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        max_usd = Decimal(args.max_usd)
        llm_module.price_of(args.model)
        rubric = args.rubric.read_text(encoding="utf-8")
        items, about = load_items(args.source)
    except InvalidOperation:
        return _stop(f"--max-usd must be a number, got {args.max_usd!r}")
    except (llm_module.UnknownModel, JudgeError) as problem:
        return _stop(str(problem))
    except (OSError, KeyError) as problem:
        return _stop(f"{type(problem).__name__}: {problem}")
    if args.limit is not None:
        items = items[: max(args.limit, 0)]
    if not items:
        return _stop("nothing to judge: no answered question with an explanation")
    try:
        if make_llm is not None:
            model = make_llm(args.model)
        else:
            model = llm_module.AnthropicLLM(config.require_api_key(API_KEY_NAME), args.model)
    except config.ConfigError as problem:
        return _stop(f"No model key: {problem}")
    except ImportError:
        return _stop("The anthropic package is not installed: run with `uv run --group agent`.")

    started = _now()
    judge_id = f"{started.replace(':', '').replace('+0000', 'Z')}_judge_{uuid.uuid4().hex[:6]}"
    out = args.out or config.data_dir() / "judge" / f"{judge_id}.json"
    output = {
        "format": FORMAT,
        "state": run.UNFINISHED,
        "judge_id": judge_id,
        "model": model.model,
        "rubric_file": args.rubric.name,
        "rubric_sha256": hashlib.sha256(rubric.encode("utf-8")).hexdigest(),
        "source": about,
        "started": started,
        "ended": None,
        "budget_usd": str(max_usd),
        "spent_usd": "0",
    }

    def put(verdicts: list[dict], finished: bool) -> None:
        spent = sum((Decimal(v.get("usd", "0")) for v in verdicts), Decimal(0))
        output.update(
            state=run.COMPLETE if finished else run.UNFINISHED,
            ended=_now() if finished else None,
            spent_usd=str(spent),
            summary=summarize(verdicts),
            verdicts=verdicts,
        )
        run.write(out, output)

    put([], finished=False)
    verdicts, _ = judge_all(
        items,
        model,
        rubric,
        max_usd=max_usd,
        ledger=budget.default_ledger(),
        scope=f"judge:{judge_id}",
        after_each=lambda so_far: put(so_far, finished=False),
        sleep=sleep,
    )
    put(verdicts, finished=True)
    s = output["summary"]
    print(
        f"{s['judged']} of {s['items']} judged: {s['faithful']} faithful, {s['unfaithful']} "
        f"unfaithful; {s['no_verdict']} without a verdict, {s['errors']} errors, "
        f"{s['not_judged']} not judged; spent ${output['spent_usd']} of ${max_usd}"
    )
    print(f"verdicts: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
