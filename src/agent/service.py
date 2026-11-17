"""The agent as a small HTTP service: one endpoint, ``POST /ask``, and a trace per question.

    PYTHONPATH=src uv run --group agent uvicorn agent.service:app_from_env --factory \\
        --host 127.0.0.1 --port 8000

``POST /ask`` takes ``{"question": "...", "max_usd": "0.10"}`` (``max_usd`` optional, at
most the warehouse file's limit) and runs the same loop as ``python -m agent``, with the
same tools, the same read-only user and the same dollar budget. It answers 200 with how
the question ended, whatever the ending: ``status`` is one of the five of ``agent.loop``,
and ``answer``, ``sql``, ``explanation`` and ``trace_id`` are there for every ending, empty
when there is nothing to put in them. A request that is not valid is a 422; a question
that could not be started, because the read-only user did not connect, is a 503 with a
reason that names no host, user or password.

Every question is one trace: a span ``agent.ask`` for the question, and under it a span for
every model call and every tool call. ``trace_id`` in the response is that trace's id, and
the spans go to ``agent.traces`` (a JSON Lines file under the data directory).

``create_app`` takes the pieces as arguments, so the tests build it with a scripted model
and canned tools. ``app_from_env`` is the one that uses the real ones, and it refuses to
start when the model key or the read-only user is not configured.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel, Field

from agent import budget, loop, traces, warehouse
from agent import llm as llm_module
from agent.llm import LLM, Response
from univ3_indexer import config

TRACER_NAME = "univ3.agent"
MAX_QUESTION_CHARS = 2000


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    max_usd: Decimal | None = Field(default=None, gt=0)


class Answer(BaseModel):
    trace_id: str
    status: str
    reason: str
    answer: object = None
    unit: str | None = None
    sql: str | None = None
    explanation: str | None = None
    refusal_reason: str | None = None
    usd: str
    iterations: int
    model: str


class TracedLLM:
    """The model, with a span around every call. Anything else is the model's own."""

    def __init__(self, inner: LLM, tracer: trace.Tracer):
        self._inner, self._tracer = inner, tracer
        self.model = inner.model

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def complete(self, **request: object) -> Response:
        with self._tracer.start_as_current_span("llm.complete") as span:
            span.set_attribute("llm.model", self.model)
            response = self._inner.complete(**request)
            span.set_attribute("llm.stop_reason", response.stop_reason)
            span.set_attribute("llm.input_tokens", response.usage.input_tokens)
            span.set_attribute("llm.output_tokens", response.usage.output_tokens)
            called = [b["name"] for b in response.content if b.get("type") == "tool_use"]
            span.set_attribute("llm.tool_calls", called)
            return response


class TracedTools:
    """The tools of one question, with a span around every call."""

    def __init__(self, inner: object, tracer: trace.Tracer):
        self._inner, self._tracer = inner, tracer

    @property
    def has_descriptions(self) -> bool:
        return bool(getattr(self._inner, "has_descriptions", False))

    def _traced(self, name: str, call: Callable[[], dict], **attributes: object) -> dict:
        with self._tracer.start_as_current_span(f"tool.{name}") as span:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
            output = call()
            span.set_attribute("tool.ok", bool(output.get("ok")))
            if output.get("ok") and "row_count" in output:
                span.set_attribute("tool.row_count", output["row_count"])
                span.set_attribute("tool.truncated", bool(output.get("truncated")))
            error = output.get("error")
            if isinstance(error, dict):
                span.set_attribute("tool.error_kind", str(error.get("kind", "")))
            return output

    def describe_schema(self, tables: list[str] | None = None) -> dict:
        return self._traced(
            "describe_schema",
            lambda: self._inner.describe_schema(tables),
            **{"tool.tables": list(tables) if tables else None},
        )

    def run_sql(self, sql: object) -> dict:
        return self._traced(
            "run_sql",
            lambda: self._inner.run_sql(sql),
            **{"db.statement": sql if isinstance(sql, str) else None},
        )


