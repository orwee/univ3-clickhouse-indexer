"""Query performance experiments on a COPY of the real table. Measures; changes nothing.

    PYTHONPATH=src:scripts uv run python scripts/query_performance.py > results.json

Works in the throw-away database `test_query_perf`, filled with
`INSERT ... SELECT * FROM <raw database>.raw_swaps`, and drops it at the end. The schema
of the real database is never touched. Each experiment changes ONE thing on its own copy:

  base   the decided table, as is
  proj   + a projection ordered by time
  bloom  + a bloom_filter skipping index on tx_hash
  1 insert vs 1,000 inserts of the same rows

Rows and bytes read come from system.query_log; granules from EXPLAIN indexes = 1; every
query is measured with the query condition cache off and on (see schema_experiments.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from schema_experiments import measure

from univ3_indexer import clickhouse as ch
from univ3_indexer import config
from univ3_indexer.loader import COLUMNS

DB = "test_query_perf"


def copy_table(client, source: str, name: str) -> None:
    ddl = ch.strip_sql_comments(ch.RAW_SWAPS_DDL.read_text()).strip().rstrip(";")
    client.command(ddl.replace("raw_swaps", name, 1), settings={"database": DB})
    client.command(f"INSERT INTO {DB}.{name} SELECT * FROM {source}.{ch.RAW_SWAPS}")
    client.command(f"OPTIMIZE TABLE {DB}.{name} FINAL")


def size(client, name: str) -> dict:
    row = client.query(
        "SELECT count(), sum(rows), sum(data_compressed_bytes), sum(marks) FROM system.parts "
        f"WHERE database = '{DB}' AND table = '{name}' AND active"
    ).result_rows[0]
    return dict(
        zip(("parts", "rows", "compressed_bytes", "marks"), (int(v) for v in row), strict=True)
    )


def explain(client, sql: str) -> list[str]:
    rows = client.query(f"EXPLAIN indexes = 1 {sql}").result_rows
    keep = ("ReadFromMergeTree", "Indexes", "MinMax", "Partition", "PrimaryKey", "Skip", "Keys",
            "Condition", "Parts", "Granules", "Name", "Description", "Projection", "Search")  # fmt: skip
    return [r[0].rstrip() for r in rows if any(k in r[0] for k in keep)]


def queries(table: str, big: str, small: str, day: str, tx_hex: str) -> dict:
    t = f"{DB}.{table}"
    one_day = (f"block_timestamp >= toDateTime('{day} 00:00:00', 'UTC') AND "
               f"block_timestamp < toDateTime('{day} 00:00:00', 'UTC') + INTERVAL 1 DAY")  # fmt: skip
    week = (f"block_timestamp >= toDateTime('{day} 00:00:00', 'UTC') AND "
            f"block_timestamp < toDateTime('{day} 00:00:00', 'UTC') + INTERVAL 7 DAY")  # fmt: skip
    return {
        "daily_volume_all_pools": f"SELECT pool_address, toDate(block_timestamp) d, count(), sum(abs(amount0)) FROM {t} GROUP BY pool_address, d",
        "one_pool_one_day_big": f"SELECT count(), sum(abs(amount0)) FROM {t} WHERE pool_address = '{big}' AND {one_day}",
        "one_pool_one_day_small": f"SELECT count(), sum(abs(amount0)) FROM {t} WHERE pool_address = '{small}' AND {one_day}",
        "all_pools_one_day": f"SELECT pool_address, count(), sum(abs(amount0)) FROM {t} WHERE {one_day} GROUP BY pool_address",
        "all_pools_one_week": f"SELECT pool_address, count(), sum(abs(amount0)) FROM {t} WHERE {week} GROUP BY pool_address",
        "point_lookup_tx_hash": f"SELECT block_number, log_index, amount0, amount1 FROM {t} WHERE tx_hash = unhex('{tx_hex}')",
    }


def insert_experiment(client, source: str, rows_wanted: int, batches: int) -> dict:
    data = client.query(
        f"SELECT * FROM {source}.{ch.RAW_SWAPS} ORDER BY block_number, log_index LIMIT {rows_wanted}"
    ).result_rows
    ddl = ch.strip_sql_comments(ch.RAW_SWAPS_DDL.read_text()).strip().rstrip(";")
    out = {"rows": len(data)}
    for name, n in (("ins_one_batch", 1), ("ins_many_batches", batches)):
        client.command(ddl.replace("raw_swaps", name, 1), settings={"database": DB})
        step = len(data) // n
        started = time.perf_counter()
        for i in range(n):
            chunk = data[i * step : (i + 1) * step] if i < n - 1 else data[i * step :]
            client.insert(f"{DB}.{name}", chunk, column_names=COLUMNS)
        seconds = time.perf_counter() - started
        right_after = size(client, name)
        time.sleep(20)  # let background merges work
        client.command("SYSTEM FLUSH LOGS")
        log = client.query(
            "SELECT countIf(event_type = 'NewPart'), countIf(event_type = 'MergeParts'), "
            "sumIf(rows, event_type = 'MergeParts'), sumIf(duration_ms, event_type = 'MergeParts'), "
            "sumIf(size_in_bytes, event_type = 'MergeParts') FROM system.part_log "
            f"WHERE database = '{DB}' AND table = '{name}'"
        ).result_rows[0]
        ever = client.command(
            f"SELECT count() FROM system.parts WHERE database = '{DB}' AND table = '{name}'"
        )
        out[name] = {
            "inserts": n, "rows_per_insert": step, "insert_seconds": round(seconds, 2),
            "active_parts_right_after": right_after["parts"],
            "after_20s": size(client, name), "parts_still_on_disk_incl_inactive": int(ever),
            "part_log": dict(zip(("new_parts", "merges", "rows_rewritten_by_merges", "merge_ms",
                                  "bytes_written_by_merges"), (int(v) for v in log), strict=True)),
        }  # fmt: skip
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="database holding raw_swaps (default: CLICKHOUSE_DB)")
    parser.add_argument("--insert-rows", type=int, default=50_000)
    parser.add_argument("--insert-batches", type=int, default=1_000)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    source = args.source or config.load_clickhouse_config().database
    ch.qualified(source)
    client = ch.connect(database="default")
    client.command(f"DROP DATABASE IF EXISTS {DB}")
    client.command(f"CREATE DATABASE {DB}")
    out: dict = {"clickhouse": client.command("SELECT version()"), "source": source}
    try:
        copy_table(client, source, "base")
        out["rows"] = size(client, "base")["rows"]
        shares = client.query(
            f"SELECT pool_address, count() n FROM {DB}.base GROUP BY 1 ORDER BY n DESC"
        ).result_rows
        big, small = shares[0][0], shares[-1][0]
        day = client.command(f"SELECT toString(toDate(min(block_timestamp)) + 5) FROM {DB}.base")
        tx_hex = client.command(
            f"SELECT lower(hex(tx_hash)) FROM {DB}.base WHERE pool_address = '{big}' ORDER BY block_number DESC LIMIT 1 OFFSET 1000"
        )
        out["probe"] = {"big_pool": big, "small_pool": small, "day": day, "tx_hash": "0x" + tx_hex}

        base_q = queries("base", big, small, day, tx_hex)
        out["base"] = {"size": size(client, "base"),
                       "queries": {k: {**measure(client, q), "explain": explain(client, q)} for k, q in base_q.items()}}  # fmt: skip

        # --- projection ordered by time ---------------------------------------------------
        copy_table(client, source, "proj")
        before = size(client, "proj")
        started = time.perf_counter()
        client.command(
            f"ALTER TABLE {DB}.proj ADD PROJECTION by_time (SELECT * ORDER BY block_timestamp, pool_address)"
        )
        client.command(
            f"ALTER TABLE {DB}.proj MATERIALIZE PROJECTION by_time", settings={"mutations_sync": 2}
        )
        build = time.perf_counter() - started
        proj_bytes = client.command(
            f"SELECT sum(data_compressed_bytes) FROM system.projection_parts WHERE database = '{DB}' AND table = 'proj' AND active"
        )
        proj_q = queries("proj", big, small, day, tx_hex)
        out["projection"] = {
            "table_bytes_before": before["compressed_bytes"], "table_bytes_after": size(client, "proj")["compressed_bytes"],
            "projection_bytes": int(proj_bytes), "build_seconds": round(build, 2),
            "queries": {k: {**measure(client, proj_q[k]), "explain": explain(client, proj_q[k])}
                        for k in ("all_pools_one_day", "all_pools_one_week", "one_pool_one_day_big", "daily_volume_all_pools")},
        }  # fmt: skip

        # --- bloom filter on tx_hash ---------------------------------------------------------
        copy_table(client, source, "bloom")
        started = time.perf_counter()
        client.command(
            f"ALTER TABLE {DB}.bloom ADD INDEX tx_bloom tx_hash TYPE bloom_filter(0.01) GRANULARITY 1"
        )
        client.command(
            f"ALTER TABLE {DB}.bloom MATERIALIZE INDEX tx_bloom", settings={"mutations_sync": 2}
        )
        build = time.perf_counter() - started
        index_bytes = client.query(
            f"SELECT data_compressed_bytes, data_uncompressed_bytes FROM system.data_skipping_indices WHERE database = '{DB}' AND table = 'bloom'"
        ).result_rows[0]
        bloom_q = queries("bloom", big, small, day, tx_hex)
        absent = bloom_q["point_lookup_tx_hash"].replace(tx_hex, "00" * 32)
        out["bloom_filter"] = {
            "index_compressed_bytes": int(index_bytes[0]), "index_uncompressed_bytes": int(index_bytes[1]),
            "build_seconds": round(build, 2), "table_bytes": size(client, "bloom")["compressed_bytes"],
            "queries": {"point_lookup_tx_hash": {**measure(client, bloom_q["point_lookup_tx_hash"]), "explain": explain(client, bloom_q["point_lookup_tx_hash"])},
                        "point_lookup_absent_hash": {**measure(client, absent), "explain": explain(client, absent)}},
        }  # fmt: skip
        out["base"]["queries"]["point_lookup_absent_hash"] = measure(
            client, base_q["point_lookup_tx_hash"].replace(tx_hex, "00" * 32)
        )

        # --- one insert against many ---------------------------------------------------------
        out["inserts"] = insert_experiment(client, source, args.insert_rows, args.insert_batches)
    finally:
        if not args.keep:
            client.command(f"DROP DATABASE IF EXISTS {DB}")
    out["database_dropped"] = not args.keep
    json.dump(out, sys.stdout, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
