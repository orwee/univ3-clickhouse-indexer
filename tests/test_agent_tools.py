"""The agent's two tools, against the marts fixture loaded into a throw-away database.

Also the two things that keep the package generic: its only domain file is a YAML under
evals/, and nothing under src/agent/ names this project's domain or imports its code.
"""

import ast
import datetime
import json
import re
from decimal import Decimal

import pytest

from agent import tools, warehouse
from evalkit import fixture
from univ3_indexer import agent_reader, config
from univ3_indexer import clickhouse as ch

AGENT_DIR = config.REPO_ROOT / "src" / "agent"
LIMITS = "database: d\ntables: [a]\nlimits: {row_cap: 1, max_iterations: 1, max_usd: 1}\n"
WAREHOUSE_YML = config.REPO_ROOT / "evals" / "warehouse.yml"
DOMAIN_WORDS = ("uniswap", "swap", "pool", "usdc", "weth")

# --- no server needed ------------------------------------------------------------------


def test_nothing_under_src_agent_knows_this_projects_domain():
    """No domain word in any case, in any file: code, prompts, anything."""
    files = [p for p in AGENT_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert any(p.suffix == ".py" for p in files)
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        found = [word for word in DOMAIN_WORDS if word in text]
        assert not found, f"{path.relative_to(config.REPO_ROOT)} mentions {found}"


def test_the_prompt_names_no_table_and_no_limit_of_this_warehouse():
    """It says a result too large for the server is an error, without saying how large."""
    prompt = (AGENT_DIR / "prompts" / "system.md").read_text()
    assert "A result too large for the server comes back as an error, not as a cut result" in prompt
    assert "aggregate or to add LIMIT" in prompt
    for table in warehouse.load(WAREHOUSE_YML).tables:
        assert table not in prompt
    for number in ("396", "10,000", "10000", "200", "0.25"):
        assert number not in prompt, number
    assert re.findall(r"\{\{(\w+)\}\}", prompt) == ["descriptions", "row_cap", "max_iterations"]


def test_the_prompt_says_what_a_missing_day_is_from_the_coverage_and_writes_no_date():
    """The rule on days with no row reads the dates from describe_schema, not from the text:
    the data grows by a day every day and a date written here would go stale."""
    prompt = (AGENT_DIR / "prompts" / "system.md").read_text()
    assert "## Days with no row" in prompt
    for field in ("`coverage`", "`first`", "`last`", "`keys_from`", "`table`"):
        assert field in prompt, field
    assert "Answer 0; do not refuse." in prompt
    assert "refuse, and say why" in prompt
    assert not re.search(r"\b(19|20)\d\d-\d\d-\d\d\b", prompt)
    assert not re.search(r"\b(19|20)\d\d\b", prompt)


def test_src_agent_imports_nothing_of_the_indexer_but_its_config():
    for path in AGENT_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("univ3_indexer"):
                assert node.module == "univ3_indexer" and [a.name for a in node.names] == ["config"]
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("univ3_indexer"), path.name
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("evalkit"), path.name


def test_the_warehouse_file_names_the_tables_the_reader_is_granted():
    w = warehouse.load(WAREHOUSE_YML)
    granted = agent_reader.definition()
    assert w.database == granted.database
    assert w.tables == granted.tables == fixture.TABLES
    assert (w.row_cap, w.max_iterations, w.max_usd) == (200, 6, Decimal("0.25"))
    assert w.row_cap <= int(granted.settings["max_result_rows"])
    assert w.coverage == warehouse.Coverage("fct_pool_daily", "block_date", "dim_pools")
    assert w.coverage.column in fixture.read_table(w.coverage.table).columns


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("tables: [a]\nlimits: {row_cap: 1, max_iterations: 1, max_usd: 1}", "the database"),
        ("database: d\nlimits: {row_cap: 1, max_iterations: 1, max_usd: 1}", "'tables'"),
        ("database: d\ntables: ['a; DROP']\nlimits: {}", "a table name"),
        (
            "database: d\ntables: [a, a]\nlimits: {row_cap: 1, max_iterations: 1, max_usd: 1}",
            "twice",
        ),
        ("database: d\ntables: [a]", "'limits'"),
        (
            "database: d\ntables: [a]\nlimits: {row_cap: 0, max_iterations: 1, max_usd: 1}",
            "row_cap",
        ),
        (
            "database: d\ntables: [a]\nlimits: {row_cap: 1, max_iterations: true, max_usd: 1}",
            "max_it",
        ),
        (
            "database: d\ntables: [a]\nlimits: {row_cap: 1, max_iterations: 1, max_usd: -1}",
            "max_usd",
        ),
        (
            "database: d\ntables: [a]\nlimits: {row_cap: 1, max_iterations: 1, max_usd: x}",
            "max_usd",
        ),
        ("- just\n- a list", "mapping"),
        (LIMITS + "coverage: {table: a, column: d}", "keys_from"),
        (LIMITS + "coverage: {table: a, column: d, keys_from: a, more: 1}", "keys_from"),
        (LIMITS + "coverage: {table: b, column: d, keys_from: a}", "names b"),
        (LIMITS + "coverage: {table: a, column: d, keys_from: b}", "names b"),
        (LIMITS + "coverage: {table: a, column: 'd; DROP', keys_from: a}", "coverage.column"),
        (LIMITS + "coverage: [a]", "'coverage'"),
    ],
)
def test_a_warehouse_file_that_is_not_names_and_limits_is_refused(tmp_path, text, says):
    path = tmp_path / "warehouse.yml"
    path.write_text(text)
    with pytest.raises(warehouse.WarehouseError, match=re.escape(says)):
        warehouse.load(path)
    with pytest.raises(warehouse.WarehouseError, match="file not found"):
        warehouse.load(tmp_path / "absent.yml")