def create_app(
    house: warehouse.Warehouse,
    *,
    make_llm: Callable[[], LLM],
    make_tools: Callable[[], object],
    tracer_provider: TracerProvider,
    ledger: Path | None = None,
) -> FastAPI:
    """The service. ``make_llm`` and ``make_tools`` are called once per question.

    ``ledger`` is the budget's ledger file (``budget.default_ledger()`` in the real
    service); every question has a scope of its own in it, so one question's spending never
    counts against another's.
    """
    tracer = tracer_provider.get_tracer(TRACER_NAME)
    app = FastAPI(title="univ3 agent", docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/ask", response_model=Answer)
    def ask(request: Ask) -> Answer:
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="the question is empty")
        max_usd = request.max_usd if request.max_usd is not None else house.max_usd
        if max_usd > house.max_usd:
            raise HTTPException(
                status_code=422,
                detail=f"max_usd may not be more than {house.max_usd}, the warehouse limit",
            )
        with tracer.start_as_current_span("agent.ask") as span:
            trace_id = traces.trace_id_hex(span.get_span_context().trace_id)
            span.set_attribute("agent.question", question)
            span.set_attribute("agent.max_usd", str(max_usd))
            try:
                tools = make_tools()
            except Exception as problem:  # noqa: BLE001 - any connection failure ends here
                code = getattr(problem, "code", None)
                detail = f"ClickHouse error {code}" if code else type(problem).__name__
                span.set_attribute("agent.status", "unavailable")
                span.set_attribute("agent.reason", detail)
                raise HTTPException(
                    status_code=503,
                    detail=f"could not connect as the read-only user ({detail})",
                    headers={"x-trace-id": trace_id},
                ) from None
            model = make_llm()
            span.set_attribute("agent.model", model.model)
            purse = budget.DollarBudget(max_usd, ledger, scope=f"question:{uuid.uuid4()}")
            result = loop.run(
                question,
                TracedLLM(model, tracer),
                TracedTools(tools, tracer),
                purse,
                max_iterations=house.max_iterations,
                row_cap=house.row_cap,
            )
            span.set_attribute("agent.status", result.status)
            span.set_attribute("agent.reason", result.reason)
            span.set_attribute("agent.iterations", result.iterations)
            span.set_attribute("agent.usd", str(result.usd))
            span.set_attribute("agent.input_tokens", result.usage.input_tokens)
            span.set_attribute("agent.output_tokens", result.usage.output_tokens)
            if result.final_sql:
                span.set_attribute("agent.final_sql", result.final_sql)
        given = result.answer or {}
        return Answer(
            trace_id=trace_id,
            status=result.status,
            reason=result.reason,
            answer=given.get("value"),
            unit=given.get("unit"),
            sql=result.final_sql,
            explanation=given.get("explanation"),
            refusal_reason=given.get("refusal_reason"),
            usd=str(result.usd),
            iterations=result.iterations,
            model=result.model,
        )

    return app


def app_from_env(
    config_file: Path | None = None,
    model: str = llm_module.DEFAULT_MODEL,
    provider: str = llm_module.DEFAULT_PROVIDER,
) -> FastAPI:
    """The real service: the warehouse file, the read-only user and the model key.

    It stops before serving anything when one of them is missing: ``config.ConfigError``
    for the key or the user, ``warehouse.WarehouseError`` for the file. There is no other
    user, key or provider it falls back to.
    """
    from agent import __main__ as cli
    from agent import tools as tools_module

    house = warehouse.load(config_file or cli.DEFAULT_CONFIG)
    llm_module.price_of(model)
    llm_module.check_served_by(model, provider)
    config.load_agent_reader_config()
    chosen = llm_module.provider_of(provider)
    key = config.require_api_key(chosen.key_name)

    def make_llm() -> LLM:
        return llm_module.AnthropicLLM(key, model, provider=chosen.name)

    def make_tools() -> object:
        return tools_module.Tools(cli.connect_as_reader(house.database), house)

    return create_app(
        house,
        make_llm=make_llm,
        make_tools=make_tools,
        tracer_provider=traces.tracer_provider(traces.default_traces_file()),
        ledger=budget.default_ledger(),
    )
