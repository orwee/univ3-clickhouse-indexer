"""`make demo`: the whole pipeline on the committed fixtures. No API key, no network data.

Runs inside the demo container (docker-compose.demo.yml) against a throw-away ClickHouse:

  1. land      the ~240 real Swap logs of tests/fixtures/ into a JSONL landing zone
  2. view      create the daily materialized view BEFORE loading, so rows arrive via the trigger
  3. load      landing zone -> raw_swaps, then verify it (rows, duplicates, coverage, view)
  4. reload    load again, full and incremental: nothing may change
  5. dbt       seed + staging + marts + every dbt test, into its own database
  6. reconcile internal: recomputation from raw_swaps vs the materialized view, exact

Exits non-zero at the first step that does not hold.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from univ3_indexer import clickhouse as ch
from univ3_indexer import config, landing, loader, mv, reconcile
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

    mart = client.query(
        "SELECT pool_label, sum(swaps), round(sum(volume_usd), 2), round(sum(fees_usd), 4) "
        "FROM demo_dbt.fct_pool_daily GROUP BY pool_label ORDER BY 2 DESC"
    ).result_rows
    step("result: fct_pool_daily")
    for row in mart:
        print("  ", row)
    if sum(row[1] for row in mart) != total:
        print("FAILED: the mart does not account for every swap")
        return 1
    print("\nDEMO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