def test_json_safe_keeps_every_digit():
    big = Decimal("1234567890123456789012345678901234567890123456789012345678.123456789012345678")
    assert Decimal(tools.json_safe(big)) == big
    assert tools.json_safe(Decimal("6.802048000000000000")) == "6.802048"
    assert tools.json_safe(Decimal("0E-18")) == "0"
    assert tools.json_safe(Decimal("-0.000")) == "0"
    assert tools.json_safe(Decimal("100")) == "100"
    assert tools.json_safe(Decimal("1E+3")) == "1000"
    assert tools.json_safe(2**53 - 1) == 2**53 - 1
    assert tools.json_safe(2**53) == str(2**53)
    assert tools.json_safe(-(2**255)) == str(-(2**255))
    assert tools.json_safe(datetime.date(2026, 9, 25)) == "2026-09-25"
    assert tools.json_safe(datetime.datetime(2026, 9, 25, 1, 2, 3)) == "2026-09-25T01:02:03"
    assert tools.json_safe(float("nan")) == "nan" and tools.json_safe(1.5) == 1.5
    assert tools.json_safe(b"\xff\x00") == "0xff00" and tools.json_safe(b"abc") == "abc"
    assert tools.json_safe([Decimal("1.50"), (None, True)]) == ["1.5", [None, True]]
    json.dumps(tools.json_safe({"k": [Decimal("1"), datetime.date(2026, 1, 1), 2**70]}))


# --- against the server ----------------------------------------------------------------


@pytest.fixture(scope="module")
def loaded(clickhouse):
    """The marts fixture in a `test_*` database, and a client whose default database it is."""
    import uuid

    database = f"test_{uuid.uuid4().hex[:12]}"
    clickhouse.command(f"CREATE DATABASE {database}")
    try:
        fixture.load(clickhouse, database)
        yield database, ch.connect(database=database)
    finally:
        clickhouse.command(f"DROP DATABASE IF EXISTS {database}")


@pytest.fixture
def kit(loaded):
    database, client = loaded
    real = warehouse.load(WAREHOUSE_YML)
    w = warehouse.Warehouse(database, real.tables, 5, real.max_iterations, real.max_usd)
    return tools.Tools(client, w)


def test_describe_schema_gives_names_and_types_and_nothing_else(kit, loaded):
    out = kit.describe_schema()
    assert out["ok"] and out["database"] == loaded[0]
    assert tuple(out["tables"]) == fixture.TABLES
    for name in fixture.TABLES:
        table = fixture.read_table(name)
        expected = [{"name": c, "type": t} for c, t in zip(table.columns, table.types, strict=True)]
        assert out["tables"][name] == expected
    json.dumps(out)


