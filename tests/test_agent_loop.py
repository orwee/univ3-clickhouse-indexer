"""The agent loop, driven by scripted conversations. No network, and mostly no server.

Each test is one question with a fixed list of model responses. The tools are a stand-in
that returns canned results, except in the last tests, which run the real tools against the
marts fixture and the command line end to end.
"""

import ast
import json
from decimal import Decimal

import pytest

from agent import __main__ as cli
from agent import budget, llm, loop, tools, warehouse
from evalkit import fixture
from univ3_indexer import config

AGENT_DIR = config.REPO_ROOT / "src" / "agent"
SCHEMA = {"ok": True, "database": "d", "tables": {"t": [{"name": "v", "type": "Decimal(76, 18)"}]}}
SMALL = llm.Usage(input_tokens=1000, output_tokens=100)  # $0.006 on the default model


def rows(*result_rows, columns=("v",)):
    return {
        "ok": True,
        "columns": [{"name": c, "type": "String"} for c in columns],
        "rows": [list(r) for r in result_rows],
        "row_count": len(result_rows),
        "truncated": False,
    }


def failed(message, code=47):
    return {"ok": False, "error": {"kind": "database", "code": code, "message": message}}


class FakeTools:
    """Answers describe_schema with SCHEMA and each run_sql with the next canned result."""

    def __init__(self, *results):
        self._results = list(results)
        self.sql: list[str] = []
        self.described: list = []

    def describe_schema(self, tables=None):
        self.described.append(tables)
        return SCHEMA

    def run_sql(self, sql):
        self.sql.append(sql)
        return self._results.pop(0)


def describe(usage=SMALL):
    return llm.response(llm.tool_use("describe_schema", {}), usage=usage)


def query(sql, usage=SMALL, id_=""):
    return llm.response(llm.tool_use("run_sql", {"sql": sql}, id_), usage=usage)


def submit(usage=SMALL, **fields):
    return llm.response(llm.tool_use("submit_answer", fields), usage=usage)


def ask(script, fake, max_usd="5", **options):
    model = llm.ScriptedLLM(script)
    purse = budget.DollarBudget(max_usd)
    return loop.run("How much?", model, fake, purse, **options), model, purse


# --- the paths of the loop ----------------------------------------------------------------


def test_the_direct_path_describe_query_submit():
    fake = FakeTools(rows(["5991906275.50882"]))
    script = [
        describe(),
        query("SELECT sum(v) AS v FROM t"),
        submit(
            type="number",
            value="5991906275.50882",
            unit="USD",
            sql="SELECT sum(v) AS v FROM t",
            explanation="The sum of v.",
        ),
    ]
    result, model, purse = ask(script, fake)
    assert result.status == "answered" and result.reason == ""
    assert result.answer == {
        "type": "number",
        "value": "5991906275.50882",
        "unit": "USD",
        "sql": "SELECT sum(v) AS v FROM t",
        "explanation": "The sum of v.",
        "refusal_reason": None,
    }
    assert result.final_sql == "SELECT sum(v) AS v FROM t" == fake.sql[0]
    assert result.iterations == 3 == len(model.calls)
    assert result.usage == llm.Usage(input_tokens=3000, output_tokens=300)
    assert result.usd == Decimal("0.018") == purse.spent  # 3 x (1000 x 4 + 100 x 20) / 1e6
    assert result.seconds >= 0
    assert [(c.iteration, c.name, c.summary) for c in result.tool_calls] == [
        (1, "describe_schema", {"ok": True, "tables": {"t": 1}}),
        (2, "run_sql", {"ok": True, "columns": ["v"], "row_count": 1, "truncated": False}),
        (3, "submit_answer", {"ok": True, "grounded": True}),
    ]
    json.dumps(result.to_json())


