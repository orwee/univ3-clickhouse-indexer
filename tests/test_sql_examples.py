"""sql/examples/*.sql must run against the dbt marts. Skips when they are not built."""

import pytest

from univ3_indexer import clickhouse as ch

EXAMPLES = sorted((ch.SQL_DIR / "examples").glob("*.sql"))
DBT_DATABASE = "onchain_dbt"


@pytest.fixture(scope="module")
def marts(clickhouse):
    built = clickhouse.command(
        "SELECT count() FROM system.tables WHERE database = %(db)s AND name = 'fct_pool_daily'",
        parameters={"db": DBT_DATABASE},
    )
    if not built:
        pytest.skip(f"{DBT_DATABASE}.fct_pool_daily does not exist: run `make dbt-build` first")
    return clickhouse


def test_there_are_examples():
    assert len(EXAMPLES) >= 2


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_runs_and_returns_rows(marts, path):
    sql = ch.strip_sql_comments(path.read_text()).strip().rstrip(";")
    result = marts.query(sql, settings={"database": DBT_DATABASE})
    assert result.result_rows, f"{path.name} returned nothing"