def test_describe_schema_returns_the_descriptions_it_was_given_next_to_names_and_types(loaded):
    """What the descriptions say and where they were written is the caller's business."""
    database, client = loaded
    real = warehouse.load(WAREHOUSE_YML)
    house = warehouse.Warehouse(database, real.tables, 5, real.max_iterations, real.max_usd)
    plain = tools.Tools(client, house)
    assert plain.has_descriptions is False
    given = {
        "dim_pools": {"description": "One row per thing.", "columns": {"pool_label": "Its name."}},
        "fct_pool_daily": {"columns": {"swaps": "How many.", "no_such_column": "Ignored."}},
        "no_such_table": {"description": "Ignored."},
    }
    kit = tools.Tools(client, house, given)
    assert kit.has_descriptions is True
    out, bare = kit.describe_schema(), plain.describe_schema()
    assert out["descriptions"] == {"dim_pools": "One row per thing."} and "descriptions" not in bare
    with_text = {
        (table, column["name"]): column["description"]
        for table, columns in out["tables"].items()
        for column in columns
        if "description" in column
    }
    assert with_text == {
        ("dim_pools", "pool_label"): "Its name.",
        ("fct_pool_daily", "swaps"): "How many.",
    }
    # Names and types are what they were without descriptions.
    strip = lambda columns: [{"name": c["name"], "type": c["type"]} for c in columns]  # noqa: E731
    assert {t: strip(c) for t, c in out["tables"].items()} == bare["tables"]
    assert "descriptions" not in kit.describe_schema(["fct_pool_daily"])
    json.dumps(out)


def covered(loaded, table="fct_pool_daily"):
    database, client = loaded
    real = warehouse.load(WAREHOUSE_YML)
    cover = warehouse.Coverage(table, real.coverage.column, real.coverage.keys_from)
    house = warehouse.Warehouse(database, real.tables, 5, 6, Decimal("1"), cover)
    return tools.Tools(client, house)


def test_describe_schema_reports_the_coverage_of_the_data_whatever_tables_were_asked(loaded):
    table = fixture.read_table("fct_pool_daily")
    dates = [row[table.columns.index("block_date")] for row in table.rows]
    kit = covered(loaded)
    for asked in (None, ["dim_pools"]):
        out = kit.describe_schema(asked)
        assert out["coverage"] == {
            "table": "fct_pool_daily",
            "column": "block_date",
            "first": min(dates),
            "last": max(dates),
            "keys_from": "dim_pools",
            "partial_days": tools.PARTIAL_DAYS,
        }
        json.dumps(out)
    # Without a coverage in the warehouse there is none in the output.
    database, client = loaded
    plain = tools.Tools(client, warehouse.Warehouse(database, fixture.TABLES, 5, 6, Decimal("1")))
    assert "coverage" not in plain.describe_schema()


def test_the_coverage_is_computed_when_describe_schema_is_called(loaded):
    """A day loaded after the first call is in the second: nothing holds a date."""
    database, client = loaded
    kit = covered(loaded)
    before = kit.describe_schema()["coverage"]
    later = datetime.date.fromisoformat(before["last"]) + datetime.timedelta(days=3)
    client.command(
        f"INSERT INTO {database}.fct_pool_daily (pool_address, block_date, pool_label, fee, swaps, "
        f"volume_token0, volume_token1) VALUES ('0xabab', '{later.isoformat()}', 'x', 1, 1, 0, 0)"
    )
    after = kit.describe_schema()["coverage"]
    assert (after["first"], after["last"]) == (before["first"], later.isoformat())


def test_the_coverage_of_a_table_with_no_rows_has_no_dates(loaded):
    """min() of no rows is 1970-01-01 in ClickHouse; it must not come back as a date."""
    out = covered(loaded, "fct_pool_daily_smart_money").describe_schema()
    assert out["coverage"]["first"] is None and out["coverage"]["last"] is None
    assert out["coverage"]["partial_days"] == "The table has no rows."


def test_describe_schema_of_some_tables_and_of_one_that_is_not_listed(kit):
    out = kit.describe_schema(["dim_pools"])
    assert list(out["tables"]) == ["dim_pools"]
    out = kit.describe_schema(["dim_pools", "raw_swaps"])
    assert out == {
        "ok": False,
        "error": {
            "kind": "unknown_table",
            "message": "Not in the schema: raw_swaps. The tables are: "
            + ", ".join(fixture.TABLES)
            + ".",
        },
    }


