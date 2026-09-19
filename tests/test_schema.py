"""The versioned DDL creates exactly the table that DECISIONS.md describes."""

from univ3_indexer import clickhouse as ch

EXPECTED_COLUMNS = {
    "pool_address": "LowCardinality(String)",
    "block_number": "UInt64",
    "block_timestamp": "DateTime('UTC')",
    "tx_hash": "FixedString(32)",
    "log_index": "UInt32",
    "sender": "FixedString(20)",
    "recipient": "FixedString(20)",
    "amount0": "Int256",
    "amount1": "Int256",
    "sqrt_price_x96": "UInt256",
    "liquidity": "UInt128",
    "tick": "Int32",
}


def test_ddl_file_never_names_a_database():
    sql = ch.strip_sql_comments(ch.RAW_SWAPS_DDL.read_text())
    assert "onchain" not in sql.lower()
    assert "CREATE TABLE IF NOT EXISTS raw_swaps" in sql


def test_ddl_creates_the_decided_table_and_it_can_be_dropped(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database)
    columns = dict(
        clickhouse.query(
            "SELECT name, type FROM system.columns WHERE database = %(db)s AND table = %(t)s "
            "ORDER BY position",
            parameters={"db": temp_database, "t": ch.RAW_SWAPS},
        ).result_rows
    )
    assert columns == EXPECTED_COLUMNS
    assert list(columns) == list(EXPECTED_COLUMNS), "column order is part of the contract"

    engine, sorting_key, primary_key, partition_key = clickhouse.query(
        "SELECT engine, sorting_key, primary_key, partition_key FROM system.tables "
        "WHERE database = %(db)s AND name = %(t)s",
        parameters={"db": temp_database, "t": ch.RAW_SWAPS},
    ).result_rows[0]
    assert engine == "MergeTree"
    assert sorting_key == "pool_address, block_timestamp, block_number, log_index"
    assert primary_key == "pool_address, block_timestamp"
    assert partition_key == "toYYYYMM(block_timestamp)"

    clickhouse.command(f"DROP TABLE {temp_database}.{ch.RAW_SWAPS}")
    left = clickhouse.command(
        "SELECT count() FROM system.tables WHERE database = %(db)s",
        parameters={"db": temp_database},
    )
    assert left == 0


def test_applying_the_ddl_twice_is_harmless(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database)
    ch.apply_ddl(clickhouse, temp_database)


def test_the_primary_key_is_a_prefix_of_the_sorting_key_and_not_unique(clickhouse, temp_database):
    """Two rows with the same full sorting key coexist: MergeTree does not deduplicate."""
    ch.apply_ddl(clickhouse, temp_database)
    row = ["0x" + "ab" * 20, 1, 1_700_000_000, b"\x01" * 32, 7, b"\x02" * 20, b"\x03" * 20,
           -(2**255), 2**255 - 1, 2**160 - 1, 2**128 - 1, -887272]  # fmt: skip
    table = f"{temp_database}.{ch.RAW_SWAPS}"
    clickhouse.insert(table, [row, row], column_names=list(EXPECTED_COLUMNS))
    assert clickhouse.command(f"SELECT count() FROM {table}") == 2
    back = clickhouse.query(
        f"SELECT amount0, amount1, sqrt_price_x96, liquidity, tick, lower(hex(tx_hash)) "
        f"FROM {table} LIMIT 1"
    ).result_rows[0]
    assert back == (-(2**255), 2**255 - 1, 2**160 - 1, 2**128 - 1, -887272, "01" * 32)
