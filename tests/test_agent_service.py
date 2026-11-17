"""The HTTP service and its traces, driven with a scripted model and canned tools.

No server, no network, no key: FastAPI's ``TestClient`` calls the app in the process, the
model is ``llm.ScriptedLLM`` and the tools return canned results. The traces go to a file
under ``tmp_path``.
"""

import json
import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from agent import __main__ as cli
from agent import budget, llm, service, traces, warehouse
from univ3_indexer import config

OPUS = "claude-opus-5-5"
SMALL = llm.Usage(input_tokens=1000, output_tokens=100)  # $0.006 on OPUS
HOUSE = warehouse.Warehouse(
    database="d", tables=("t",), row_cap=200, max_iterations=6, max_usd=Decimal("0.25")
)
SCHEMA = {"ok": True, "database": "d", "tables": {"t": [{"name": "v", "type": "UInt64"}]}}
SQL = "SELECT count() AS v FROM t"
HEX32 = re.compile(r"[0-9a-f]{32}")


def rows(*values):
    return {
        "ok": True,
        "columns": [{"name": "v", "type": "UInt64"}],
        "rows": [[v] for v in values],
        "row_count": len(values),
        "truncated": False,
    }


class FakeTools:
    def __init__(self, *results):
        self._results = list(results)
        self.sql = []

    def describe_schema(self, tables=None):
        return SCHEMA

    def run_sql(self, sql):
        self.sql.append(sql)
        return self._results.pop(0)


def describe():
    return llm.response(llm.tool_use("describe_schema", {}), usage=SMALL)


def query(sql=SQL):
    return llm.response(llm.tool_use("run_sql", {"sql": sql}), usage=SMALL)


def submit(**fields):
    return llm.response(llm.tool_use("submit_answer", fields), usage=SMALL)


ANSWERED = [
    describe(),
    query(),
    submit(type="number", value="42", unit="rows", sql=SQL, explanation="The rows of t."),
]


class Service:
    """The app, built with one script and one set of tools per question, in order."""

    def __init__(self, tmp_path, scripts, tools, ledger=None):
        self.scripts, self.tools = list(scripts), list(tools)
        self.models = []
        self.traces_file = tmp_path / "data" / "agent" / traces.TRACES_NAME

        def make_llm():
            model = llm.ScriptedLLM(self.scripts.pop(0), OPUS)
            self.models.append(model)
            return model

        def make_tools():
            tool = self.tools.pop(0)
            if isinstance(tool, Exception):
                raise tool
            return tool

        self.app = service.create_app(
            HOUSE,
            make_llm=make_llm,
            make_tools=make_tools,
            tracer_provider=traces.tracer_provider(self.traces_file),
            ledger=ledger,
        )
        self.client = TestClient(self.app)

    def ask(self, **body):
        return self.client.post("/ask", json=body)

    def spans(self):
        if not self.traces_file.exists():
            return []
        lines = self.traces_file.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]


def test_an_answered_question_returns_the_answer_the_sql_the_explanation_and_the_trace_id(
    tmp_path,
):
    tools = FakeTools(rows(42))
    app = Service(tmp_path, [ANSWERED], [tools])
    response = app.ask(question="How many rows does t have?")
    assert response.status_code == 200
    body = response.json()
    assert HEX32.fullmatch(body["trace_id"])
    assert {k: body[k] for k in ("status", "answer", "unit", "sql", "explanation")} == {
        "status": "answered",
        "answer": "42",
        "unit": "rows",
        "sql": SQL,
        "explanation": "The rows of t.",
    }
    assert body["reason"] == "" and body["refusal_reason"] is None
    assert body["usd"] == "0.018" and body["iterations"] == 3 and body["model"] == OPUS
    assert tools.sql == [SQL]
    assert app.models[0].calls[0]["messages"] == [
        {"role": "user", "content": "How many rows does t have?"}
    ]