def test_what_the_model_is_sent():
    fake = FakeTools(rows(["1"]))
    script = [describe(), query("SELECT 1 AS v", id_="call_7"), submit(type="number", value="1")]
    _, model, _ = ask(script, fake, max_iterations=4, row_cap=50)
    first, second, third = model.calls
    assert first["messages"] == [{"role": "user", "content": "How much?"}]
    assert "at most 4 turns" in first["system"] and "At most 50 rows" in first["system"]
    assert "{{" not in first["system"]
    assert [t["name"] for t in first["tools"]] == ["describe_schema", "run_sql", "submit_answer"]
    assert first["tools"][2]["input_schema"]["properties"]["type"]["enum"] == list(
        loop.ANSWER_TYPES
    )
    assert set(first["tools"][2]["input_schema"]["properties"]) == set(loop.ANSWER_FIELDS)
    assert first["max_tokens"] == loop.DEFAULT_MAX_TOKENS
    # The second call carries the assistant turn and the schema as a tool result.
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert json.loads(second["messages"][2]["content"][0]["content"]) == SCHEMA
    last = third["messages"][-1]["content"]
    assert last[0]["tool_use_id"] == "call_7" and "is_error" not in last[0]
    assert json.loads(last[0]["content"])["rows"] == [["1"]]


def test_an_sql_error_followed_by_a_corrected_query():
    fake = FakeTools(failed("Unknown expression identifier `vv`"), rows(["42"]))
    script = [
        query("SELECT sum(vv) AS v FROM t"),
        query("SELECT sum(v) AS v FROM t"),
        submit(type="number", value=42, sql="SELECT sum(v) AS v FROM t"),
    ]
    result, model, _ = ask(script, fake)
    assert result.status == "answered" and result.final_sql == "SELECT sum(v) AS v FROM t"
    assert fake.sql == ["SELECT sum(vv) AS v FROM t", "SELECT sum(v) AS v FROM t"]
    assert result.tool_calls[0].summary == {
        "ok": False,
        "kind": "database",
        "code": 47,
        "message": "Unknown expression identifier `vv`",
    }
    # The error went back to the model as a tool result marked as an error, not as a crash.
    sent = model.calls[1]["messages"][-1]["content"][0]
    assert sent["is_error"] is True and "Unknown expression identifier" in sent["content"]


def test_at_the_iteration_cap_the_result_is_no_answer_never_a_guess():
    fake = FakeTools(*[rows([str(i)]) for i in range(6)])
    script = [query(f"SELECT {i} AS v") for i in range(6)]
    result, model, _ = ask(script, fake)
    assert result.status == "no_answer" and result.answer is None
    assert result.reason == "iteration_cap: 6 model calls without an answer"
    assert result.iterations == 6 == len(model.calls) == loop.DEFAULT_MAX_ITERATIONS
    assert result.final_sql == "SELECT 5 AS v"  # what ran is reported; no value is made of it

    result, model, _ = ask([describe(), describe(), describe()], FakeTools(), max_iterations=2)
    assert result.status == "no_answer" and len(model.calls) == 2


def test_the_budget_refuses_a_call_before_it_is_sent():
    """The first call's worst case is over eight cents of output alone: three cents never fit."""
    result, model, purse = ask([describe()], FakeTools(), max_usd="0.03")
    assert model.calls == []
    assert result.status == "no_answer" and result.reason.startswith("budget: a call that can cost")
    assert result.usd == 0 == purse.spent and result.iterations == 0


def test_the_budget_refuses_the_next_call_once_the_money_is_spent():
    heavy = llm.Usage(input_tokens=20_000, output_tokens=4_000)  # $0.16
    result, model, purse = ask([describe(heavy), describe()], FakeTools(), max_usd="0.25")
    assert len(model.calls) == 1 and result.iterations == 1
    assert result.status == "no_answer" and "$0.16 of $0.25 already spent" in result.reason
    assert result.usd == Decimal("0.16") == purse.spent


def test_every_call_is_booked_in_the_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    purse = budget.DollarBudget("1", ledger, scope="question:1")
    script = [describe(), submit(type="refusal", refusal_reason="No such column.")]
    loop.run("q", llm.ScriptedLLM(script), FakeTools(), purse)
    lines = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [(e["usd"], e["outcome"], e["note"]) for e in lines] == [
        ("0.006", "ok", "iteration 1"),
        ("0.006", "ok", "iteration 2"),
    ]
    assert lines[0]["details"]["model"] == llm.DEFAULT_MODEL
    assert lines[0]["details"]["input_tokens"] == 1000


