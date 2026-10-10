"""The SQL guard, as a table: what it lets through and what it stops, with the reason."""

import pytest

from agent import sql_guard

ALLOWED = [
    "SELECT 1",
    "select count() from fct_pool_daily",
    "SELECT 1;",
    "  SELECT 1 ;  -- done",
    "(SELECT 1) UNION ALL (SELECT 2)",
    "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
    "with 1 as one select one",
    "SELECT * FROM numbers(10)",
    "SELECT * FROM generateSeries(1, 3)",
    "SELECT format('{}-{}', 'a', 'b')",
    "SELECT extract(year FROM toDate('2026-01-01'))",
    # Text inside strings, quoted identifiers and comments is not SQL.
    "SELECT 'a; b' AS x",
    "SELECT 'SETTINGS max_execution_time = 600'",
    "SELECT 'url(' AS x",
    "SELECT `url` FROM t",
    "SELECT 1 /* ; SETTINGS a = 1 */",
    "SELECT 1 -- ; DROP TABLE t",
    "SELECT 'it''s', 'a\\'b; c'",
    "SELECT $$ a ; b $$",
    # A column may be called settings or format: only the clause is refused.
    "SELECT settings FROM t",
    "SELECT format FROM t",
    "SELECT a FROM t ORDER BY format DESC",
    "SELECT a FROM t WHERE format",
    "SELECT a, format FROM t",
    "SELECT 1 AS url",
    # Wrong, and not the guard's business: the database answers these, and its error is
    # what the model has to learn from. The first one is the alias that shadows a column.
    "SELECT sum(volume_usd) AS volume_usd, avg(volume_usd) FROM fct_pool_daily",
    "SELECT no_such_column FROM fct_pool_daily",
    "SELECT * FROM a_table_the_reader_has_no_grant_on",
    "SELECT toDate('not a date')",
]

REJECTED = [
    ("", "empty"),
    ("   -- nothing\n", "empty"),
    (";", "empty"),
    ("SELECT 1; SELECT 2", "Exactly one statement"),
    ("SELECT 1;;", "Exactly one statement"),
    ("SELECT 1; DROP TABLE t", "Exactly one statement"),
    ("INSERT INTO t SELECT 1", "Only SELECT"),
    ("DROP TABLE t", "Only SELECT"),
    ("ALTER TABLE t DELETE WHERE 1", "Only SELECT"),
    ("TRUNCATE TABLE t", "Only SELECT"),
    ("CREATE TABLE t (x UInt8) ENGINE = Memory", "Only SELECT"),
    ("SET readonly = 0", "Only SELECT"),
    ("DESCRIBE TABLE t", "describe_schema"),
    ("SHOW TABLES", "describe_schema"),
    ("EXPLAIN SELECT 1", "Only SELECT"),
    ("WITH 1 AS x", "no SELECT"),
    ("SELECT 1 SETTINGS max_execution_time = 600", "SETTINGS"),
    ("select 1 settings max_result_rows=0", "SETTINGS"),
    ("SELECT 1 FROM t SETTINGS `readonly` = 0", "SETTINGS"),
    ("SELECT 1 INTO OUTFILE 'x.csv'", "INTO OUTFILE"),
    ("SELECT 1 into   outfile 'x.csv'", "INTO OUTFILE"),
    ("SELECT 1 FORMAT JSON", "FORMAT"),
    ("SELECT a FROM t FORMAT CSV", "FORMAT"),
    ("SELECT a FROM t WHERE (b) format TSV;", "FORMAT"),
    ("SELECT * FROM url('http://example.com/x', CSV)", "url()"),
    ("SELECT * FROM file('x.csv')", "file()"),
    ("SELECT file('x.txt')", "file()"),
    ("SELECT * FROM remote('other:9000', system.one)", "remote()"),
    ("SELECT * FROM remoteSecure('other', system.one)", "remoteSecure()"),
    ("SELECT * FROM s3('https://bucket/x.parquet')", "s3()"),
    ("SELECT * FROM S3 ('https://bucket/x.parquet')", "S3()"),
    ("SELECT * FROM `url`('http://example.com')", "url()"),
    ("SELECT * FROM t, postgresql('h:5432', 'd', 't', 'u', 'p')", "postgresql()"),
    ("SELECT * FROM mysql('h:3306', 'd', 't', 'u', 'p')", "mysql()"),
    ("SELECT * FROM executable('script.sh', TSV, 'x String')", "executable()"),
    ("SELECT * FROM cluster('default', system.one)", "cluster()"),
    ("SELECT * FROM merge('.*', '.*')", "merge()"),
    ("SELECT 'abc", "never closed"),
    ("SELECT 1 /* open", "never closed"),
    ("SELECT `abc", "never closed"),
    # A dollar-quoted string must not hide what follows it.
    ("SELECT $$'$$ SETTINGS max_execution_time = 600 --'", "SETTINGS"),
    ("SELECT $a$'$a$; DROP TABLE t --'", "Exactly one statement"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    verdict = sql_guard.check(sql)
    assert verdict.allowed, verdict.message
    assert verdict.message == ""


@pytest.mark.parametrize(("sql", "says"), REJECTED)
def test_rejected_with_a_message_for_the_model(sql, says):
    verdict = sql_guard.check(sql)
    assert not verdict.allowed
    assert verdict.message.startswith(sql_guard.PREFIX)
    assert says in verdict.message


def test_the_two_lists_of_table_functions_do_not_overlap():
    assert not sql_guard.SAFE_TABLE_FUNCTIONS & sql_guard.REFUSED_TABLE_FUNCTIONS
    for name in ("url", "file", "remote", "s3"):
        assert name in sql_guard.REFUSED_TABLE_FUNCTIONS


def test_every_table_function_of_this_server_is_in_one_of_the_two_lists(clickhouse):
    """A table function added by a later ClickHouse has to be classified by hand."""
    known = {
        row[0] for row in clickhouse.query("SELECT name FROM system.table_functions").result_rows
    }
    decided = sql_guard.SAFE_TABLE_FUNCTIONS | sql_guard.REFUSED_TABLE_FUNCTIONS
    assert known - decided == set()