def test_one_question_is_one_trace_with_a_span_for_every_model_and_tool_call(tmp_path):
    app = Service(tmp_path, [ANSWERED], [FakeTools(rows(42))])
    trace_id = app.ask(question="How many rows does t have?").json()["trace_id"]
    spans = app.spans()
    assert {s["trace_id"] for s in spans} == {trace_id}
    by_name = {}
    for span in spans:
        by_name.setdefault(span["name"], []).append(span)
    assert sorted(by_name) == ["agent.ask", "llm.complete", "tool.describe_schema", "tool.run_sql"]
    (root,) = by_name["agent.ask"]
    assert root["parent_id"] is None
    assert all(s["parent_id"] == root["span_id"] for s in spans if s is not root)
    assert len(by_name["llm.complete"]) == 3
    assert [s["attributes"]["llm.tool_calls"] for s in by_name["llm.complete"]] == [
        ["describe_schema"],
        ["run_sql"],
        ["submit_answer"],
    ]
    (sql_span,) = by_name["tool.run_sql"]
    assert sql_span["attributes"] == {
        "db.statement": SQL,
        "tool.ok": True,
        "tool.row_count": 1,
        "tool.truncated": False,
    }
    attributes = root["attributes"]
    assert attributes["agent.question"] == "How many rows does t have?"
    assert attributes["agent.status"] == "answered" and attributes["agent.usd"] == "0.018"
    assert attributes["agent.iterations"] == 3 and attributes["agent.final_sql"] == SQL
    assert root["status"] == "UNSET" and root["seconds"] >= 0
    assert all(s["start"] <= s["end"] for s in spans)


def test_two_questions_are_two_traces_each_with_a_model_and_tools_of_its_own(tmp_path):
    refusal = [describe(), submit(type="refusal", refusal_reason="The data has no prices.")]
    app = Service(tmp_path, [ANSWERED, refusal], [FakeTools(rows(42)), FakeTools()])
    first = app.ask(question="How many rows does t have?").json()
    second = app.ask(question="What will the price be tomorrow?").json()
    assert first["trace_id"] != second["trace_id"]
    assert second["status"] == "refused"
    assert second["refusal_reason"] == "The data has no prices."
    assert second["answer"] is None and second["sql"] is None
    assert len(app.models) == 2 and len(app.models[1].calls) == 2
    roots = [s for s in app.spans() if s["name"] == "agent.ask"]
    assert [r["trace_id"] for r in roots] == [first["trace_id"], second["trace_id"]]


def test_a_question_with_no_answer_is_still_a_200_with_its_reason(tmp_path):
    app = Service(tmp_path, [[describe()] * HOUSE.max_iterations], [FakeTools()])
    body = app.ask(question="How many?").json()
    assert body["status"] == "no_answer" and body["reason"].startswith("iteration_cap")
    assert body["answer"] is None and body["sql"] is None and HEX32.fullmatch(body["trace_id"])


@pytest.mark.parametrize(
    "body",
    [{}, {"question": ""}, {"question": "   "}, {"question": "x" * 2001}, {"max_usd": "0.1"}],
)
def test_a_request_that_is_not_valid_is_a_422_and_no_model_is_built(tmp_path, body):
    app = Service(tmp_path, [ANSWERED], [FakeTools(rows(42))])
    assert app.ask(**body).status_code == 422
    assert app.models == [] and app.spans() == []


@pytest.mark.parametrize("max_usd", ["0", "-1", "0.26", "1"])
def test_max_usd_must_be_positive_and_at_most_the_warehouse_limit(tmp_path, max_usd):
    app = Service(tmp_path, [ANSWERED], [FakeTools(rows(42))])
    response = app.ask(question="How many?", max_usd=max_usd)
    assert response.status_code == 422
    assert app.models == []


def test_a_max_usd_too_small_for_one_call_ends_in_error_and_nothing_is_sent(tmp_path):
    app = Service(tmp_path, [ANSWERED], [FakeTools(rows(42))])
    body = app.ask(question="How many?", max_usd="0.0001").json()
    assert body["status"] == "error" and body["reason"].startswith("budget:")
    assert app.models[0].calls == [] and body["usd"] == "0"
    assert [s["name"] for s in app.spans()] == ["agent.ask"]