def test_a_failed_model_call_is_booked_at_its_worst_case_and_ends_the_question(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    purse = budget.DollarBudget("1", ledger)
    model = llm.ScriptedLLM([describe(), llm.LLMError("_APITimeoutError")])
    result = loop.run("q", model, FakeTools(), purse)
    assert result.status == "no_answer" and result.reason == "llm_error: _APITimeoutError"
    assert result.iterations == 2 and len(model.calls) == 2  # one attempt, not retried
    booked = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [e["outcome"] for e in booked] == ["ok", "failed"]
    worst = Decimal(booked[1]["usd"])
    assert worst > Decimal("0.08192")  # the whole output cap, plus the input bound
    assert result.usd == Decimal("0.006") + worst == purse.spent

    result = loop.run(
        "q", llm.ScriptedLLM([ValueError("boom")]), FakeTools(), budget.DollarBudget("1")
    )
    assert result.reason == "llm_error: ValueError"


def test_a_refusal_ends_the_question_and_needs_no_result():
    script = [describe(), submit(type="refusal", refusal_reason="The table has no rows.")]
    result, _, _ = ask(script, FakeTools())
    assert result.status == "refused" and result.final_sql is None
    assert result.answer["type"] == "refusal" and result.answer["value"] is None
    assert result.answer["refusal_reason"] == "The table has no rows."


def test_a_refusal_without_a_reason_is_sent_back():
    script = [submit(type="refusal"), submit(type="refusal", refusal_reason="Not in the data.")]
    result, model, _ = ask(script, FakeTools())
    assert result.status == "refused" and result.iterations == 2
    sent = model.calls[1]["messages"][-1]["content"][0]
    assert sent["is_error"] is True and "refusal_reason" in sent["content"]
    assert result.tool_calls[0].summary["ok"] is False


def test_a_value_that_is_not_in_the_last_result_is_ungrounded():
    fake = FakeTools(rows(["41.5"], ["43"]))
    script = [query("SELECT v FROM t"), submit(type="number", value="42", sql="SELECT v FROM t")]
    result, _, _ = ask(script, fake)
    assert result.status == "ungrounded"
    assert result.reason == "the value is not a cell of the last result"
    assert result.answer["value"] == "42"  # kept, and flagged
    assert result.tool_calls[-1].summary == {"ok": True, "grounded": False}


def test_only_the_last_result_counts():
    fake = FakeTools(rows(["42"]), rows(["7"]))
    script = [query("SELECT 42 AS v"), query("SELECT 7 AS v"), submit(type="number", value="42")]
    assert ask(script, fake)[0].status == "ungrounded"
    # A failed query does not replace the last result that worked.
    fake = FakeTools(rows(["42"]), failed("boom"))
    script = [query("SELECT 42 AS v"), query("SELECT x"), submit(type="number", value="42")]
    result = ask(script, fake)[0]
    assert result.status == "answered" and result.final_sql == "SELECT 42 AS v"


def test_an_answer_with_no_query_at_all_is_ungrounded():
    result, _, _ = ask([submit(type="label", value="probably this")], FakeTools())
    assert result.status == "ungrounded" and result.final_sql is None


@pytest.mark.parametrize(
    ("cell", "value", "same"),
    [
        ("6.802048", "6.802048", True),
        ("6.802048", 6.802048, True),
        ("6.802048", "6.8020480", True),
        ("6.802048", "6.80", False),
        ("6.802048", 6.8, False),
        (1240618, "1240618", True),
        (1240618, 1240618.0, True),
        ("115792089237316195423570985008687907853269984665640564039457584007913129639935",
         "115792089237316195423570985008687907853269984665640564039457584007913129639935", True),
        ("115792089237316195423570985008687907853269984665640564039457584007913129639935",
         "115792089237316195423570985008687907853269984665640564039457584007913129639934", False),
        ("2026-08-19", "2026-08-19", True),
        ("2026-08-19", "2026-08-20", False),
        ("alpha", "alpha", True),
        ("alpha", "Alpha", False),
        (None, None, False),
        (None, "None", False),
        (True, 1, False),
        (0.5, "0.5", True),
        ("nan", "nan", True),
    ],
)  # fmt: skip
def test_what_counts_as_the_same_value(cell, value, same):
    assert loop.same_value(cell, value) is same


def test_a_list_is_grounded_when_every_element_is_a_cell():
    result_rows = [["a", 1], ["b", 2], ["c", 3]]
    assert loop.is_grounded("list", ["a", "c"], result_rows)
    assert loop.is_grounded("list", [1, "2", 3.0], result_rows)
    assert not loop.is_grounded("list", ["a", "z"], result_rows)
    assert not loop.is_grounded("list", [], result_rows)
    assert not loop.is_grounded("label", ["a", "b"], result_rows)
    assert loop.is_grounded("list", ["x", "y"], [[["x", "y"]]])  # an array cell, as a whole
    assert not loop.is_grounded("number", 1, None)
    assert not loop.is_grounded("number", 1, [])


def test_text_instead_of_a_tool_call_is_nudged_and_counts_as_a_turn():
    fake = FakeTools(rows(["3"]))
    script = [
        llm.response(llm.text("I think it is about three.")),
        query("SELECT 3 AS v"),
        submit(type="number", value="3"),
    ]
    result, model, _ = ask(script, fake)
    assert result.status == "answered" and result.iterations == 3
    assert model.calls[1]["messages"][-1] == {"role": "user", "content": loop.NUDGE}


@pytest.mark.parametrize("stop", ["refusal", "max_tokens", "pause_turn"])
def test_a_model_that_stops_for_another_reason_gives_no_answer(stop):
    script = [llm.response(llm.text("..."), stop_reason=stop), describe()]
    result, model, _ = ask(script, FakeTools())
    assert result.status == "no_answer" and result.reason == f"model_stop: {stop}"
    assert len(model.calls) == 1


@pytest.mark.parametrize(
    ("fields", "says"),
    [
        ({"type": "guess", "value": 1}, "type must be one of"),
        ({"type": "number"}, "needs a value"),
        ({"type": "number", "value": ""}, "needs a value"),
        ({"type": "list", "value": "a"}, "array of cells"),
        ({"type": "number", "value": [1, 2]}, "single cell"),
    ],
)
def test_a_malformed_answer_is_sent_back_and_costs_a_turn(fields, says):
    fake = FakeTools(rows(["1"]))
    script = [query("SELECT 1 AS v"), submit(**fields), submit(type="number", value="1")]
    result, model, _ = ask(script, fake)
    assert result.status == "answered" and result.iterations == 3
    sent = model.calls[2]["messages"][-1]["content"][0]
    assert sent["is_error"] is True and says in sent["content"]


def test_several_tool_calls_in_one_turn_go_back_in_one_message():
    fake = FakeTools(rows(["1"]), rows(["2"]))
    both = llm.response(
        llm.tool_use("run_sql", {"sql": "SELECT 1 AS v"}, "a"),
        llm.tool_use("run_sql", {"sql": "SELECT 2 AS v"}, "b"),
        llm.tool_use("made_up_tool", {}, "c"),
        usage=SMALL,
    )
    result, model, _ = ask([both, submit(type="number", value="2")], fake)
    back = model.calls[1]["messages"][-1]
    assert back["role"] == "user"
    assert [b["tool_use_id"] for b in back["content"]] == ["a", "b", "c"]
    assert back["content"][2]["is_error"] is True
    assert result.status == "answered" and result.final_sql == "SELECT 2 AS v"


def test_an_answer_in_the_same_turn_as_its_query_is_checked_against_that_query():
    fake = FakeTools(rows(["9"]))
    turn = llm.response(
        llm.tool_use("run_sql", {"sql": "SELECT 9 AS v"}, "a"),
        llm.tool_use("submit_answer", {"type": "number", "value": "9"}, "b"),
    )
    assert ask([turn], fake)[0].status == "answered"


# --- the command line ----------------------------------------------------------------------

INDEXER_ENV = {
    "CLICKHOUSE_DB": "onchain",
    "CLICKHOUSE_USER": "indexer",
    "CLICKHOUSE_PASSWORD": "not-the-indexer-password",
    "CH_HOST": "127.0.0.1",
    "CH_PORT": "8123",
}


@pytest.fixture
def no_reader(monkeypatch, tmp_path):
    """The writer's credentials are all there; the reader's file does not exist."""
    for name, value in INDEXER_ENV.items():
        monkeypatch.setenv(name, value)
    for name in config.AGENT_READER_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(config.AGENT_READER_POINTER, str(tmp_path / "absent-agent-reader.env"))
    monkeypatch.setenv(config.API_KEYS_POINTER, str(tmp_path / "absent-api-keys.env"))
    monkeypatch.delenv(cli.API_KEY_NAME, raising=False)
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(tmp_path / "data"))


