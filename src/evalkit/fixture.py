"""The five dbt marts as committed files, and how to load them into a database.

``evals/fixture/`` holds one ``<table>.tsv`` per mart in ClickHouse's
``TabSeparatedWithNamesAndTypes`` format, ``schema.sql`` with the ``CREATE TABLE`` statements
(unqualified names) and ``fingerprint.json``. ``scripts/export_marts_fixture.py`` writes them
from the live marts with SELECT only; ``load`` puts them into a database given by name.

One mart is in the fixture as a schema and no rows: see ``SCHEMA_ONLY``.

Everything here that touches a server is a SELECT, except ``load``, which only ever creates
tables: it never drops or replaces one, so loading into a database that already has a mart
fails instead of overwriting it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path

import yaml

from univ3_indexer import clickhouse as ch
from univ3_indexer import config

FIXTURE_DIR = config.REPO_ROOT / "evals" / "fixture"
SPEC_FILE = config.REPO_ROOT / "evals" / "fixture.yml"
SCHEMA_FILE = "schema.sql"
FINGERPRINT_FILE = "fingerprint.json"
FORMAT = "TabSeparatedWithNamesAndTypes"

# Nothing of the warehouse is named in this module. Which tables the fixture holds, which of
# them are kept as a schema and no rows, and which columns the fingerprint summarises all
# come from the spec file, under evals/.
_SPEC = yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))
TABLES: tuple[str, ...] = tuple(_SPEC["tables"])
# Tables whose rows are NOT published: the fixture holds the two header lines of the file and
# the CREATE TABLE, so the table exists wherever the fixture is loaded, and it is empty there.
# The value is the reason, and it is copied into fingerprint.json.
SCHEMA_ONLY: dict[str, str] = dict(_SPEC["schema_only"])
DATE_COLUMN: str = _SPEC["fingerprint"]["date_column"]
SUM_COLUMNS: tuple[str, ...] = tuple(_SPEC["fingerprint"]["sum_columns"])
# Above this a file does not go into the repository without the owner deciding how.
MAX_FILE_BYTES = 3 * 1024 * 1024


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]
    types: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]

    def column(self, name: str) -> list[str | None]:
        i = self.columns.index(name)
        return [row[i] for row in self.rows]


def parse(name: str, data: bytes) -> Table:
    """Parse one TabSeparatedWithNamesAndTypes file. NULL (``\\N``) becomes ``None``.

    The marts hold no tab, newline or backslash inside a value, so nothing is unescaped; a
    file that needs unescaping is refused rather than read wrongly.
    """
    text = data.decode("utf-8")
    if not text.endswith("\n"):
        raise ValueError(f"{name}: the file does not end in a newline")
    lines = text[:-1].split("\n")
    if len(lines) < 2:
        raise ValueError(f"{name}: no header")
    columns, types = (tuple(line.split("\t")) for line in lines[:2])
    if len(columns) != len(types) or len(set(columns)) != len(columns):
        raise ValueError(f"{name}: the two header lines do not describe the same columns")
    rows = []
    for number, line in enumerate(lines[2:], start=3):
        cells = line.split("\t")
        if len(cells) != len(columns):
            raise ValueError(f"{name}: line {number} has {len(cells)} cells, not {len(columns)}")
        for cell in cells:
            if "\\" in cell and cell != "\\N":
                raise ValueError(f"{name}: line {number} holds an escape sequence")
        rows.append(tuple(None if cell == "\\N" else cell for cell in cells))
    return Table(name, columns, tuple(t.replace("\\'", "'") for t in types), tuple(rows))


def read_table(name: str, directory: Path = FIXTURE_DIR) -> Table:
    return parse(name, (directory / f"{name}.tsv").read_bytes())


def statements(directory: Path = FIXTURE_DIR) -> dict[str, str]:
    """``CREATE TABLE`` statement per table, from schema.sql."""
    sql = ch.strip_sql_comments((directory / SCHEMA_FILE).read_text(encoding="utf-8"))
    found = {}
    for statement in (part.strip() for part in sql.split(";\n")):
        if statement:
            head = statement.split("\n", 1)[0].split()
            if head[:2] != ["CREATE", "TABLE"] or len(head) != 3 or "." in head[2]:
                raise ValueError(f"{SCHEMA_FILE}: not an unqualified CREATE TABLE: {head}")
            found[head[2]] = statement.rstrip(";")
    return found


def decimal_text(value: Decimal) -> str:
    """A Decimal in plain notation without trailing zeros, every digit kept.

    Not ``normalize()``: that rounds to the precision of the arithmetic context, 28
    digits by default, and a Decimal(76, 18) can hold 76.
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def fingerprint_of(table: Table) -> dict:
    """What fingerprint.json says about one table, computed from its rows alone."""
    out: dict = {"rows": len(table.rows)}
    if not table.rows:
        return out
    if DATE_COLUMN in table.columns:
        dates = table.column(DATE_COLUMN)
        out["first_date"], out["last_date"] = min(dates), max(dates)
    for name in SUM_COLUMNS:
        if name in table.columns:
            with localcontext() as exact:
                exact.prec = 200  # a wide decimal sum must not be rounded to 28 digits
                total = sum((Decimal(v) for v in table.column(name) if v is not None), Decimal(0))
            out[f"sum_{name}"] = decimal_text(total)
    return out


