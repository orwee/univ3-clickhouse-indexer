"""One question, from the first model call to an answer or to ``no_answer``.

The loop gives the model three tools: ``describe_schema`` and ``run_sql`` (agent.tools) and
``submit_answer``, which ends the question. It stops on ``submit_answer`` or after a fixed
number of model calls, and at the cap the result is ``no_answer``: it never makes up an
answer from what it has seen.

Before every model call the budget is asked whether the worst case of that call still
fits. A call that does not fit is not sent.

An answer is checked against the rows of the last successful ``run_sql``: the value
submitted has to be one of its cells. When it is not, the answer is kept and marked
``ungrounded``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agent import llm as llm_module
from agent.budget import BudgetExceeded, DollarBudget
from agent.llm import LLM, Usage
from agent.tools import Tools

SYSTEM_PROMPT_FILE = Path(__file__).parent / "prompts" / "system.md"
DEFAULT_MAX_ITERATIONS = 6
DEFAULT_MAX_TOKENS = 4096
ANSWER_TYPES = ("number", "label", "date", "list", "refusal")
ANSWER_FIELDS = ("type", "value", "unit", "sql", "explanation", "refusal_reason")

TOOL_DEFINITIONS = [
    {
        "name": "describe_schema",
        "description": (
            "Column names and types of the tables you can read. Call it before writing SQL. "
            "With no argument it describes every table."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Table names to describe. Omit for all of them.",
                }
            },
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run one ClickHouse SELECT (or WITH ... SELECT) and get its rows back. Errors "
            "come back as a result to read, not as a failure. Rows beyond the cap are cut "
            "and flagged with truncated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "One SELECT statement."}},
            "required": ["sql"],
        },
    },
    {
        "name": "submit_answer",
        "description": (
            "End the question with an answer or a refusal. The value must be a cell of the "
            "result of your last run_sql call, copied exactly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": list(ANSWER_TYPES)},
                "value": {
                    "description": (
                        "The cell of the last result that answers the question; for a list, "
                        "an array of cells. Omit for a refusal."
                    )
                },
                "unit": {"type": "string", "description": "The unit of a number, if any."},
                "sql": {"type": "string", "description": "The last query you ran."},
                "explanation": {"type": "string", "description": "What the query measures."},
                "refusal_reason": {
                    "type": "string",
                    "description": "For a refusal: why the data cannot answer.",
                },
            },
            "required": ["type"],
        },
    },
]

NUDGE = (
    "You did not call a tool. Continue with describe_schema or run_sql, or finish with "
    "submit_answer: an answer whose value is a cell of your last result, or a refusal."
)


@dataclass(frozen=True)
class ToolCall:
    iteration: int
    name: str
    input: dict
    summary: dict  # what came back, without the rows


@dataclass
class Result:
    """How one question ended.

    ``status`` is ``answered``, ``refused``, ``ungrounded`` or ``no_answer``. ``reason`` says
    why for the last two. ``answer`` holds the six fields of ``submit_answer`` when the model
    submitted one. ``final_sql`` is the last statement that actually ran successfully.
    """

    question: str
    model: str
    status: str = "no_answer"
    reason: str = ""
    answer: dict | None = None
    final_sql: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    iterations: int = 0
    usage: Usage = field(default_factory=Usage)
    usd: Decimal = Decimal(0)
    seconds: float = 0.0

    def to_json(self) -> dict:
        return {
            "question": self.question,
            "model": self.model,
            "status": self.status,
            "reason": self.reason,
            "answer": self.answer,
            "final_sql": self.final_sql,
            "tool_calls": [asdict(call) for call in self.tool_calls],
            "iterations": self.iterations,
            "tokens": asdict(self.usage),
            "usd": str(self.usd),
            "seconds": round(self.seconds, 3),
        }


def system_prompt(max_iterations: int, row_cap: int) -> str:
    template = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    return template.replace("{{max_iterations}}", str(max_iterations)).replace(
        "{{row_cap}}", str(row_cap)
    )


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def same_value(cell: object, value: object) -> bool:
    """Whether a submitted value is this cell: the same number, or the same text."""
    if cell is None or value is None:
        return False
    if isinstance(cell, (list, dict)) or isinstance(value, (list, dict)):
        return cell == value
    a, b = _number(cell), _number(value)
    if a is not None and b is not None:
        return a == b
    if isinstance(cell, bool) or isinstance(value, bool):
        return cell is value
    return str(cell) == str(value)


def is_grounded(answer_type: str, value: object, rows: list[list] | None) -> bool:
    """The value, or for a list every element of it, is a cell of the last result."""
    if rows is None:
        return False
    cells = [cell for row in rows for cell in row]
    if any(same_value(cell, value) for cell in cells):
        return True
    if answer_type == "list" and isinstance(value, list) and value:
        return all(any(same_value(cell, item) for cell in cells) for item in value)
    return False


def _summary(name: str, output: dict) -> dict:
    if not output.get("ok"):
        return {"ok": False, **output.get("error", {})}
    if name == "describe_schema":
        return {"ok": True, "tables": {t: len(c) for t, c in output["tables"].items()}}
    return {
        "ok": True,
        "columns": [c["name"] for c in output["columns"]],
        "row_count": output["row_count"],
        "truncated": output["truncated"],
    }


def _check_answer(given: object) -> tuple[dict | None, str]:
    """The six fields, or what is wrong with them, in a sentence for the model."""
    if not isinstance(given, dict):
        return None, "submit_answer takes an object."
    answer = {name: given.get(name) for name in ANSWER_FIELDS}
    kind = answer["type"]
    if kind not in ANSWER_TYPES:
        return None, f"type must be one of: {', '.join(ANSWER_TYPES)}."
    if kind == "refusal":
        reason = answer["refusal_reason"]
        if not isinstance(reason, str) or not reason.strip():
            return None, "A refusal needs refusal_reason: why the data cannot answer."
        answer["value"] = None
        return answer, ""
    if answer["value"] is None or answer["value"] == "" or answer["value"] == []:
        return None, "An answer needs a value: a cell of your last result. Or refuse."
    if kind == "list" and not isinstance(answer["value"], list):
        return None, "For type list the value must be an array of cells."
    if kind != "list" and isinstance(answer["value"], (list, dict)):
        return None, f"For type {kind} the value must be a single cell, not a collection."
    return answer, ""


def run(
    question: str,
    llm: LLM,
    tools: Tools,
    budget: DollarBudget,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    row_cap: int = 200,
    clock: Callable[[], float] = time.monotonic,
) -> Result:
    started = clock()
    result = Result(question=question, model=llm.model)
    system = system_prompt(max_iterations, row_cap)
    messages: list = [{"role": "user", "content": question}]
    last_rows: list[list] | None = None

    def finish(status: str, reason: str = "") -> Result:
        result.status, result.reason = status, reason
        result.seconds = clock() - started
        return result

    for iteration in range(1, max_iterations + 1):
        ceiling = llm_module.input_token_ceiling(system, messages, TOOL_DEFINITIONS)
        worst = llm_module.worst_case_usd(llm.model, ceiling, max_tokens)
        try:
            budget.check(worst)
        except BudgetExceeded as refusal:
            return finish("no_answer", f"budget: {refusal}")
        try:
            response = llm.complete(
                system=system, messages=messages, tools=TOOL_DEFINITIONS, max_tokens=max_tokens
            )
        except Exception as exc:  # noqa: BLE001 - whatever failed, the question ends here
            # A request the API rejected with a 4xx status was not served, so it cost
            # nothing. Anything else (a timeout, a lost connection, a 5xx) may have been
            # served and billed, and is booked at the most it could have cost.
            if isinstance(exc, llm_module.LLMError) and exc.rejected:
                booked = Decimal(0)
                note = (
                    f"iteration {iteration}: rejected by the API with HTTP {exc.status_code}"
                    f" ({exc.error_type or 'no error type'}), not served, booked at zero"
                )
            else:
                booked = worst
                note = f"iteration {iteration}: {type(exc).__name__}, booked at the worst case"
            budget.fail(booked, note, model=llm.model)
            result.usd += booked
            result.iterations = iteration
            detail = str(exc) if isinstance(exc, llm_module.LLMError) else type(exc).__name__
            return finish("no_answer", f"llm_error: {detail}")
        cost = llm_module.cost_usd(llm.model, response.usage)
        budget.record(cost, f"iteration {iteration}", model=llm.model, **asdict(response.usage))
        result.usd += cost
        result.usage = result.usage + response.usage
        result.iterations = iteration

        if response.stop_reason in ("refusal", "max_tokens", "pause_turn"):
            return finish("no_answer", f"model_stop: {response.stop_reason}")

        messages.append({"role": "assistant", "content": response.assistant_content()})
        calls = [block for block in response.content if block["type"] == "tool_use"]
        if not calls:
            messages.append({"role": "user", "content": NUDGE})
            continue

        outputs = []
        for call in calls:
            name, given = call["name"], call.get("input") or {}
            if name == "submit_answer":
                answer, problem = _check_answer(given)
                if answer is None:
                    result.tool_calls.append(
                        ToolCall(iteration, name, given, {"ok": False, "message": problem})
                    )
                    outputs.append((call["id"], {"ok": False, "error": problem}, True))
                    continue
                result.answer = answer
                if answer["type"] == "refusal":
                    result.tool_calls.append(ToolCall(iteration, name, given, {"ok": True}))
                    return finish("refused")
                grounded = is_grounded(answer["type"], answer["value"], last_rows)
                result.tool_calls.append(
                    ToolCall(iteration, name, given, {"ok": True, "grounded": grounded})
                )
                if grounded:
                    return finish("answered")
                return finish("ungrounded", "the value is not a cell of the last result")
            if name == "describe_schema":
                wanted = given.get("tables") if isinstance(given, dict) else None
                output = tools.describe_schema(wanted if isinstance(wanted, list) else None)
            elif name == "run_sql":
                sql = given.get("sql") if isinstance(given, dict) else None
                output = tools.run_sql(sql)
                if output.get("ok"):
                    last_rows, result.final_sql = output["rows"], sql
            else:
                output = {"ok": False, "error": {"kind": "unknown_tool", "message": name}}
            result.tool_calls.append(ToolCall(iteration, name, given, _summary(name, output)))
            outputs.append((call["id"], output, not output.get("ok")))
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": json.dumps(output, ensure_ascii=False),
                        **({"is_error": True} if failed else {}),
                    }
                    for call_id, output, failed in outputs
                ],
            }
        )
    return finish("no_answer", f"iteration_cap: {max_iterations} model calls without an answer")