def test_run_sql_returns_rows_as_json_safe_values(kit):
    out = kit.run_sql(
        "SELECT pool_address, block_date, swaps, volume_usd FROM fct_pool_daily "
        "ORDER BY pool_address, block_date LIMIT 3"
    )
    assert out["ok"] and out["row_count"] == 3 and out["truncated"] is False
    assert [c["type"] for c in out["columns"]] == [
        "LowCardinality(String)",
        "Date",
        "UInt64",
        "Nullable(Decimal(76, 18))",
    ]
    table = fixture.read_table("fct_pool_daily")
    for got, row in zip(out["rows"], table.rows, strict=False):
        assert got[0] == row[0] and got[1] == row[1]  # the date in ISO form, as in the file
        assert got[2] == int(row[4]) and isinstance(got[2], int)
        assert isinstance(got[3], str) and Decimal(got[3]) == Decimal(row[7])
    assert json.loads(json.dumps(out)) == out


def test_decimal256_and_256_bit_integers_round_trip_exactly(kit):
    """Every volume_usd of the fixture, a sum of them, and the extremes of the wide types."""
    out = kit.run_sql("SELECT sum(volume_usd), max(swaps) FROM fct_pool_daily")
    recorded = fixture.read_fingerprint()["tables"]["fct_pool_daily"]["sum_volume_usd"]
    assert out["rows"][0][0] == recorded and isinstance(out["rows"][0][1], int)

    table = fixture.read_table("fct_round_trip_legs")
    wanted = [Decimal(v) for v in table.column("volume_usd")[:5]]
    out = kit.run_sql(
        "SELECT volume_usd FROM fct_round_trip_legs ORDER BY pool_address, block_number, "
        "log_index LIMIT 5"
    )
    assert [Decimal(row[0]) for row in out["rows"]] == wanted

    digits = "1234567890123456789012345678901234567890123456789012345678.123456789012345678"
    max_u256, min_i256 = str(2**256 - 1), str(-(2**255))
    out = kit.run_sql(
        f"SELECT toDecimal256('{digits}', 18) AS d, toDecimal256('-0.000000000000000001', 18), "
        f"toUInt256('{max_u256}') AS u, toInt256('{min_i256}') AS i, toUInt256(7) AS small, "
        "toUInt64(18446744073709551615) AS u64, toNullable(toDecimal256('1.5', 18)) AS n, "
        "CAST(NULL AS Nullable(Decimal(76, 18))) AS nothing"
    )
    assert out["ok"], out
    assert out["rows"] == [
        [
            digits,
            "-0.000000000000000001",
            max_u256,
            min_i256,
            "7",
            "18446744073709551615",
            "1.5",
            None,
        ]
    ]
    assert Decimal(out["rows"][0][0]) == Decimal(digits)
    assert int(out["rows"][0][2]) == 2**256 - 1 and int(out["rows"][0][3]) == -(2**255)
    assert json.loads(json.dumps(out)) == out


def test_rows_over_the_cap_are_cut_and_flagged(kit):
    out = kit.run_sql("SELECT block_date FROM fct_pool_daily ORDER BY block_date, pool_address")
    assert out["ok"] and out["row_count"] == 5 == len(out["rows"]) and out["truncated"] is True
    out = kit.run_sql("SELECT pool_address FROM dim_pools ORDER BY pool_address")
    assert out["row_count"] == 4 and out["truncated"] is False
    out = kit.run_sql("SELECT number FROM numbers(5)")
    assert out["row_count"] == 5 and out["truncated"] is False
    # The connection is still usable after a result was cut short.
    assert kit.run_sql("SELECT 1 AS one")["rows"] == [[1]]


def test_a_result_over_the_servers_row_limit_is_an_error_not_a_cut_result(kit, loaded):
    """The read-only user has max_result_rows with result_overflow_mode = 'throw'. This
    connection gets the same two settings for the session, with a small limit, to see what
    the tool returns: over the server's limit there are no rows at all, only error 396.
    Between the tool's cap and the server's limit the result is cut and flagged."""
    import clickhouse_connect

    c = config.load_clickhouse_config()
    limited = clickhouse_connect.get_client(
        host=c.host,
        port=c.port,
        username=c.user,
        password=c.password,
        database=loaded[0],
        settings={"max_result_rows": 1000, "result_overflow_mode": "throw"},
    )
    capped = tools.Tools(limited, kit._warehouse)  # the tool's own cap is 5 rows
    over = capped.run_sql("SELECT number FROM numbers(1001)")
    assert over["ok"] is False and "rows" not in over
    assert over["error"]["kind"] == "database" and over["error"]["code"] == 396
    assert "TOO_MANY_ROWS_OR_BYTES" in over["error"]["message"]
    within = capped.run_sql("SELECT number FROM numbers(1000)")
    assert within["ok"] and within["row_count"] == 5 and within["truncated"] is True
    assert capped.run_sql("SELECT number FROM numbers(1001) LIMIT 3")["rows"] == [[0], [1], [2]]