def test_without_the_reader_the_command_says_so_and_never_falls_back_to_indexer(
    no_reader, monkeypatch, capsys
):
    def never(**kwargs):
        raise AssertionError(f"a connection was opened as {kwargs.get('username')}")

    monkeypatch.setattr(cli.clickhouse_connect, "get_client", never)
    used = []
    code = cli.main(["How much?"], make_llm=lambda model: used.append(model))
    captured = capsys.readouterr()
    assert code == cli.SETUP_ERROR == 2 and captured.out == ""
    assert "The read-only user is not available" in captured.err
    assert "absent-agent-reader.env" in captured.err and "file not found" in captured.err
    assert "connects as that user only" in captured.err
    assert used == []  # no model was even built
    assert "not-the-indexer-password" not in captured.err


def test_nothing_under_src_agent_can_load_the_writers_credentials():
    """Not a fallback that is switched off: the code to connect as anyone else is not there."""
    for path in AGENT_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute):
                assert node.attr != "load_clickhouse_config", path.name
        assert "CLICKHOUSE_" not in source, path.name
    assert "load_agent_reader_config" in (AGENT_DIR / "__main__.py").read_text()


def test_a_reader_that_cannot_log_in_stops_the_command(no_reader, monkeypatch, capsys):
    for name, value in zip(
        config.AGENT_READER_NAMES.values(),
        ("127.0.0.1", "8123", "onchain_dbt", "agent_reader", "wrong"),
        strict=True,
    ):
        monkeypatch.setenv(name, value)

    class Refused(Exception):
        code = 516

    def refuse(**kwargs):
        assert kwargs["username"] == "agent_reader" and kwargs["database"] == "onchain_dbt"
        raise Refused("Authentication failed: password is incorrect")

    monkeypatch.setattr(cli.clickhouse_connect, "get_client", refuse)
    assert cli.main(["q"], make_llm=lambda model: None) == 2
    err = capsys.readouterr().err
    assert "Could not connect as the read-only user (ClickHouse error 516)" in err
    assert "wrong" not in err.replace("wrong with", "")


