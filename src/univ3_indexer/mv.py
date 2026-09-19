"""The daily materialized view: create it, backfill it, prove it matches.

    python -m univ3_indexer.mv --setup      # target + view + read view, then backfill
    python -m univ3_indexer.mv --check      # swaps_daily vs a direct GROUP BY (exit 1 on mismatch)
    python -m univ3_indexer.mv --rebuild    # truncate the target and backfill everything

A ClickHouse materialized view is an insert trigger. It sees the rows of each INSERT
into raw_swaps and nothing else: not the rows that were already there, and not rows
that are deleted or truncated later. Everything in this module follows from that.
The SQL lives in sql/mv/ as plain files; this module only runs them in order.
"""

from __future__ import annotations

import argparse
import sys

from univ3_indexer import clickhouse as ch
from univ3_indexer import config

MV_DIR = ch.SQL_DIR / "mv"
TARGET = "swaps_daily_agg"
VIEW = "swaps_daily_mv"
READ_VIEW = "swaps_daily"
_DDL = ("001_swaps_daily_agg.sql", "002_swaps_daily_mv.sql", "003_swaps_daily_view.sql")


def _sql(name: str) -> str:
    return ch.strip_sql_comments((MV_DIR / name).read_text(encoding="utf-8")).strip().rstrip(";")


def exists(client, database: str) -> bool:
    return bool(
        client.command(
            "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(name)s",
            parameters={"db": database, "name": VIEW},
        )
    )


def create(client, database: str) -> None:
    """Target table, materialized view and read view. Does NOT backfill."""
    ch.qualified(database)
    for name in _DDL:
        client.command(_sql(name), settings={"database": database})


def max_block(client, database: str) -> int:
    return int(client.command(f"SELECT max(block_number) FROM {ch.qualified(database)}"))


def backfill(client, database: str, cutoff_block: int) -> None:
    """Aggregate raw rows up to cutoff_block (inclusive) into the target. NOT idempotent."""
    ch.qualified(database)
    client.command(
        _sql("010_backfill.sql"),
        parameters={"cutoff_block": cutoff_block},
        settings={"database": database},
    )


def rebuild(client, database: str) -> None:
    """Make the target exact again after raw_swaps lost rows (TRUNCATE, DELETE).

    The trigger only ever ADDS. When rows leave raw_swaps the target keeps counting
    them, and reinserting them counts them a second time. The only correct repair is
    to empty the target and aggregate raw_swaps again. Call it with ingestion stopped.
    """
    client.command(f"TRUNCATE TABLE {ch.qualified(database, TARGET)}")
    if client.command(f"SELECT count() FROM {ch.qualified(database)}"):
        backfill(client, database, max_block(client, database))


def mismatches(client, database: str) -> list[tuple]:
    """(pool, day) pairs where swaps_daily differs from a direct GROUP BY. Expected: none."""
    ch.qualified(database)
    return list(client.query(_sql("020_compare.sql"), settings={"database": database}).result_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.mv")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--setup", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--rebuild", action="store_true")
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    args = parser.parse_args(argv)
    database = args.database or config.load_clickhouse_config().database
    client = ch.connect(database=database)

    if args.setup:
        if exists(client, database):
            print(f"{database}.{VIEW} already exists: nothing created, nothing backfilled")
        else:
            create(client, database)
            target = ch.qualified(database, TARGET)
            raw_rows = client.command(f"SELECT count() FROM {ch.qualified(database)}")
            empty = client.command(f"SELECT count() FROM {target}")
            print(f"created. raw rows: {raw_rows} | target rows right after creation: {empty}")
            rebuild(client, database)
            print(f"backfilled. target rows: {client.command(f'SELECT count() FROM {target}')}")
    elif args.rebuild:
        rebuild(client, database)
    bad = mismatches(client, database)
    days = client.command(f"SELECT count() FROM {ch.qualified(database, READ_VIEW)}")
    print(f"swaps_daily: {days} pool-days; differing from a direct GROUP BY: {len(bad)}")
    for row in bad[:20]:
        print("  MISMATCH", row)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