def test_the_empty_smart_money_table_answers_with_no_rows(kit):
    out = kit.run_sql("SELECT count() AS n FROM fct_pool_daily_smart_money")
    assert out["rows"] == [[0]]
    out = kit.run_sql("SELECT * FROM fct_pool_daily_smart_money")
    # No rows, and no column list either: for an empty result the server sends none.
    assert out == {"ok": True, "columns": [], "rows": [], "row_count": 0, "truncated": False}


def test_a_clickhouse_error_comes_back_as_data(kit):
    out = kit.run_sql("SELECT no_such_column FROM fct_pool_daily")
    assert out["ok"] is False and out["error"]["kind"] == "database"
    assert out["error"]["code"] == 47
    message = out["error"]["message"]
    assert "no_such_column" in message and "UNKNOWN_IDENTIFIER" in message
    assert "\n" not in message and "http" not in message and "Received ClickHouse" not in message
    json.dumps(out)


def test_an_alias_that_shadows_a_column_passes_the_guard_and_clickhouse_says_why(kit):
    """The guard lets it through on purpose; the lesson is in the server's error."""
    out = kit.run_sql("SELECT sum(volume_usd) AS volume_usd, avg(volume_usd) FROM fct_pool_daily")
    assert out["ok"] is False and out["error"]["kind"] == "database"
    assert out["error"]["code"] == 184 and "ILLEGAL_AGGREGATION" in out["error"]["message"]
    fixed = kit.run_sql(
        "SELECT sum(volume_usd) AS total, avg(volume_usd) AS mean FROM fct_pool_daily"
    )
    assert fixed["ok"] and fixed["row_count"] == 1


def test_the_same_sql_is_not_sent_again_after_it_failed(kit, loaded):
    bad = "SELECT no_such_column FROM fct_pool_daily"
    assert kit.run_sql(bad)["error"]["kind"] == "database"
    again = kit.run_sql(bad)
    assert again == {
        "ok": False,
        "error": {
            "kind": "repeated",
            "message": "This exact SQL already failed in this question and was not sent again. "
            "Change the query: read the earlier error.",
        },
    }
    assert kit.run_sql(bad + " ")["error"]["kind"] == "database"  # another text is another try
    good = "SELECT 1 AS one"
    assert kit.run_sql(good)["ok"] and kit.run_sql(good)["ok"]  # only failures are remembered
    # A new question starts clean.
    fresh = tools.Tools(loaded[1], kit._warehouse)
    assert fresh.run_sql(bad)["error"]["kind"] == "database"


def test_what_the_guard_rejects_never_reaches_the_server(kit, loaded):
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"the client was used: {name}")

    offline = tools.Tools(Untouchable(), kit._warehouse)
    for sql in ("DROP TABLE dim_pools", "SELECT 1; SELECT 2", "SELECT 1 SETTINGS max_threads = 1"):
        out = offline.run_sql(sql)
        assert out["ok"] is False and out["error"]["kind"] == "rejected"
        assert offline.run_sql(sql)["error"]["kind"] == "repeated"
    assert offline.run_sql(None)["error"]["kind"] == "rejected"
    assert kit.run_sql("SELECT count() FROM dim_pools")["rows"] == [[4]]


def test_a_client_failure_is_data_too(kit):
    class Broken:
        def query_rows_stream(self, sql):
            raise ConnectionError("connection refused\nsecond line")

        def query(self, sql):
            raise ConnectionError("connection refused")

    broken = tools.Tools(Broken(), kit._warehouse)
    out = broken.run_sql("SELECT 1")
    assert out == {
        "ok": False,
        "error": {"kind": "client", "message": "ConnectionError: connection refused"},
    }
    assert broken.describe_schema()["error"]["kind"] == "client"
