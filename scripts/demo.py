"""`make demo`: the whole pipeline on the committed fixtures. No API key, no network data.

Runs inside the demo container (docker-compose.demo.yml) against a throw-away ClickHouse:

  1. land      the ~240 real Swap logs of tests/fixtures/ into a JSONL landing zone
  2. view      create the daily materialized view BEFORE loading, so rows arrive via the trigger
  3. load      landing zone -> raw_swaps, then verify it (rows, duplicates, coverage, view)
  4. reload    load again, full and incremental: nothing may change
  5. dbt       seed + staging + marts + every dbt test, into its own database
  6. reconcile internal: recomputation from raw_swaps vs the materialized view, exact
  7. reader    connect as the read-only user of clickhouse/users.d/agent_reader.xml and try
               everything it must be refused, the destructive statements included. This
               throw-away server is the only place where those are ever tried.

Exits non-zero at the first step that does not hold.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from clickhouse_connect.driver.exceptions import DatabaseError, ProgrammingError

from univ3_indexer import agent_reader, config, landing, loader, mv, reconcile
from univ3_indexer import clickhouse as ch
from univ3_indexer.backfill import Batch
from univ3_indexer.swap import decode_swap

FIXTURES = config.REPO_ROOT / "tests" / "fixtures" / "swap_logs.json"


def land_fixtures(directory: Path, pieces: int = 4) -> int:
    """Cut the fixture logs into contiguous files, as the backfill would have written them."""
    logs = sorted(
        (entry for response in json.loads(FIXTURES.read_text()) for entry in response["result"]),
        key=lambda e: (int(e["blockNumber"], 16), int(e["logIndex"], 16)),
    )
    blocks = sorted({int(e["blockNumber"], 16) for e in logs})
    cuts = [blocks[i * len(blocks) // pieces] for i in range(pieces)] + [blocks[-1] + 1]
    sink = landing.JsonlSink(directory)
    for i in range(pieces):
        lo, hi = cuts[i], cuts[i + 1] - 1
        chunk = tuple(e for e in logs if lo <= int(e["blockNumber"], 16) <= hi)
        sink.write_batch(Batch(lo, hi, chunk, tuple(decode_swap(e) for e in chunk)))
    return len(logs)


def step(title: str) -> None:
    print(f"\n=== {title}", flush=True)


def check_reader(admin, raw_database: str, dbt_database: str) -> list[str]:
    """Everything the read-only user may and may not do. Returns what did not hold."""
    d = agent_reader.definition()
    if d.database != dbt_database:
        return [f"the grants name {d.database}, dbt built into {dbt_database}"]
    reader = agent_reader.connect()
    print(f"connected as {reader.command('SELECT currentUser()')} with clickhouse-connect")
    marts = set(d.tables)
    mart = ch.qualified(d.database, d.tables[0])
    failures: list[str] = []

    def expect(what: str, held: bool) -> None:
        print(f"  {'ok' if held else 'FAILED':6} {what}")
        if not held:
            failures.append(what)

    new_table = ch.qualified(d.database, "test_reader_probe")
    failures += agent_reader.run_checks(
        reader, agent_reader.harmless_checks(d, raw_database, new_table)
    )
    failures += agent_reader.run_checks(reader, agent_reader.destructive_checks(d))

    shown = {row[0] for row in reader.query(f"SHOW TABLES FROM {d.database}").result_rows}
    expect("SHOW TABLES lists the granted marts and nothing else", shown == marts)
    columns = reader.query(
        "SELECT DISTINCT database, table FROM system.columns "
        "WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')"
    ).result_rows
    expect(
        "system.columns shows the granted marts and nothing else",
        {tuple(row) for row in columns} == {(d.database, t) for t in marts},
    )
    expect(
        "max_execution_time as a URL parameter: refused with 164",
        agent_reader.url_parameter_error_code("SELECT 1", max_execution_time="600")
        == agent_reader.READONLY,
    )
    try:
        reader.query("SELECT 1", settings={"max_execution_time": 600})
        refused = False
    except ProgrammingError:
        refused = True
    expect("clickhouse-connect refuses a per-query setting before sending it", refused)
    try:
        reader.insert(mart, [["0x"]], column_names=["pool_address"])
        denied = False
    except DatabaseError as exc:
        denied = exc.code == agent_reader.ACCESS_DENIED
    expect("clickhouse-connect insert: refused with 497", denied)

    # Grants are by name: the mart stays readable when the table behind the name changes,
    # as it does whenever a model is rebuilt under the same name.
    rows = int(admin.command(f"SELECT count() FROM {mart}"))
    spare = ch.qualified(d.database, d.tables[0] + "__spare")
    admin.command(f"CREATE TABLE {spare} AS {mart}")
    admin.command(f"INSERT INTO {spare} SELECT * FROM {mart}")
    admin.command(f"EXCHANGE TABLES {mart} AND {spare}")
    expect(
        "a mart after EXCHANGE TABLES is readable",
        int(reader.command(f"SELECT count() FROM {mart}")) == rows,
    )
    expect(
        "the table it was exchanged with is not",
        agent_reader.error_code(reader, f"SELECT count() FROM {spare}")
        == agent_reader.ACCESS_DENIED,
    )
    admin.command(f"DROP TABLE {mart} SYNC")
    admin.command(f"CREATE TABLE {mart} AS {spare}")
    admin.command(f"INSERT INTO {mart} SELECT * FROM {spare}")
    admin.command(f"DROP TABLE {spare} SYNC")
    expect(
        "a mart after DROP and CREATE is readable",
        int(reader.command(f"SELECT count() FROM {mart}")) == rows,
    )
    expect(
        "nothing the reader tried left a trace: the mart still has its rows",
        int(admin.command(f"SELECT count() FROM {mart}")) == rows
        and int(admin.command(f"EXISTS TABLE {new_table}")) == 0,
    )
    return failures


def main() -> int:
    c = config.load_clickhouse_config()
    database = c.database
    client = ch.connect(database="default")
    client.command(f"CREATE DATABASE IF NOT EXISTS {ch.qualified(database).split('.')[0]}")

    with tempfile.TemporaryDirectory() as tmp:
        landing_dir = Path(tmp) / "landing"
        step("1. land the fixtures")
        total = land_fixtures(landing_dir)
        print(f"{total} real Swap logs in {len(landing.landed_files(landing_dir))} files, "
              f"blocks {landing.check_coverage(landing_dir)}")  # fmt: skip

        step("2. create the materialized view on the EMPTY table")
        ch.apply_ddl(client, database)
        mv.create(client, database)

        step("3. load and verify")
        summary = loader.load(client, database, landing_dir, "full")
        check = loader.verify(client, database, landing_dir)
        print(summary)
        print(json.dumps(check.facts, indent=2))
        if not check.ok or summary.rows_inserted != total:
            print("FAILED:", check.problems)
            return 1

        step("4. load again: full, then incremental. Nothing may change")
        loader.load(client, database, landing_dir, "full")
        again = loader.load(client, database, landing_dir, "incremental")
        check = loader.verify(client, database, landing_dir)
        print(again)
        if not check.ok or again.rows_inserted != 0 or check.facts["table_rows"] != total:
            print("FAILED:", check.problems)
            return 1
        through_view = client.command(
            f"SELECT sum(swaps) FROM {ch.qualified(database, mv.READ_VIEW)}"
        )
        differing = len(mv.mismatches(client, database))
        print(f"rows: {check.facts['table_rows']} | through the view: {through_view}")
        print(f"pool-days differing from a direct GROUP BY: {differing}")
        if int(through_view) != total:
            return 1

    step("5. dbt build (seed, staging, marts, tests)")
    dbt = subprocess.run([sys.executable, "scripts/run_dbt.py", "build"], cwd=config.REPO_ROOT)  # noqa: S603
    if dbt.returncode:
        return dbt.returncode

    step("6. internal reconciliation: recomputation from raw_swaps vs the materialized view")
    result = reconcile.run(client, database, internal_only=True)
    print(f"A internal: {'exact, 0 differences' if result.internal_ok else result.internal}")
    print("B external: skipped in the demo (it needs the external source, which needs the network)")
    if not result.internal_ok:
        return 1

    dbt_database = os.environ["DBT_TARGET_DATABASE"]
    mart = client.query(
        "SELECT pool_label, sum(swaps), round(sum(volume_usd), 2), round(sum(fees_usd), 4) "
        f"FROM {ch.qualified(dbt_database, 'fct_pool_daily')} "
        "GROUP BY pool_label ORDER BY 2 DESC"
    ).result_rows
    step("result: fct_pool_daily")
    for row in mart:
        print("  ", row)
    if sum(row[1] for row in mart) != total:
        print("FAILED: the mart does not account for every swap")
        return 1

    step("7. the read-only user: what it may read and everything it is refused")
    failures = check_reader(client, database, dbt_database)
    if failures:
        print("FAILED:", failures)
        return 1
    print("\nDEMO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
