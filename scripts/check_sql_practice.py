"""Run every solution in docs/sql_practice_solutions.sql against the REAL tables, read-only.

    PYTHONPATH=src uv run python scripts/check_sql_practice.py

The solutions use the real schema: onchain.raw_swaps, onchain.swaps_daily (the read view over
the materialized view), onchain_dbt.stg_swaps, onchain_dbt.fct_pool_daily, onchain_dbt.dim_pools.
So the data must be loaded (`make load`), the view set up (`make mv-setup`) and dbt built
(`make dbt-build`) first. Nothing is created or modified: every statement is a SELECT, an
EXPLAIN or SYSTEM FLUSH LOGS. A solution that does not run, or returns nothing, is a failure.
"""

from __future__ import annotations

import re
import sys

from univ3_indexer import clickhouse as ch
from univ3_indexer.config import REPO_ROOT

SOLUTIONS = REPO_ROOT / "docs" / "sql_practice_solutions.sql"
REQUIRED = (
    ("onchain", "raw_swaps"), ("onchain", "swaps_daily"), ("onchain", "swaps_daily_agg"),
    ("onchain_dbt", "stg_swaps"), ("onchain_dbt", "fct_pool_daily"), ("onchain_dbt", "dim_pools"),
)  # fmt: skip
READ_ONLY = re.compile(r"^\s*(SELECT|WITH|EXPLAIN|SYSTEM FLUSH LOGS)\b", re.IGNORECASE)


def statements() -> list[tuple[str, str]]:
    text = SOLUTIONS.read_text(encoding="utf-8")
    parts = re.split(r"^-- \[(\w+)\]\s*$", text, flags=re.MULTILINE)[1:]
    return [(parts[i], parts[i + 1].strip().rstrip(";")) for i in range(0, len(parts), 2)]


def main() -> int:
    client = ch.connect(database="default")
    missing = [
        f"{db}.{table}" for db, table in REQUIRED
        if not client.command("SELECT count() FROM system.tables WHERE database = %(d)s AND name = %(t)s",
                              parameters={"d": db, "t": table})
    ]  # fmt: skip
    if missing:
        print("missing tables:", ", ".join(missing), file=sys.stderr)
        print("run: make load && make mv-setup && make dbt-build", file=sys.stderr)
        return 2

    failures = 0
    for number, sql in statements():
        if not READ_ONLY.match(sql):
            failures += 1
            print(f"[{number}] REFUSED: a practice solution must be read-only\n")
            continue
        try:
            if sql.upper().startswith("SYSTEM"):
                client.command(sql)
                print(f"[{number}] ok (command)\n")
                continue
            result = client.query(sql)
        except Exception as exc:  # noqa: BLE001 - report every failure, then exit non-zero
            failures += 1
            print(f"[{number}] FAILED: {str(exc)[:400]}\n")
            continue
        if not result.result_rows:
            failures += 1
            print(f"[{number}] FAILED: returned no rows\n")
            continue
        print(f"[{number}] ok, {len(result.result_rows)} rows: {', '.join(result.column_names)}")
        for row in result.result_rows[:3]:
            print("     ", row)
        print()
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
