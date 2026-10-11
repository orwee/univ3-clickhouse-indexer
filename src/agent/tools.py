"""What the model can do: look at the schema, and run one SELECT.

Both tools return plain data that goes straight into JSON. Neither raises into the loop: a
statement the guard rejects, a ClickHouse error and a client error all come back as a
result with ``ok`` false, because the error text is what the model corrects itself from.

The client handed to ``Tools`` decides what can be read. In production it is connected as
the read-only user, and the grants of that user are the table list the server enforces;
the list in the YAML only says which tables ``describe_schema`` shows.
"""

from __future__ import annotations

import datetime
import decimal
import math
import re

from clickhouse_connect.driver.exceptions import DatabaseError

from agent import sql_guard
from agent.warehouse import Warehouse

# Integers beyond this lose digits in a JSON reader that uses doubles, so they go as strings.
MAX_SAFE_INTEGER = 2**53 - 1
_WIDE_INTEGER = re.compile(r"U?Int(128|256)")
MESSAGE_CHARS = 600


def json_safe(value: object) -> object:
    """One cell as something ``json.dumps`` writes without losing a digit.

    Decimal becomes a string in plain notation (``Decimal(text)`` gives the same number
    back), an integer too wide for a double becomes a string of its digits, dates and times
    take their ISO form.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value if -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER else str(value)
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            return str(value)
        # Not normalize(): it rounds to the 28 digits of the default arithmetic context.
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if text in ("-0", "") else text
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + value.hex()
    if isinstance(value, dict):
        return {str(json_safe(k)): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    return str(value)


def _cell(value: object, type_name: str) -> object:
    if isinstance(value, int) and not isinstance(value, bool) and _WIDE_INTEGER.search(type_name):
        return str(value)  # always a string for these types, whatever the size of this value
    return json_safe(value)


def _first_line(text: str) -> str:
    """The server's own sentence: no client preamble, no URL, one line."""
    marker = "DB::Exception: "
    if marker in text:
        text = text.split(marker, 1)[1]
    text = text.strip().splitlines()[0] if text.strip() else ""
    text = re.sub(r"\s*\(for url [^)]*\)\s*$", "", text)
    return text[:MESSAGE_CHARS]


def _failure(kind: str, message: str, code: int | None = None) -> dict:
    error: dict = {"kind": kind, "message": message}
    if code is not None:
        error["code"] = code
    return {"ok": False, "error": error}


class Tools:
    """The two tools, bound to one connection and one warehouse, for ONE question.

    ``client`` is a clickhouse-connect client whose default database is the warehouse's, so
    the model writes table names without a database in front.
    """

    def __init__(self, client, warehouse: Warehouse):
        self._client = client
        self._warehouse = warehouse
        self._failed: set[str] = set()

    def describe_schema(self, tables: list[str] | None = None) -> dict:
        """Column names and types of the configured tables, or of the ones asked for.

        Names and types only, as DESCRIBE TABLE gives them: no descriptions.
        """
        wanted = list(tables) if tables else list(self._warehouse.tables)
        unknown = [t for t in wanted if t not in self._warehouse.tables]
        if unknown:
            return _failure(
                "unknown_table",
                f"Not in the schema: {', '.join(map(str, unknown))}. "
                f"The tables are: {', '.join(self._warehouse.tables)}.",
            )
        described = {}
        for table in wanted:
            try:
                rows = self._client.query(
                    f"DESCRIBE TABLE {self._warehouse.database}.{table}"
                ).result_rows
            except DatabaseError as exc:
                return _failure("database", _first_line(str(exc)), exc.code)
            except Exception as exc:  # noqa: BLE001 - nothing may escape into the loop
                return _failure("client", f"{type(exc).__name__}: {_first_line(str(exc))}")
            described[table] = [{"name": row[0], "type": row[1]} for row in rows]
        return {"ok": True, "database": self._warehouse.database, "tables": described}

    def run_sql(self, sql: str) -> dict:
        """Run one SELECT and return its rows, at most ``row_cap`` of them.

        ``truncated`` says whether rows were cut. A text that already failed in this
        question is not sent again. A result with no rows has no column list either: the
        server sends none.
        """
        if not isinstance(sql, str):
            return _failure("rejected", "The sql argument must be a string.")
        if sql in self._failed:
            return _failure(
                "repeated",
                "This exact SQL already failed in this question and was not sent again. "
                "Change the query: read the earlier error.",
            )
        verdict = sql_guard.check(sql)
        if not verdict.allowed:
            self._failed.add(sql)
            return _failure("rejected", verdict.message)
        cap = self._warehouse.row_cap
        rows: list[list] = []
        truncated = False
        try:
            with self._client.query_rows_stream(sql) as stream:
                names = list(stream.source.column_names)
                types = [t.name for t in stream.source.column_types]
                for row in stream:
                    if len(rows) == cap:
                        truncated = True
                        break
                    rows.append([_cell(v, t) for v, t in zip(row, types, strict=True)])
        except DatabaseError as exc:
            self._failed.add(sql)
            return _failure("database", _first_line(str(exc)), exc.code)
        except Exception as exc:  # noqa: BLE001 - nothing may escape into the loop
            self._failed.add(sql)
            return _failure("client", f"{type(exc).__name__}: {_first_line(str(exc))}")
        return {
            "ok": True,
            "columns": [{"name": n, "type": t} for n, t in zip(names, types, strict=True)],
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