def test_the_reader_must_be_for_the_database_of_the_warehouse_file(no_reader, monkeypatch, capsys):
    for name, value in zip(
        config.AGENT_READER_NAMES.values(),
        ("127.0.0.1", "8123", "onchain", "agent_reader", "secret-value"),
        strict=True,
    ):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cli.clickhouse_connect, "get_client", lambda **kw: pytest.fail("connected"))
    assert cli.main(["q"]) == 2
    err = capsys.readouterr().err
    assert "names the database onchain, the warehouse file onchain_dbt" in err
    assert "secret-value" not in err


def test_a_model_without_a_price_is_refused_before_anything_else(no_reader, capsys):
    assert cli.main(["q", "--model", "claude-placeholder-0"]) == 2
    err = capsys.readouterr().err
    assert "no price is recorded for model 'claude-placeholder-0'" in err
    assert "read-only user" not in err


def test_without_a_key_the_command_says_which_variable_is_missing(no_reader, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_connect_as_reader", lambda database: object())
    assert cli.main(["q"]) == 2
    err = capsys.readouterr().err
    assert "No model key: ANTHROPIC_API_KEY is not set" in err
    assert "ANTHROPIC_API_KEY" in config.API_KEY_NAMES


def test_bad_arguments_stop_the_command(no_reader, tmp_path, capsys):
    assert cli.main(["q", "--max-usd", "a lot"]) == 2
    assert "--max-usd must be a number" in capsys.readouterr().err
    assert cli.main(["q", "--config", str(tmp_path / "absent.yml")]) == 2
    assert "file not found" in capsys.readouterr().err


# --- the real tools and the whole command, on the marts fixture ----------------------------


@pytest.fixture
def fixture_setup(clickhouse, marts_database, monkeypatch, tmp_path):
    """A warehouse file for the fixture database, and reader variables that reach it.

    The real server has no read-only user, so for this test only the reader variables carry
    the test connection's own credentials. What is exercised is the command's plumbing, not
    the grants: those are checked in tests/test_agent_reader.py and in `make demo`.
    """
    real = config.load_clickhouse_config()
    values = (real.host, str(real.port), marts_database, real.user, real.password)
    for name, value in zip(config.AGENT_READER_NAMES.values(), values, strict=True):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(tmp_path / "data"))
    path = tmp_path / "warehouse.yml"
    path.write_text(
        f"database: {marts_database}\n"
        f"tables: [{', '.join(fixture.TABLES)}]\n"
        "limits: {row_cap: 50, max_iterations: 6, max_usd: 0.5}\n"
    )
    return path