def read_fingerprint(directory: Path = FIXTURE_DIR) -> dict:
    return json.loads((directory / FINGERPRINT_FILE).read_text(encoding="utf-8"))


def order_by(client, database: str, table: str) -> str:
    """The table's sorting key, or every column when it has none (``ORDER BY tuple()``)."""
    key, columns = client.query(
        "SELECT t.sorting_key, "
        "arrayStringConcat(arrayMap(x -> x.2, arraySort(groupArray((c.position, c.name)))), ', ') "
        "FROM system.tables AS t INNER JOIN system.columns AS c "
        "ON c.database = t.database AND c.table = t.name "
        "WHERE t.database = {db:String} AND t.name = {table:String} GROUP BY t.sorting_key",
        parameters={"db": database, "table": table},
    ).first_row
    return key or columns


def dump(client, database: str, table: str) -> bytes:
    """Every row of one table, in sorting-key order, as the bytes the fixture file holds.

    Two dumps of the same data are byte-identical: the key is unique in every mart (the
    tests check it on the files), so the order is total.

    For a table in ``SCHEMA_ONLY`` no row is read at all: the query is ``LIMIT 0`` and the
    result is the two header lines.
    """
    name = ch.qualified(database, table)
    if table in SCHEMA_ONLY:
        return client.raw_query(f"SELECT * FROM {name} LIMIT 0", fmt=FORMAT)
    return client.raw_query(
        f"SELECT * FROM {name} ORDER BY {order_by(client, database, table)}", fmt=FORMAT
    )


def create_statement(client, database: str, table: str) -> str:
    """``SHOW CREATE TABLE`` for one table, with the database name taken out of it."""
    statement = client.query(f"SHOW CREATE TABLE {ch.qualified(database, table)}").first_row[0]
    qualified = f"CREATE TABLE {database}.{table}\n"
    if not statement.startswith(qualified) or database in statement[len(qualified) :]:
        raise ValueError(f"{table}: unexpected CREATE TABLE statement")
    return f"CREATE TABLE {table}\n" + statement[len(qualified) :]


def load(client, database: str, directory: Path = FIXTURE_DIR) -> dict[str, int]:
    """Create the five tables in ``database`` and fill them from the files. Rows per table.

    The database must exist. A table that is already there makes this fail: nothing is
    dropped, truncated or replaced. A table in ``SCHEMA_ONLY`` is created and stays empty.
    """
    ddl = statements(directory)
    loaded = {}
    for table in TABLES:
        target = ch.qualified(database, table)
        client.command(ddl[table], settings={"database": database})
        client.raw_insert(
            target, insert_block=(directory / f"{table}.tsv").read_bytes(), fmt=FORMAT
        )
        loaded[table] = int(client.command(f"SELECT count() FROM {target}"))
    return loaded
