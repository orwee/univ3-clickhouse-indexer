"""ClickHouse access: one way to connect, one way to apply the versioned DDL."""

from __future__ import annotations

import re
from pathlib import Path

import clickhouse_connect

from univ3_indexer import config

SQL_DIR = config.REPO_ROOT / "sql"
RAW_SWAPS_DDL = SQL_DIR / "001_raw_swaps.sql"
RAW_SWAPS = "raw_swaps"


def connect(database: str | None = None):
    """A client for the configured server. ``database`` defaults to CLICKHOUSE_DB."""
    c = config.load_clickhouse_config()
    return clickhouse_connect.get_client(
        host=c.host,
        port=c.port,
        username=c.user,
        password=c.password,
        database=database or c.database,
    )


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def qualified(database: str, table: str = RAW_SWAPS) -> str:
    """``database.table`` for use in SQL text, after checking both are plain identifiers.

    Identifiers cannot be bound as query parameters, so they are interpolated; this is
    the one place that makes sure nothing but an identifier ever gets there.
    """
    for name in (database, table):
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError(f"not a plain SQL identifier: {name!r}")
    return f"{database}.{table}"


def strip_sql_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def apply_ddl(client, database: str, path: Path = RAW_SWAPS_DDL) -> None:
    """Run one DDL file inside ``database``. The file never names a database itself."""
    qualified(database)  # validates the name
    statement = strip_sql_comments(path.read_text(encoding="utf-8")).strip().rstrip(";")
    client.command(statement, settings={"database": database})
