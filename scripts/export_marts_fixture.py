"""`make eval-fixture`: copy the five dbt marts into evals/fixture/. SELECT only.

Writes, for each mart, ``<table>.tsv`` (TabSeparatedWithNamesAndTypes, in sorting-key order,
so two exports of the same data are byte-identical), plus ``schema.sql`` and
``fingerprint.json``. Before writing anything it checks every table against the server: the
row count and the sums computed from the bytes it is about to write must equal the ones
ClickHouse computes itself.

The marts in ``fixture.SCHEMA_ONLY`` are written as a schema only: the two header lines and
the CREATE TABLE. Their rows are never selected, and the fingerprint says rows 0 and why.

"The commit the marts were built from" is not recorded anywhere by dbt. What goes into the
fingerprint is the last commit that changed ``dbt/``, together with the time the server says
the tables were created; the export refuses to run if a table is older than that commit,
because then the marts were built from different models.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

from evalkit import fixture
from univ3_indexer import clickhouse as ch
from univ3_indexer import config

sys.path.insert(0, str(config.REPO_ROOT / "scripts"))
import run_dbt  # noqa: E402

COMMIT_RULE = (
    "the last commit that changed dbt/; every mart was created on the server after it "
    "(marts_built_at). dbt does not record the commit itself"
)


def last_dbt_commit() -> tuple[str, datetime]:
    out = subprocess.run(  # noqa: S603
        ["git", "log", "-1", "--format=%H %cI", "--", "dbt"],  # noqa: S607
        cwd=config.REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return out[0], datetime.fromisoformat(out[1])


def server_side(client, database: str, table: fixture.Table) -> dict:
    """The same figures as ``fixture.fingerprint_of``, computed by ClickHouse."""
    name = ch.qualified(database, table.name)
    out: dict = {"rows": int(client.command(f"SELECT count() FROM {name}"))}
    date = fixture.DATE_COLUMN
    if date in table.columns:
        first, last = client.query(f"SELECT min({date}), max({date}) FROM {name}").first_row
        out["first_date"], out["last_date"] = str(first), str(last)
    for column in fixture.SUM_COLUMNS:
        if column in table.columns:
            total = client.query(f"SELECT sum({column}) FROM {name}").first_row[0]
            out[f"sum_{column}"] = fixture.decimal_text(Decimal(str(total)))
    return out


def main() -> int:
    database = run_dbt.DEFAULT_TARGET_DATABASE
    client = ch.connect(database="default")
    commit, committed_at = last_dbt_commit()

    files: dict[str, bytes] = {}
    tables: dict[str, dict] = {}
    ddl = []
    built = []
    for name in fixture.TABLES:
        data = fixture.dump(client, database, name)
        table = fixture.parse(name, data)
        ours = fixture.fingerprint_of(table)
        if name in fixture.SCHEMA_ONLY:
            if table.rows:
                print(f"{name}: schema only, but the dump holds rows", file=sys.stderr)
                return 1
            ours = {**ours, "schema_only": True, "why": fixture.SCHEMA_ONLY[name]}
        elif ours != (theirs := server_side(client, database, table)):
            print(f"{name}: the export says {ours}, the server says {theirs}", file=sys.stderr)
            return 1
        created = client.query(
            "SELECT metadata_modification_time FROM system.tables "
            "WHERE database = {db:String} AND name = {table:String}",
            parameters={"db": database, "table": name},
        ).first_row[0]
        built.append(created.replace(tzinfo=UTC))
        ddl.append(fixture.create_statement(client, database, name) + ";\n")
        files[f"{name}.tsv"] = data
        tables[name] = {"order_by": fixture.order_by(client, database, name), **ours}

    if min(built) < committed_at:
        print(
            f"the marts were built at {min(built).isoformat()}, before the last commit that "
            f"changed dbt/ ({commit[:7]}, {committed_at.isoformat()}): rebuild them first",
            file=sys.stderr,
        )
        return 1
    if str(client.command("SELECT timezone()")) != "UTC":
        print("the server's time zone is not UTC: marts_built_at would be wrong", file=sys.stderr)
        return 1

    header = (
        "-- The five dbt marts, as `SHOW CREATE TABLE` printed them, with the database name\n"
        "-- removed: the database comes from the session. Written by\n"
        "-- scripts/export_marts_fixture.py; do not edit by hand.\n\n"
    )
    files[fixture.SCHEMA_FILE] = (header + "\n".join(ddl)).encode()
    fingerprint = {
        "exported_on": datetime.now(UTC).date().isoformat(),
        "source_database": database,
        "format": fixture.FORMAT,
        "built_from_commit": commit,
        "built_from_commit_rule": COMMIT_RULE,
        "marts_built_at": max(built).isoformat().replace("+00:00", "Z"),
        "tables": tables,
    }
    files[fixture.FINGERPRINT_FILE] = (json.dumps(fingerprint, indent=2) + "\n").encode()

    too_big = {n: len(b) for n, b in files.items() if len(b) > fixture.MAX_FILE_BYTES}
    if too_big:
        print(f"over {fixture.MAX_FILE_BYTES} bytes, nothing written: {too_big}", file=sys.stderr)
        return 1
    fixture.FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (fixture.FIXTURE_DIR / name).write_bytes(data)
        print(f"{len(data):>9,} bytes  evals/fixture/{name}")
    for name, facts in tables.items():
        print(f"  {name}: {facts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
