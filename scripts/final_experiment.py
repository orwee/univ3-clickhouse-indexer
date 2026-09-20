"""What does FINAL cost with the sorting key that was actually chosen? Measures; changes nothing.

    PYTHONPATH=src:scripts uv run python scripts/final_experiment.py > results.json

docs/SCHEMA_EXPERIMENTS.md measured FINAL on a ReplacingMergeTree ordered by
(pool, block_number, log_index): a key without time, on which a one-day query could not prune
with or without FINAL. This repeats it with the ORDER BY of the real table,
(pool_address, block_timestamp, block_number, log_index), which is unique per log and is
therefore a valid deduplication key as well.

In the throw-away database `test_final_experiment`, two tables filled from the real raw_swaps
with the SAME inserts (many small ones, merges stopped, every tenth slice delivered twice):

  plain      MergeTree, the real DDL                     (duplicates stay: it is the baseline)
  replacing  ReplacingMergeTree, same columns, same key  (duplicates collapse under FINAL)

Each query is measured without and with FINAL, first with the parts unmerged and then after
OPTIMIZE FINAL (one part per monthly partition), with the query condition cache off and on.
A third variant adds do_not_merge_across_partitions_select_final = 1.
"""

from __future__ import annotations

import argparse
import json
import sys

from schema_experiments import measure

from univ3_indexer import clickhouse as ch
from univ3_indexer import config

DB = "test_final_experiment"
ACROSS = " SETTINGS do_not_merge_across_partitions_select_final = 1"


def create(client, name: str, engine: str) -> None:
    ddl = ch.strip_sql_comments(ch.RAW_SWAPS_DDL.read_text()).strip().rstrip(";")
    ddl = ddl.replace("raw_swaps", name, 1).replace("ENGINE = MergeTree", f"ENGINE = {engine}", 1)
    client.command(ddl, settings={"database": DB})
    client.command(f"SYSTEM STOP MERGES {DB}.{name}")


def state(client, name: str) -> dict:
    row = client.query(
        "SELECT count(), sum(rows), sum(data_compressed_bytes), uniqExact(partition) "
        f"FROM system.parts WHERE database = '{DB}' AND table = '{name}' AND active"
    ).result_rows[0]
    return dict(
        zip(("parts", "rows", "compressed_bytes", "partitions"), map(int, row), strict=True)
    )


def queries(table: str, big: str, small: str, day: str, modifier: str, settings: str) -> dict:
    t = f"{DB}.{table}{modifier}"
    one_day = (f"block_timestamp >= toDateTime('{day} 00:00:00', 'UTC') AND "
               f"block_timestamp < toDateTime('{day} 00:00:00', 'UTC') + INTERVAL 1 DAY")  # fmt: skip
    return {
        "daily_volume_all_pools": f"SELECT pool_address, toDate(block_timestamp) d, count(), sum(abs(amount0)) FROM {t} GROUP BY pool_address, d{settings}",
        "one_pool_one_day_big": f"SELECT count(), sum(abs(amount0)) FROM {t} WHERE pool_address = '{big}' AND {one_day}{settings}",
        "one_pool_one_day_small": f"SELECT count(), sum(abs(amount0)) FROM {t} WHERE pool_address = '{small}' AND {one_day}{settings}",
        "all_pools_one_day": f"SELECT count(), sum(abs(amount0)) FROM {t} WHERE {one_day}{settings}",
    }


def measure_all(client, table: str, probe: tuple) -> dict:
    variants = {"no_final": ("", "")}
    if table == "replacing":  # a plain MergeTree refuses FINAL (ILLEGAL_FINAL)
        variants["final"] = (" FINAL", "")
        variants["final_not_across_partitions"] = (" FINAL", ACROSS)
    out = {}
    for label, (modifier, settings) in variants.items():
        out[label] = {}
        for name, sql in queries(table, *probe, modifier, settings).items():
            result = measure(client, sql)
            result["answer"] = [str(v) for v in client.query(sql).result_rows[0][-2:]]
            out[label][name] = result
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="database holding raw_swaps (default: CLICKHOUSE_DB)")
    parser.add_argument("--inserts", type=int, default=200, help="slices of the block range")
    parser.add_argument("--duplicate-every", type=int, default=10)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    source = args.source or config.load_clickhouse_config().database
    ch.qualified(source)
    client = ch.connect(database="default")
    client.command(f"DROP DATABASE IF EXISTS {DB}")
    client.command(f"CREATE DATABASE {DB}")
    out: dict = {"clickhouse": client.command("SELECT version()"), "source": source,
                 "inserts": args.inserts, "duplicate_every": args.duplicate_every}  # fmt: skip
    try:
        create(client, "plain", "MergeTree")
        create(client, "replacing", "ReplacingMergeTree")
        lo, hi, total = client.query(
            f"SELECT min(block_number), max(block_number), count() FROM {source}.{ch.RAW_SWAPS}"
        ).result_rows[0]
        step = (hi - lo) // args.inserts + 1
        redelivered = 0
        for i in range(args.inserts):
            where = f"block_number >= {lo + i * step} AND block_number < {lo + (i + 1) * step}"
            again = args.duplicate_every and i % args.duplicate_every == 0
            for table in ("plain", "replacing"):
                for _ in range(2 if again else 1):
                    client.command(
                        f"INSERT INTO {DB}.{table} SELECT * FROM {source}.{ch.RAW_SWAPS} WHERE {where}"
                    )
            if again:
                redelivered += int(
                    client.command(f"SELECT count() FROM {source}.{ch.RAW_SWAPS} WHERE {where}")
                )
        out["rows_in_source"], out["rows_redelivered"] = int(total), redelivered

        shares = client.query(
            f"SELECT pool_address, count() n FROM {source}.{ch.RAW_SWAPS} GROUP BY 1 ORDER BY n DESC"
        ).result_rows
        day = client.command(
            f"SELECT toString(toDate(min(block_timestamp)) + 5) FROM {source}.{ch.RAW_SWAPS}"
        )
        probe = (shares[0][0], shares[-1][0], day)
        out["probe"] = {"big_pool": probe[0], "small_pool": probe[1], "day": day}

        out["unmerged"] = {t: {"state": state(client, t), "queries": measure_all(client, t, probe)}
                           for t in ("plain", "replacing")}  # fmt: skip
        for table in ("plain", "replacing"):
            client.command(f"SYSTEM START MERGES {DB}.{table}")
            client.command(f"OPTIMIZE TABLE {DB}.{table} FINAL")
        out["merged"] = {t: {"state": state(client, t), "queries": measure_all(client, t, probe)}
                         for t in ("plain", "replacing")}  # fmt: skip
    finally:
        if not args.keep:
            client.command(f"DROP DATABASE IF EXISTS {DB}")
    out["database_dropped"] = not args.keep
    json.dump(out, sys.stdout, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