def test_a_scripted_question_end_to_end_on_the_fixture(fixture_setup, capsys, tmp_path):
    total = fixture.read_fingerprint()["tables"]["fct_pool_daily"]["sum_volume_usd"]
    sql = "SELECT sum(volume_usd) AS total FROM fct_pool_daily"
    script = [
        describe(),
        query("SELECT sum(volume) FROM fct_pool_daily"),  # a column that does not exist
        query(sql),
        submit(type="number", value=total, unit="USD", sql=sql, explanation="All volume."),
    ]
    scripted = llm.ScriptedLLM(script)
    code = cli.main(["What is the total?", "--config", str(fixture_setup), "--json"],
                    make_llm=lambda model: scripted)  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "answered"
    assert out["answer"]["value"] == total and out["final_sql"] == sql
    assert [c["summary"]["ok"] for c in out["tool_calls"]] == [True, False, True, True]
    assert out["tool_calls"][1]["summary"]["code"] == 47
    assert out["usd"] == "0.024" and out["iterations"] == 4
    # The schema the model saw is the fixture's, names and types.
    schema = json.loads(scripted.calls[1]["messages"][2]["content"][0]["content"])
    assert list(schema["tables"]) == list(fixture.TABLES)
    ledger = tmp_path / "data" / "agent" / "ledger.jsonl"
    booked = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(booked) == 4 and all(e["scope"].startswith("question:") for e in booked)


def test_the_plain_output_has_the_answer_the_sql_and_the_cost(fixture_setup, capsys):
    sql = "SELECT count() AS n FROM dim_pools"
    script = [query(sql), submit(type="number", value=4, unit="rows", sql=sql, explanation="Rows.")]
    code = cli.main(["How many?", "--config", str(fixture_setup)],
                    make_llm=lambda model: llm.ScriptedLLM(script))  # fmt: skip
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[0] == "Answer: 4 rows" and out[1] == "Explanation: Rows." and out[2] == f"SQL: {sql}"
    assert out[3].startswith("Cost: $0.012 (2,000 input and 200 output tokens, 2 model calls, ")
    assert out[3].endswith(f"{llm.DEFAULT_MODEL})")


def test_a_question_the_empty_table_cannot_answer_ends_in_a_refusal(fixture_setup, capsys):
    sql = "SELECT count() AS n FROM fct_pool_daily_smart_money"
    script = [query(sql), submit(type="refusal", refusal_reason="The table has no rows.")]
    code = cli.main(["q", "--config", str(fixture_setup)],
                    make_llm=lambda model: llm.ScriptedLLM(script))  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and out.startswith("Refused: The table has no rows.")


def test_no_answer_and_ungrounded_exit_with_one(fixture_setup, capsys):
    script = [query("SELECT 1 AS n"), submit(type="number", value=2)]
    code = cli.main(["q", "--config", str(fixture_setup)],
                    make_llm=lambda model: llm.ScriptedLLM(script))  # fmt: skip
    assert code == 1 and capsys.readouterr().out.startswith("UNGROUNDED, do not trust: 2")
    code = cli.main(["q", "--config", str(fixture_setup), "--max-usd", "0.01"],
                    make_llm=lambda model: llm.ScriptedLLM([describe()]))  # fmt: skip
    assert code == 1 and capsys.readouterr().out.startswith("No answer: budget:")


def test_the_real_tools_in_the_loop(clickhouse, marts_database):
    from univ3_indexer import clickhouse as ch

    house = warehouse.Warehouse(marts_database, fixture.TABLES, 3, 6, Decimal("1"))
    kit = tools.Tools(ch.connect(database=marts_database), house)
    script = [
        query("SELECT block_date FROM fct_pool_daily ORDER BY block_date DESC, pool_address"),
        submit(type="date", value="2026-09-25"),
    ]
    result = loop.run(
        "Last day?", llm.ScriptedLLM(script), kit, budget.DollarBudget("1"), row_cap=3
    )
    assert result.status == "answered"
    assert result.tool_calls[0].summary["truncated"] is True
    assert result.tool_calls[0].summary["row_count"] == 3
