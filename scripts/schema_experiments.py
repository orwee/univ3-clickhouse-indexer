"""Schema experiments on real landed data. Decides nothing: it measures.

Loads the JSONL landing zone into several candidate tables that differ in ONE
thing at a time, runs two queries against each, and prints what ClickHouse
actually read (from system.query_log), how long it took, and how the data sits
on disk. Everything happens in a throw-away database that is dropped at the end.

    PYTHONPATH=src uv run python scripts/schema_experiments.py \
        --landing /var/lib/univ3-indexer/landing > results.json

Needs only the ClickHouse credentials, no API key and no network.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path

import clickhouse_connect

from univ3_indexer import config, landing
from univ3_indexer.pools import load_pools

DB = "test_schema_exp"
COLUMNS = """
    pool LowCardinality(String), block_number UInt32, block_timestamp DateTime('UTC'),
    log_index UInt32, tx_hash String, sender String, recipient String,
    amount0 Int256, amount1 Int256, sqrt_price_x96 UInt256, liquidity UInt128, tick Int32
"""
NAMES = [
    "pool", "block_number", "block_timestamp", "log_index", "tx_hash", "sender", "recipient",
    "amount0", "amount1", "sqrt_price_x96", "liquidity", "tick",
]  # fmt: skip

# name -> (engine, order by, partition by). Each comparison changes one thing.
CANDIDATES = {
    "mt_pool_ts": ("MergeTree", "(pool, block_timestamp)", None),
    "mt_ts_pool": ("MergeTree", "(block_timestamp, pool)", None),
    "mt_pool_block_log": ("MergeTree", "(pool, block_number, log_index)", None),
    "rmt_pool_block_log": ("ReplacingMergeTree", "(pool, block_number, log_index)", None),
    "mt_pool_ts_monthly": ("MergeTree", "(pool, block_timestamp)", "toYYYYMM(block_timestamp)"),
    # not a candidate, a trap: a Replacing key that is NOT unique per swap
    "rmt_pool_ts_TRAP": ("ReplacingMergeTree", "(pool, block_timestamp)", None),
}


def connect():
    c = config.load_clickhouse_config()
    return clickhouse_connect.get_client(
        host=c.host, port=c.port, username=c.user, password=c.password
    )


def rows_of(swaps):
    return [
        [s.pool, s.block_number, s.block_timestamp, s.log_index, s.tx_hash, s.sender,
         s.recipient, s.amount0, s.amount1, s.sqrt_price_x96, s.liquidity, s.tick]
        for s in swaps
    ]  # fmt: skip


# --- 1. type round trip ----------------------------------------------------------


def type_round_trip(client, swaps) -> dict:
    """Insert the real extremes (and the type bounds) and read them back exactly."""
    extremes = {
        "amount1 max": max(swaps, key=lambda s: s.amount1),
        "amount1 min": min(swaps, key=lambda s: s.amount1),
        "amount0 max": max(swaps, key=lambda s: s.amount0),
        "amount0 min": min(swaps, key=lambda s: s.amount0),
        "sqrt_price max": max(swaps, key=lambda s: s.sqrt_price_x96),
        "liquidity max": max(swaps, key=lambda s: s.liquidity),
        "tick min": min(swaps, key=lambda s: s.tick),
        "tick max": max(swaps, key=lambda s: s.tick),
    }
    client.command(f"CREATE TABLE {DB}.types (label String, {COLUMNS}) ENGINE = Memory")
    data = [[label, *rows_of([s])[0]] for label, s in extremes.items()]
    bounds = [
        ["bound: int256 min / uint256 max / uint128 max", "0xb", 1, 1, 0, "0x", "0x", "0x",
         -(2**255), 2**255 - 1, 2**256 - 1, 2**128 - 1, -(2**31)],
    ]  # fmt: skip
    client.insert(f"{DB}.types", data + bounds, column_names=["label", *NAMES])

    result = {"rows": [], "surprises": []}
    back = client.query(
        f"SELECT label, amount0, amount1, sqrt_price_x96, liquidity, tick, "
        f"toString(amount0), toString(amount1), toString(sqrt_price_x96), toString(liquidity), "
        f"hex(reinterpretAsFixedString(amount1)), block_timestamp FROM {DB}.types"
    ).result_rows
    sent = {row[0]: row for row in data + bounds}
    for row in back:
        label = row[0]
        original = sent[label]
        wrote = [original[8], original[9], original[10], original[11], original[12]]
        read = list(row[1:6])
        as_text = [int(x) for x in row[6:10]]
        ok_driver = wrote == read and all(type(v) is int for v in read)
        ok_server = wrote[:4] == as_text
        # the 32 bytes as stored (little-endian two's complement): rebuild and compare bit for bit
        raw = bytes.fromhex(row[10])
        ok_bits = int.from_bytes(raw, "little", signed=True) == wrote[1] and len(raw) == 32
        result["rows"].append(
            {"label": label, "amount1_bits": abs(wrote[1]).bit_length(), "driver_exact": ok_driver,
             "server_text_exact": ok_server, "bit_for_bit": ok_bits,
             "python_types": sorted({type(v).__name__ for v in read})}
        )  # fmt: skip
        if not (ok_driver and ok_server and ok_bits):
            result["surprises"].append(f"{label}: wrote {wrote} read {read}")
    timestamp = back[0][11]
    result["datetime_python_type"] = f"{type(timestamp).__name__} tz={timestamp.tzinfo}"

    # second path: JSONEachRow with integers as strings, as they sit in the landing zone
    client.command(
        f"CREATE TABLE {DB}.types_json (amount1 Int256, sqrt_price_x96 UInt256) ENGINE = Memory"
    )  # noqa: E501
    big = extremes["amount1 min"]
    line = json.dumps({"amount1": str(big.amount1), "sqrt_price_x96": str(big.sqrt_price_x96)})
    client.raw_insert(f"{DB}.types_json", insert_block=line + "\n", fmt="JSONEachRow")
    got = client.query(f"SELECT amount1, sqrt_price_x96 FROM {DB}.types_json").result_rows[0]
    result["json_strings_exact"] = list(got) == [big.amount1, big.sqrt_price_x96]
    # and the classic mistake, for the record: the same value through Float64
    lossy = client.query(f"SELECT toInt256(toFloat64(amount1)) FROM {DB}.types_json").result_rows
    result["through_float64"] = {"original": str(big.amount1), "after": str(lossy[0][0]),
                                 "lost": str(abs(big.amount1 - lossy[0][0]))}  # fmt: skip
    return result


# --- 2. candidate tables -----------------------------------------------------------


def create_and_load(client, files, duplicate_every: int) -> dict:
    for name, (engine, order_by, partition_by) in CANDIDATES.items():
        partition = f"PARTITION BY {partition_by}" if partition_by else ""
        client.command(
            f"CREATE TABLE {DB}.{name} ({COLUMNS}) ENGINE = {engine} {partition} ORDER BY {order_by}"
        )
        # No background merges while loading: "before" then means exactly one part per
        # insert, and the Replacing table keeps its duplicates until we say otherwise.
        client.command(f"SYSTEM STOP MERGES {DB}.{name}")
    loaded = redelivered = 0
    for index, (_, _, path) in enumerate(files):
        swaps = []
        with path.open(encoding="utf-8") as fh:
            swaps = [landing.decode_record(json.loads(line)["decoded"]) for line in fh]
        if not swaps:
            continue
        rows = rows_of(swaps)
        again = duplicate_every and index % duplicate_every == 0
        for name in CANDIDATES:  # one insert per landed file, like a real loader would
            client.insert(f"{DB}.{name}", rows, column_names=NAMES)
            if again and name.startswith("rmt_pool_block_log"):
                client.insert(f"{DB}.{name}", rows, column_names=NAMES)  # a redelivered batch
        loaded += len(rows)
        redelivered += len(rows) if again else 0
    return {
        "distinct_rows": loaded,
        "rows_redelivered_to_rmt": redelivered,
        "inserts_per_table": len(files),
    }  # noqa: E501


def storage(client, table: str) -> dict:
    row = client.query(
        "SELECT count(), sum(rows), sum(data_compressed_bytes), sum(data_uncompressed_bytes), "
        "sum(primary_key_bytes_in_memory), sum(marks), uniqExact(partition) "
        f"FROM system.parts WHERE database = '{DB}' AND table = '{table}' AND active"
    ).result_rows[0]
    keys = [
        "parts",
        "rows",
        "compressed_bytes",
        "uncompressed_bytes",
        "pk_bytes",
        "marks",
        "partitions",
    ]  # noqa: E501
    return dict(zip(keys, (int(v) for v in row), strict=True))


def measure(client, sql: str, runs: int = 5) -> dict:
    ids = []
    for _ in range(runs):
        query_id = str(uuid.uuid4())
        client.query(sql, settings={"query_id": query_id, "use_query_cache": 0})
        ids.append(query_id)
    client.command("SYSTEM FLUSH LOGS")
    stats = client.query(
        "SELECT query_duration_ms, read_rows, read_bytes, memory_usage FROM system.query_log "
        f"WHERE type = 'QueryFinish' AND query_id IN {tuple(ids)!r} ORDER BY event_time_microseconds"
    ).result_rows
    explain = client.query(f"EXPLAIN indexes = 1 {sql}").result_rows
    text = [r[0].strip() for r in explain]
    granules = [t for t in text if t.startswith("Granules:")]
    parts = [t for t in text if t.startswith("Parts:")]
    return {
        "ms_median": statistics.median(s[0] for s in stats),
        "ms_all": [s[0] for s in stats],
        "read_rows": stats[-1][1],
        "read_bytes": stats[-1][2],
        "memory_bytes": stats[-1][3],
        "granules_after_primary_key": granules[-1] if granules else None,
        "parts_after_pruning": parts[-1] if parts else None,
    }


def queries(table: str, big: str, small: str, day: str, final: bool = False) -> dict:
    f = " FINAL" if final else ""
    one_day = f"block_timestamp >= toDateTime('{day} 00:00:00', 'UTC') AND block_timestamp < toDateTime('{day} 00:00:00', 'UTC') + INTERVAL 1 DAY"  # noqa: E501
    return {
        "daily_volume_all_pools": f"SELECT pool, toDate(block_timestamp) AS d, count(), sum(abs(amount0)) FROM {DB}.{table}{f} GROUP BY pool, d ORDER BY pool, d",  # noqa: E501
        "one_day_big_pool": f"SELECT count(), sum(abs(amount0)) FROM {DB}.{table}{f} WHERE pool = '{big}' AND {one_day}",  # noqa: E501
        "one_day_small_pool": f"SELECT count(), sum(abs(amount0)) FROM {DB}.{table}{f} WHERE pool = '{small}' AND {one_day}",  # noqa: E501
        "one_day_all_pools": f"SELECT count(), sum(abs(amount0)) FROM {DB}.{table}{f} WHERE {one_day}",  # noqa: E501
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--landing", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=0, help="0 = every complete file")
    parser.add_argument("--duplicate-every", type=int, default=10,
                        help="redeliver every Nth file to the Replacing table (0 = never)")  # fmt: skip
    parser.add_argument("--keep", action="store_true", help="do not drop the database at the end")
    args = parser.parse_args()

    files = landing.landed_files(args.landing)
    if args.max_files:
        files = files[: args.max_files]
    client = connect()
    client.command(f"DROP DATABASE IF EXISTS {DB}")
    client.command(f"CREATE DATABASE {DB}")
    out: dict = {"clickhouse": client.command("SELECT version()"), "files": len(files),
                 "blocks": [files[0][0], files[-1][1]]}  # fmt: skip
    try:
        sample = [s for _, _, p in files[:3] for s in _read(p)]
        out["type_round_trip"] = type_round_trip(client, sample)

        started = time.perf_counter()
        out["load"] = create_and_load(client, files, args.duplicate_every)
        out["load"]["seconds"] = round(time.perf_counter() - started, 1)

        shares = client.query(
            f"SELECT pool, count() AS n FROM {DB}.mt_pool_ts GROUP BY pool ORDER BY n DESC"
        ).result_rows
        labels = {p.address.lower(): p.label for p in load_pools()}
        out["rows_per_pool"] = {labels[a]: n for a, n in shares}
        big, small = shares[0][0], shares[-1][0]
        day = client.command(
            f"SELECT toString(toDate(min(block_timestamp)) + 1) FROM {DB}.mt_pool_ts"
        )
        out["probe"] = {"big_pool": labels[big], "small_pool": labels[small], "day": day}

        out["before_optimize"] = {t: storage(client, t) for t in CANDIDATES}
        out["replacing_before_merge"] = {
            "count_plain": client.command(f"SELECT count() FROM {DB}.rmt_pool_block_log"),
            "count_final": client.command(f"SELECT count() FROM {DB}.rmt_pool_block_log FINAL"),
            "queries_plain": {
                k: measure(client, q)
                for k, q in queries("rmt_pool_block_log", big, small, day).items()
            },  # noqa: E501
            "queries_final": {
                k: measure(client, q)
                for k, q in queries("rmt_pool_block_log", big, small, day, final=True).items()
            },  # noqa: E501
        }
        for table in CANDIDATES:
            client.command(f"SYSTEM START MERGES {DB}.{table}")
            client.command(f"OPTIMIZE TABLE {DB}.{table} FINAL")
        out["after_optimize"] = {t: storage(client, t) for t in CANDIDATES}
        out["trap"] = {
            "distinct_rows_loaded": out["load"]["distinct_rows"],
            "rows_left_in_rmt_pool_ts": client.command(
                f"SELECT count() FROM {DB}.rmt_pool_ts_TRAP"
            ),  # noqa: E501
        }
        out["queries"] = {
            t: {k: measure(client, q) for k, q in queries(t, big, small, day).items()}
            for t in CANDIDATES if not t.endswith("TRAP")
        }  # fmt: skip
        out["replacing_after_merge_final"] = {
            k: measure(client, q)
            for k, q in queries("rmt_pool_block_log", big, small, day, final=True).items()
        }
        out["column_bytes"] = {
            name: {"compressed": int(c), "uncompressed": int(u)}
            for name, c, u in client.query(
                "SELECT column, sum(column_data_compressed_bytes), sum(column_data_uncompressed_bytes) "  # noqa: E501
                f"FROM system.parts_columns WHERE database = '{DB}' AND table = 'mt_pool_ts' AND active "  # noqa: E501
                "GROUP BY column ORDER BY 2 DESC"
            ).result_rows
        }
    finally:
        if not args.keep:
            client.command(f"DROP DATABASE IF EXISTS {DB}")
    out["database_dropped"] = not args.keep
    json.dump(out, sys.stdout, indent=1, default=str)
    return 0


def _read(path: Path):
    with path.open(encoding="utf-8") as fh:
        return [landing.decode_record(json.loads(line)["decoded"]) for line in fh]


if __name__ == "__main__":
    sys.exit(main())
