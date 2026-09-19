"""Run every solution in docs/sql_practice_solutions.sql against real landed data.

Builds a throw-away database with a `swaps` table (the simplest candidate of the
schema experiments) and a `pools` table from pools.yml, runs each statement,
prints the first rows, and drops the database. A solution that does not run is
not a solution.

    PYTHONPATH=src uv run python scripts/check_sql_practice.py --landing /var/lib/univ3-indexer/landing
    ... --keep     # leave the database in place to practise against it
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from schema_experiments import COLUMNS, NAMES, _read, connect, rows_of

from univ3_indexer import landing
from univ3_indexer.config import REPO_ROOT
from univ3_indexer.pools import load_pools

DB = "test_sql_practice"
SOLUTIONS = REPO_ROOT / "docs" / "sql_practice_solutions.sql"


def statements() -> list[tuple[str, str]]:
    text = SOLUTIONS.read_text(encoding="utf-8")
    parts = re.split(r"^-- \[(\w+)\]\s*$", text, flags=re.MULTILINE)[1:]
    return [(parts[i], parts[i + 1].strip().rstrip(";")) for i in range(0, len(parts), 2)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--landing", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    client = connect()
    client.command(f"DROP DATABASE IF EXISTS {DB}")
    client.command(f"CREATE DATABASE {DB}")
    failures = 0
    try:
        client.command(
            f"CREATE TABLE {DB}.swaps ({COLUMNS}) ENGINE = MergeTree ORDER BY (pool, block_timestamp)"
        )
        client.command(
            f"CREATE TABLE {DB}.pools (address String, token0 String, token1 String, "
            "decimals0 UInt8, decimals1 UInt8, fee UInt32, label String) "
            "ENGINE = MergeTree ORDER BY address"
        )
        pools = load_pools()
        client.insert(
            f"{DB}.pools",
            [[p.address.lower(), p.token0, p.token1, p.decimals0, p.decimals1, p.fee, p.label]
             for p in pools],
        )  # fmt: skip
        files = landing.landed_files(args.landing)
        files = files[: args.max_files] if args.max_files else files
        for _, _, path in files:
            swaps = _read(path)
            if swaps:
                client.insert(f"{DB}.swaps", rows_of(swaps), column_names=NAMES)
        print(
            f"loaded {client.command(f'SELECT count() FROM {DB}.swaps')} swaps from {len(files)} files\n"
        )

        for number, sql in statements():
            try:
                if sql.upper().startswith("SYSTEM"):
                    client.command(sql)
                    print(f"[{number}] ok (command)\n")
                    continue
                result = client.query(sql, settings={"database": DB})
            except Exception as exc:  # noqa: BLE001 - report every failure, then exit non-zero
                failures += 1
                print(f"[{number}] FAILED: {str(exc)[:400]}\n")
                continue
            print(
                f"[{number}] ok, {len(result.result_rows)} rows: {', '.join(result.column_names)}"
            )
            for row in result.result_rows[:4]:
                print("     ", row)
            print()
    finally:
        if not args.keep:
            client.command(f"DROP DATABASE IF EXISTS {DB}")
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