def test_each_question_has_a_scope_of_its_own_in_the_ledger(tmp_path):
    ledger = tmp_path / "data" / "agent" / budget.LEDGER_NAME
    tools = [FakeTools(rows(42)), FakeTools(rows(42))]
    app = Service(tmp_path, [ANSWERED, list(ANSWERED)], tools, ledger=ledger)
    first = app.ask(question="How many?").json()
    second = app.ask(question="How many?").json()
    assert first["status"] == second["status"] == "answered"
    entries = [json.loads(line) for line in ledger.read_text().splitlines()]
    scopes = [e["scope"] for e in entries]
    assert len(entries) == 6 and len(set(scopes)) == 2
    assert all(s.startswith("question:") for s in scopes)
    assert sum(Decimal(e["usd"]) for e in entries) == Decimal("0.036")


def test_when_the_reader_does_not_connect_it_is_a_503_that_names_no_credential(tmp_path):
    class Refused(Exception):
        code = 516

    secret = "password=not-a-real-password host=db.example"
    app = Service(tmp_path, [ANSWERED], [Refused(secret)])
    response = app.ask(question="How many?")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "could not connect as the read-only user (ClickHouse error 516)"
    }
    assert "not-a-real-password" not in response.text and "example" not in response.text
    assert app.models == []
    (root,) = app.spans()
    assert root["attributes"]["agent.status"] == "unavailable"
    assert root["trace_id"] == response.headers["x-trace-id"]
    assert "not-a-real-password" not in app.traces_file.read_text()


def test_the_exporter_writes_one_line_per_span_and_creates_the_directory(tmp_path):
    path = tmp_path / "a" / "b" / "traces.jsonl"
    provider = traces.tracer_provider(path)
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("outer") as outer:
        outer.add_event("seen", {"n": 1})
        with tracer.start_as_current_span("inner"):
            pass
    inner, outer_line = (json.loads(line) for line in path.read_text().splitlines())
    assert inner["name"] == "inner" and outer_line["name"] == "outer"
    assert inner["parent_id"] == outer_line["span_id"] and outer_line["parent_id"] is None
    assert inner["trace_id"] == outer_line["trace_id"]
    assert outer_line["events"][0]["name"] == "seen" and outer_line["events"][0]["n"] == 1
    assert HEX32.fullmatch(inner["trace_id"]) and re.fullmatch(r"[0-9a-f]{16}", inner["span_id"])


def test_the_traces_go_under_the_data_directory_never_inside_the_repo(monkeypatch, tmp_path):
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(tmp_path / "data"))
    assert traces.default_traces_file() == (tmp_path / "data" / "agent" / "traces.jsonl")
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(config.REPO_ROOT / "traces"))
    with pytest.raises(config.ConfigError):
        traces.default_traces_file()


@pytest.fixture
def nothing_configured(monkeypatch, tmp_path):
    for name in config.AGENT_READER_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(config.AGENT_READER_POINTER, str(tmp_path / "absent-agent-reader.env"))
    monkeypatch.setenv(config.API_KEYS_POINTER, str(tmp_path / "absent-api-keys.env"))
    monkeypatch.delenv(cli.API_KEY_NAME, raising=False)
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(tmp_path / "data"))


def test_the_real_service_does_not_start_without_the_read_only_user(nothing_configured):
    with pytest.raises(config.ConfigError, match="absent-agent-reader.env"):
        service.app_from_env()


def test_the_real_service_does_not_start_without_the_model_key(nothing_configured, monkeypatch):
    for name, value in zip(
        config.AGENT_READER_NAMES.values(),
        ("127.0.0.1", "8123", "onchain_dbt", "agent_reader", "not-a-real-password"),
        strict=True,
    ):
        monkeypatch.setenv(name, value)
    with pytest.raises(config.ConfigError, match=cli.API_KEY_NAME):
        service.app_from_env()
