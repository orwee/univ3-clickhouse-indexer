"""The read-only user: its definition, a connection as that user, and what it must refuse.

The user is declared in ``clickhouse/users.d/agent_reader.xml``, which the demo always mounts
into its server and the real server mounts only under ``make up-reader``. Nothing here creates
or changes it: this module reads the file, connects with the credentials of
``agent-reader.env`` and lists the statements that tell whether the server enforces what the
file says.

The statements come in two lists. ``harmless_checks`` would do no damage if the server
accepted them, so the tests run them against the real server. ``destructive_checks`` would,
so they run only in ``make demo``, against a server that is deleted afterwards.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET  # noqa: S405 - parses one file of this repository
from dataclasses import dataclass
from pathlib import Path

import clickhouse_connect
from clickhouse_connect.driver.exceptions import DatabaseError

from univ3_indexer import clickhouse as ch
from univ3_indexer import config

USERS_FILE = config.REPO_ROOT / "clickhouse" / "users.d" / "agent_reader.xml"
MOUNT_TARGET = "/etc/clickhouse-server/users.d/agent_reader.xml"
USER = "agent_reader"
PASSWORD_HASH_VARIABLE = "AGENT_READER_PASSWORD_SHA256"  # noqa: S105 - a variable name

# ClickHouse error codes, as the server names them.
TIMEOUT_EXCEEDED = 159
READONLY = 164
TOO_MANY_ROWS_OR_BYTES = 396
ACCESS_DENIED = 497
AUTHENTICATION_FAILED = 516

_GRANT = re.compile(r"GRANT SELECT ON (\w+)\.(\w+)")


@dataclass(frozen=True)
class Definition:
    """What the users.d file says about the reader."""

    database: str
    tables: tuple[str, ...]
    settings: dict[str, str]
    grants: tuple[str, ...]


def definition(path: Path = USERS_FILE) -> Definition:
    root = ET.parse(path).getroot()  # noqa: S314 - a file of this repository, not input
    user = root.find(f"users/{USER}")
    profile = root.find(f"profiles/{user.findtext('profile')}")
    grants = tuple(q.text.strip() for q in user.findall("grants/query"))
    parsed = [_GRANT.fullmatch(g) for g in grants]
    if not grants or not all(parsed):
        raise ValueError(f"{path}: every grant must be 'GRANT SELECT ON database.table'")
    databases = {m.group(1) for m in parsed}
    if len(databases) != 1:
        raise ValueError(f"{path}: the grants name more than one database: {sorted(databases)}")
    return Definition(
        database=databases.pop(),
        tables=tuple(m.group(2) for m in parsed),
        settings={child.tag: (child.text or "").strip() for child in profile},
        grants=grants,
    )


def connect():
    """A client connected as the reader. Raises ``ConfigError`` without agent-reader.env."""
    c = config.load_agent_reader_config()
    return clickhouse_connect.get_client(
        host=c.host, port=c.port, username=c.user, password=c.password, database=c.database
    )


def error_code(client, sql: str) -> int:
    """The server's error code for one statement, 0 when it is accepted."""
    try:
        client.command(sql)
    except DatabaseError as exc:
        if exc.code is None:
            raise
        return exc.code
    return 0


def url_parameter_error_code(sql: str, **parameters: str) -> int:
    """The same, with settings sent as URL parameters instead of written in the statement.

    clickhouse-connect refuses to send a setting it knows is read-only, so this goes over
    plain HTTP to see what the server itself answers.
    """
    c = config.load_agent_reader_config()
    query = "&".join(f"{k}={v}" for k, v in parameters.items())
    request = urllib.request.Request(  # noqa: S310 - http to the configured ClickHouse
        f"http://{c.host}:{c.port}/?{query}",
        data=sql.encode(),
        headers={"X-ClickHouse-User": c.user, "X-ClickHouse-Key": c.password},
    )
    try:
        with urllib.request.urlopen(request, timeout=30):  # noqa: S310
            return 0
    except urllib.error.HTTPError as exc:
        return int(exc.headers.get("X-ClickHouse-Exception-Code") or -1)


