"""One question, from the first model call to an answer or to ``no_answer``.

The loop gives the model three tools: ``describe_schema`` and ``run_sql`` (agent.tools) and
``submit_answer``, which ends the question. It stops on ``submit_answer`` or after a fixed
number of model calls, and at the cap the result is ``no_answer``: it never makes up an
answer from what it has seen.

Before every model call the budget is asked whether the worst case of that call still
fits. A call that does not fit is not sent.

One kind of request is sent again: one the API answered with 429 or 529. Those say the
request was not served, so nothing was billed. The loop waits what the ``retry-after``
header says, at most a minute, and sends the same request again, at most three times for
one call. Every wait is recorded in the result. Nothing else is ever sent twice.

How a question ends is one of five things. ``answered``, ``refused`` and ``ungrounded`` are
what the model submitted. ``no_answer`` is the model's outcome too: it reached the cap of
model calls, or it stopped. ``error`` is not the model's: the API or the network failed
after those waits, or the budget refused a call.

An answer is checked against the rows of the last turn in which a ``run_sql`` succeeded:
the value submitted has to be a cell of one of that turn's results. A model may send
several queries in one turn, and which of them comes back last is an accident of order, so
all of them count; a result of an earlier turn does not. When the value is in none of them,
the answer is kept and marked ``ungrounded``. The first rows of the last result are kept in
the result.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agent import docs_index
from agent import llm as llm_module
from agent.budget import BudgetExceeded, DollarBudget
from agent.llm import LLM, Usage
from agent.tools import Tools

SYSTEM_PROMPT_FILE = Path(__file__).parent / "prompts" / "system.md"
DEFAULT_MAX_ITERATIONS = 6
DEFAULT_MAX_TOKENS = 4096
# After a 429 or a 529: how often one call is sent again, and how long a wait can be.
MAX_RESENDS = 3
MAX_WAIT_SECONDS = 60.0
# With no retry-after header: 10, 20, then 40 seconds.
WAIT_WITHOUT_HEADER_SECONDS = 10.0
# Rows of the last result kept in the result of a question.
KEPT_ROWS = 50
NO_DESCRIPTIONS = "There are no descriptions: names and types are all there is."
WITH_DESCRIPTIONS = (
    "Where a table or a column has a description, it comes back next to its name and type: "
    "read it before choosing a column."
)
ANSWER_TYPES = ("number", "label", "date", "list", "refusal")
ANSWER_FIELDS = ("type", "value", "unit", "sql", "explanation", "refusal_reason")

TOOL_DEFINITIONS = [
    {
        "name": "describe_schema",
        "description": (
            "Column names and types of the tables you can read, and the dates the data "
            "covers. Call it before writing SQL. With no argument it describes every table."
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

SEARCH_DOCS_DEFINITION = {
    "name": "search_docs",
    "description": (
        "Search the project's documentation (README, decisions, docs) for what the data "
        "means and why things are the way they are. Returns the best matching chunks, each "
        "with an id. Use it for questions the tables cannot answer by themselves."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to search for."},
            "k": {
                "type": "integer",
                "description": f"How many chunks, 1 to {docs_index.MAX_K}. Default "
                f"{docs_index.DEFAULT_K}.",
            },
            "source": {
                "type": "string",
                "enum": list(docs_index.SOURCES),
                "description": (
                    f"{docs_index.DOCS_SOURCE} (the default): the documentation. "
                    f"{docs_index.DBT_SOURCE}: the descriptions of the dbt models and their "
                    "columns; use it only for a question about a column or a model."
                ),
            },
        },
        "required": ["query"],
    },
}
TEXT_ANSWER = "text"
CITATIONS = "citations"


def tool_definitions(docs: bool = False) -> list:
    """The tools the model is offered. Without ``docs`` it is ``TOOL_DEFINITIONS`` itself.

    With ``docs`` there is a fourth tool, ``search_docs``, and ``submit_answer`` also takes
    the type ``text`` (the value is the answer in words) and ``citations``, the ids of the
    chunks the answer rests on, which must be ids that ``search_docs`` returned.
    """
    if not docs:
        return TOOL_DEFINITIONS
    definitions = copy.deepcopy(TOOL_DEFINITIONS)
    submit = next(d for d in definitions if d["name"] == "submit_answer")
    properties = submit["input_schema"]["properties"]
    properties["type"]["enum"].append(TEXT_ANSWER)
    properties[CITATIONS] = {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "For type text: the ids of the chunks from search_docs that the answer rests on. "
            "An answer in words from the documentation with no citation is ungrounded."
        ),
    }
    return [*definitions[:2], SEARCH_DOCS_DEFINITION, submit]


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

    ``status`` is ``answered``, ``refused``, ``ungrounded``, ``no_answer`` or ``error``.
    ``reason`` says why for the last three. ``answer`` holds the six fields of
    ``submit_answer`` when the model submitted one. ``final_sql`` is the last statement
    that actually ran successfully, and ``last_result`` what it returned: the column names,
    the first ``KEPT_ROWS`` rows, and how many rows there were. ``waits`` has one entry for
    every time the loop waited after a 429 or a 529 before sending a call again.
    ``queries`` has every statement that ran successfully, in order, each with what it
    returned, kept the same way; the last of them is ``final_sql`` and ``last_result``.
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
    waits: list[dict] = field(default_factory=list)
    last_result: dict | None = None
    queries: list[dict] = field(default_factory=list)
    # What the provider reported, call by call, put together: the models that answered,
    # the dollars it billed (None when it billed nothing it told us of), and each header
    # it was asked for with the values it took.
    served_models: list[str] = field(default_factory=list)
    billed_usd: Decimal | None = None
    reports: dict[str, list[str]] = field(default_factory=dict)
    # With the docs tool: every chunk search_docs returned in this question, id and text.
    documents: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        out = {
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
            "waits": list(self.waits),
            "last_result": self.last_result,
            "queries": list(self.queries),
            "served_models": list(self.served_models),
            "billed_usd": None if self.billed_usd is None else str(self.billed_usd),
            "reports": {name: list(values) for name, values in self.reports.items()},
        }
        if self.documents:  # only a run with the docs tool has them: the baseline is as it was
            out["documents"] = list(self.documents)
        return out


def system_prompt(
    max_iterations: int, row_cap: int, addendum: str = "", descriptions: bool = False
) -> str:
    """The system prompt. ``addendum`` is appended as it is, after a blank line.

    ``descriptions`` says whether ``describe_schema`` will return any, so that the prompt
    does not tell the model there are none when there are.
    """
    template = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{max_iterations}}", str(max_iterations))
        .replace("{{row_cap}}", str(row_cap))
        .replace("{{descriptions}}", WITH_DESCRIPTIONS if descriptions else NO_DESCRIPTIONS)
    )
    if addendum.strip():
        prompt = prompt.rstrip("\n") + "\n\n" + addendum.strip() + "\n"
    return prompt


def wait_seconds(retry_after: float | None, attempt: int) -> float:
    """How long to wait before sending a call again: what the API said, at most a minute."""
    if retry_after is None:
        retry_after = WAIT_WITHOUT_HEADER_SECONDS * 2 ** (attempt - 1)
    return min(max(retry_after, 0.0), MAX_WAIT_SECONDS)


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
        # A value sent as a JSON number is a double by the time it is read here, and a
        # double cannot carry the digits of a long decimal cell. It is that cell when the
        # cell, read as a double, is the same double. A value sent as text is compared
        # digit for digit, and so is a cell that is a whole number: those arrive exact.
        if a == b:
            return True
        return isinstance(value, float) and a != a.to_integral_value() and float(a) == value
    if isinstance(cell, bool) or isinstance(value, bool):
        return cell is value
    return str(cell) == str(value)


def is_grounded(answer_type: str, value: object, rows: list[list] | None) -> bool:
    """The value, or for a list every element of it, is a cell of ``rows``.

    ``rows`` is every row returned in the last turn in which a query ran: see ``TurnRows``.
    """
    if rows is None:
        return False
    cells = [cell for row in rows for cell in row]
    if any(same_value(cell, value) for cell in cells):
        return True
    if answer_type == "list" and isinstance(value, list) and value:
        return all(any(same_value(cell, item) for cell in cells) for item in value)
    return False


class TurnRows:
    """The rows an answer is checked against: those of the last turn that ran a query.

    ``add`` takes the turn a successful query was sent in and its rows. Rows of one turn
    are kept together; a later turn replaces them.
    """

    def __init__(self) -> None:
        self.turn: object = None
        self.rows: list[list] | None = None

    def add(self, turn: object, rows: list[list]) -> None:
        if self.rows is None or turn != self.turn:
            self.turn, self.rows = turn, []
        self.rows = self.rows + rows


def _summary(name: str, output: dict) -> dict:
    if not output.get("ok"):
        return {"ok": False, **output.get("error", {})}
    if name == "search_docs":
        return {"ok": True, "ids": [chunk["id"] for chunk in output["chunks"]]}
    if name == "describe_schema":
        summary = {"ok": True, "tables": {t: len(c) for t, c in output["tables"].items()}}
        if "coverage" in output:
            summary["coverage"] = [output["coverage"]["first"], output["coverage"]["last"]]
        return summary
    return {
        "ok": True,
        "columns": [c["name"] for c in output["columns"]],
        "row_count": output["row_count"],
        "truncated": output["truncated"],
    }


def _check_answer(given: object, docs: bool = False) -> tuple[dict | None, str]:
    """The six fields, or what is wrong with them, in a sentence for the model.

    With ``docs`` the type ``text`` is allowed, and the answer also keeps ``citations``.
    """
    if not isinstance(given, dict):
        return None, "submit_answer takes an object."
    answer = {name: given.get(name) for name in ANSWER_FIELDS}
    kind = answer["type"]
    allowed = (*ANSWER_TYPES, TEXT_ANSWER) if docs else ANSWER_TYPES
    if kind not in allowed:
        return None, f"type must be one of: {', '.join(allowed)}."
    if docs:
        answer[CITATIONS] = given.get(CITATIONS)
    if kind == TEXT_ANSWER:
        if not isinstance(answer["value"], str) or not answer["value"].strip():
            return None, "For type text the value must be the answer, in words."
        return answer, ""
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
    transcript: list | None = None,
    prompt_addendum: str = "",
    sleep: Callable[[float], None] = time.sleep,
    prompt_cache: bool = False,
    docs: dict[str, docs_index.Index] | None = None,
) -> Result:
    """Run one question. With ``transcript``, every turn is appended to that list as plain
    data: the question, what the model said and called, and what each tool returned in
    full. A turn of the model also has ``block_types``: the type of every block it returned,
    in order, including the ones whose content is not kept, such as a reasoning block. It
    is for whoever keeps a record outside the result; the loop does not read it.
    ``prompt_addendum`` is text appended to the system prompt; where it comes from is the
    caller's business. With ``prompt_cache``, the tool definitions and the system prompt
    are sent as a cached prefix: the model is sent the same text, billed differently.
    With ``docs`` (one index per source, ``docs_index.load_library``) the model is also
    offered ``search_docs`` and may answer in words with citations; without it nothing about
    the tools changes."""
    started = clock()
    result = Result(question=question, model=llm.model)
    system = system_prompt(
        max_iterations,
        row_cap,
        prompt_addendum,
        descriptions=bool(getattr(tools, "has_descriptions", False)),
    )
    messages: list = [{"role": "user", "content": question}]

    def keep(role: str, content: object, block_types: list[str] | None = None) -> None:
        if transcript is not None:
            turn = {"role": role, "content": content}
            if block_types is not None:
                # Every block the model returned, by type. ``content`` has only the ones
                # the loop acts on; the others are sent back unread and are not kept.
                turn["block_types"] = block_types
            transcript.append(turn)

    keep("user", question)
    checked = TurnRows()
    definitions = tool_definitions(docs is not None)
    returned: set[str] = set()  # ids that search_docs gave in this question

    def finish(status: str, reason: str = "") -> Result:
        result.status, result.reason = status, reason
        result.seconds = clock() - started
        return result

    sent = llm_module.cached_prefix(system) if prompt_cache else system
    for iteration in range(1, max_iterations + 1):
        ceiling = llm_module.input_token_ceiling(sent, messages, definitions)
        may_write = prompt_cache or bool(getattr(llm, "may_write_cache", False))
        worst = llm_module.worst_case_usd(llm.model, ceiling, max_tokens, may_write)
        try:
            budget.check(worst)
        except BudgetExceeded as refusal:
            return finish("error", f"budget: {refusal}")
        response = None
        for resend in range(MAX_RESENDS + 1):
            try:
                response = llm.complete(
                    system=sent,
                    messages=messages,
                    tools=definitions,
                    max_tokens=max_tokens,
                )
                break
            except Exception as exc:  # noqa: BLE001 - whatever failed is handled here
                known = isinstance(exc, llm_module.LLMError)
                if known and exc.rate_limited and resend < MAX_RESENDS:
                    # 429 or 529: the request was not served and nothing was billed. Wait
                    # what the API says and send the same request again. This is the one
                    # request the loop sends twice.
                    seconds = wait_seconds(exc.retry_after, resend + 1)
                    budget.fail(
                        Decimal(0),
                        f"iteration {iteration}: HTTP {exc.status_code}, not served, booked "
                        f"at zero; waiting {seconds:g} s before sending it again",
                        model=llm.model,
                    )
                    result.waits.append(
                        {
                            "iteration": iteration,
                            "attempt": resend + 1,
                            "status_code": exc.status_code,
                            "seconds": seconds,
                            "from_header": exc.retry_after is not None,
                        }
                    )
                    sleep(seconds)
                    continue
                # A request the API rejected (a 4xx status, or a 529) was not served, so it
                # cost nothing. Anything else (a timeout, a lost connection, another 5xx)
                # may have been served and billed, and is booked at the most it could cost.
                if known and exc.rejected:
                    booked = Decimal(0)
                    note = (
                        f"iteration {iteration}: rejected by the API with HTTP "
                        f"{exc.status_code} ({exc.error_type or 'no error type'}), not "
                        "served, booked at zero"
                    )
                else:
                    booked = worst
                    note = f"iteration {iteration}: {type(exc).__name__}, booked at the worst case"
                budget.fail(booked, note, model=llm.model)
                result.usd += booked
                result.iterations = iteration
                detail = str(exc) if known else type(exc).__name__
                return finish("error", f"llm_error: {detail}")
        cost = llm_module.cost_usd(llm.model, response.usage)
        budget.record(cost, f"iteration {iteration}", model=llm.model, **asdict(response.usage))
        result.usd += cost
        result.usage = result.usage + response.usage
        if response.served_model and response.served_model not in result.served_models:
            result.served_models.append(response.served_model)
        if response.billed_usd is not None:
            result.billed_usd = (result.billed_usd or Decimal(0)) + response.billed_usd
        for name, value in response.reports:
            if value not in result.reports.setdefault(name, []):
                result.reports[name].append(value)
        result.iterations = iteration

        if response.stop_reason in ("refusal", "max_tokens", "pause_turn"):
            return finish("no_answer", f"model_stop: {response.stop_reason}")

        messages.append({"role": "assistant", "content": response.assistant_content()})
        keep("assistant", list(response.content), response.types())
        calls = [block for block in response.content if block["type"] == "tool_use"]
        if not calls:
            messages.append({"role": "user", "content": NUDGE})
            keep("user", NUDGE)
            continue

        outputs = []
        for call in calls:
            name, given = call["name"], call.get("input") or {}
            if name == "submit_answer":
                answer, problem = _check_answer(given, docs is not None)
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
                if answer["type"] == TEXT_ANSWER:
                    cited = answer[CITATIONS]
                    grounded = (
                        isinstance(cited, list)
                        and bool(cited)
                        and all(isinstance(c, str) and c in returned for c in cited)
                    )
                    reason = "the answer cites no chunk that search_docs returned"
                else:
                    grounded = is_grounded(answer["type"], answer["value"], checked.rows)
                    reason = "the value is not a cell of the last result"
                result.tool_calls.append(
                    ToolCall(iteration, name, given, {"ok": True, "grounded": grounded})
                )
                if grounded:
                    return finish("answered")
                return finish("ungrounded", reason)
            if name == "describe_schema":
                wanted = given.get("tables") if isinstance(given, dict) else None
                output = tools.describe_schema(wanted if isinstance(wanted, list) else None)
            elif name == "search_docs" and docs is not None:
                asked = given if isinstance(given, dict) else {}
                output = docs_index.search_docs(
                    docs,
                    asked.get("query"),
                    asked.get("k", docs_index.DEFAULT_K),
                    asked.get("source", docs_index.DOCS_SOURCE),
                )
                for chunk in output.get("chunks", []):
                    if chunk["id"] not in returned:
                        returned.add(chunk["id"])
                        result.documents.append(chunk)
            elif name == "run_sql":
                sql = given.get("sql") if isinstance(given, dict) else None
                output = tools.run_sql(sql)
                if output.get("ok"):
                    checked.add(iteration, output["rows"])
                    result.final_sql = sql
                    result.last_result = {
                        "columns": [column["name"] for column in output["columns"]],
                        "rows": output["rows"][:KEPT_ROWS],
                        "row_count": output["row_count"],
                        "truncated": output["truncated"],
                    }
                    result.queries.append({"sql": sql, **result.last_result})
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
        keep("user", messages[-1]["content"])
    return finish("no_answer", f"iteration_cap: {max_iterations} model calls without an answer")