@dataclass(frozen=True)
class Check:
    what: str
    sql: str
    expected: int  # an error code, or 0 for "works"


def harmless_checks(d: Definition, raw_database: str, new_table: str) -> list[Check]:
    """Statements that would change nothing even if the server accepted every one of them.

    ``new_table`` is a qualified ``test_*`` name for the CREATE TABLE attempt: whoever calls
    this owns that name and removes the table if the server ever accepts the statement.
    """
    mart = ch.qualified(d.database, d.tables[0])
    over_the_limit = 2 * int(d.settings["max_result_rows"])
    return [
        *(
            Check(f"SELECT on {t}", f"SELECT count() FROM {ch.qualified(d.database, t)}", 0)
            for t in d.tables
        ),
        Check("DESCRIBE on a granted mart", f"DESCRIBE TABLE {mart}", 0),
        Check(
            "SELECT on the staging view",
            f"SELECT count() FROM {ch.qualified(d.database, 'stg_swaps')}",
            ACCESS_DENIED,
        ),
        Check(
            "SELECT on the seed",
            f"SELECT count() FROM {ch.qualified(d.database, 'pools')}",
            ACCESS_DENIED,
        ),
        Check(
            "SELECT on the raw table",
            f"SELECT count() FROM {ch.qualified(raw_database)}",
            ACCESS_DENIED,
        ),
        Check(
            "INSERT of zero rows into a mart",
            f"INSERT INTO {mart} SELECT * FROM {mart} WHERE 0",
            ACCESS_DENIED,
        ),
        Check("CREATE TABLE", f"CREATE TABLE {new_table} (x UInt8) ENGINE = Memory", ACCESS_DENIED),
        Check(
            "SETTINGS max_execution_time in the statement",
            "SELECT 1 SETTINGS max_execution_time = 600",
            READONLY,
        ),
        Check(
            "a result over the row limit",
            f"SELECT number FROM numbers({over_the_limit})",
            TOO_MANY_ROWS_OR_BYTES,
        ),
    ]


def destructive_checks(d: Definition) -> list[Check]:
    """Statements that would do damage if accepted. For the throw-away demo server ONLY."""
    mart = ch.qualified(d.database, d.tables[0])
    return [
        Check("INSERT of a row", f"INSERT INTO {mart} SELECT * FROM {mart} LIMIT 1", ACCESS_DENIED),
        Check("ALTER DELETE", f"ALTER TABLE {mart} DELETE WHERE 1", ACCESS_DENIED),
        Check("TRUNCATE", f"TRUNCATE TABLE {mart}", ACCESS_DENIED),
        Check("DROP TABLE", f"DROP TABLE {mart}", ACCESS_DENIED),
        Check("CREATE TEMPORARY TABLE", "CREATE TEMPORARY TABLE probe (x UInt8)", ACCESS_DENIED),
        Check(
            "url()",
            "SELECT * FROM url('http://127.0.0.1:8123/ping', LineAsString)",
            ACCESS_DENIED,
        ),
        Check("file()", "SELECT * FROM file('probe.csv', CSV, 'x String')", ACCESS_DENIED),
        Check("remote()", "SELECT * FROM remote('127.0.0.1', system.one)", ACCESS_DENIED),
        Check("SET readonly = 0", "SET readonly = 0", READONLY),
        Check(
            "a query that runs past max_execution_time",
            "SELECT count() FROM numbers(100000000000) WHERE sipHash64(number) = 0",
            TIMEOUT_EXCEEDED,
        ),
    ]


def run_checks(client, checks: list[Check]) -> list[str]:
    """Run every check, print one line each, return the ones that did not hold."""
    failures = []
    for check in checks:
        got = error_code(client, check.sql)
        verdict = "ok" if got == check.expected else "FAILED"
        wanted = "works" if check.expected == 0 else f"refused with {check.expected}"
        print(f"  {verdict:6} {check.what}: {wanted}" + ("" if verdict == "ok" else f", got {got}"))
        if got != check.expected:
            failures.append(check.what)
    return failures
