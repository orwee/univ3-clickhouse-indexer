"""Load the JSONL landing zone into the raw swaps table, and prove it matches.

    python -m univ3_indexer.loader --mode full          # truncate, load everything
    python -m univ3_indexer.loader --mode incremental   # load only what is missing
    python -m univ3_indexer.loader --verify-only

The table is a plain MergeTree: it does not deduplicate anything. Idempotency
lives here instead, and rests on one fact: a landing file is named after its
block range and no two files overlap. So for every file the table either holds
exactly its rows, none of them, or something in between, and each case has one
correct action:

    rows in the table for that block range == lines in the file   -> skip
    0 rows                                                        -> insert
    anything else (an interrupted load)                           -> delete the range, insert

Inserts are BATCHED: several files per INSERT, never one row at a time and not
even one file at a time. Every INSERT creates at least one part per partition
it touches, and parts are what ClickHouse has to merge afterwards; thousands of
tiny inserts is the classic way to hit "too many parts".

Verification compares the table with the landing zone and exits non-zero on
any mismatch.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from univ3_indexer import clickhouse as ch
from univ3_indexer import config, landing

log = logging.getLogger("univ3_indexer.loader")

COLUMNS = [
    "pool_address", "block_number", "block_timestamp", "tx_hash", "log_index", "sender",
    "recipient", "amount0", "amount1", "sqrt_price_x96", "liquidity", "tick",
]  # fmt: skip
BATCH_ROWS = 100_000  # ~25 landing files per INSERT


class LoadError(RuntimeError):
    pass


def _hex_to_bytes(value: str, length: int) -> bytes:
    raw = bytes.fromhex(value.removeprefix("0x"))
    if len(raw) != length:
        raise LoadError(f"expected {length} bytes, got {len(raw)}")
    return raw


def rows_of_file(path: Path) -> list[list]:
    """Rows ready for INSERT. Hashes and addresses become binary; integers stay exact."""
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            s = landing.decode_record(json.loads(line)["decoded"])
            if s.block_timestamp is None:
                raise LoadError(f"{path.name}: a swap has no block timestamp")
            rows.append(
                [s.pool, s.block_number, s.block_timestamp, _hex_to_bytes(s.tx_hash, 32),
                 s.log_index, _hex_to_bytes(s.sender, 20), _hex_to_bytes(s.recipient, 20),
                 s.amount0, s.amount1, s.sqrt_price_x96, s.liquidity, s.tick]
            )  # fmt: skip
    return rows


def count_lines(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def _rows_per_block(client, table: str) -> dict[int, int]:
    result = client.query(f"SELECT block_number, count() FROM {table} GROUP BY block_number")
    return dict(result.result_rows)


def _batches(files: list[tuple[int, int, Path]]) -> Iterator[list[tuple[int, int, Path, list]]]:
    batch, size = [], 0
    for from_block, to_block, path in files:
        rows = rows_of_file(path)
        batch.append((from_block, to_block, path, rows))
        size += len(rows)
        if size >= BATCH_ROWS:
            yield batch
            batch, size = [], 0
    if batch:
        yield batch


@dataclass
class LoadSummary:
    files_loaded: int = 0
    files_skipped: int = 0
    files_repaired: int = 0
    rows_inserted: int = 0
    inserts: int = 0


def load(client, database: str, landing_dir: Path, mode: str) -> LoadSummary:
    if mode not in ("full", "incremental"):
        raise ValueError("mode must be 'full' or 'incremental'")
    landing.check_coverage(landing_dir)
    ch.apply_ddl(client, database)
    table = ch.qualified(database)
    files = landing.landed_files(landing_dir)
    summary = LoadSummary()

    if mode == "full":
        client.command(f"TRUNCATE TABLE {table}")
        pending = files
    else:
        present = _rows_per_block(client, table)
        pending = []
        for from_block, to_block, path in files:
            expected = count_lines(path)
            have = sum(present.get(b, 0) for b in range(from_block, to_block + 1))
            if have == expected:
                summary.files_skipped += 1
                continue
            if have:
                log.warning("%s: table has %d rows, file has %d: reloading that block range",
                            path.name, have, expected)  # fmt: skip
                client.command(
                    f"ALTER TABLE {table} DELETE WHERE block_number BETWEEN {from_block} "
                    f"AND {to_block}",
                    settings={"mutations_sync": 2},
                )
                summary.files_repaired += 1
            pending.append((from_block, to_block, path))

    for batch in _batches(pending):
        rows = [row for *_, file_rows in batch for row in file_rows]
        if rows:
            client.insert(table, rows, column_names=COLUMNS)
            summary.inserts += 1
        summary.files_loaded += len(batch)
        summary.rows_inserted += len(rows)
        log.info("inserted %d rows from %d files (through block %d)", len(rows), len(batch),
                 batch[-1][1])  # fmt: skip
    return summary


@dataclass
class Verification:
    facts: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def verify(client, database: str, landing_dir: Path) -> Verification:
    """Compare the table with the landing zone. Every mismatch is a problem."""
    v = Verification()
    table = ch.qualified(database)
    try:
        coverage = landing.check_coverage(landing_dir)
    except landing.LandingError as exc:
        v.problems.append(f"landing zone: {exc}")
        coverage = None
    files = landing.landed_files(landing_dir)
    lines = sum(count_lines(path) for _, _, path in files)

    rows, min_block, max_block, min_ts, max_ts = client.query(
        f"SELECT count(), min(block_number), max(block_number), "
        f"toString(min(block_timestamp)), toString(max(block_timestamp)) FROM {table}"
    ).result_rows[0]
    duplicates = client.command(
        f"SELECT count() FROM (SELECT block_number, log_index FROM {table} "
        f"GROUP BY block_number, log_index HAVING count() > 1)"
    )
    v.facts = {
        "landing_files": len(files),
        "landing_lines": lines,
        "landing_coverage": list(coverage) if coverage else None,
        "table_rows": rows,
        "table_blocks": [min_block, max_block],
        "table_timestamps_utc": [min_ts, max_ts],
        "duplicate_keys": duplicates,
        "rows_per_pool": dict(
            client.query(
                f"SELECT pool_address, count() FROM {table} GROUP BY pool_address ORDER BY 2 DESC"
            ).result_rows
        ),
    }
    if rows != lines:
        v.problems.append(f"row count: table has {rows}, landing zone has {lines} lines")
    if duplicates:
        v.problems.append(f"{duplicates} (block_number, log_index) keys appear more than once")
    if coverage and rows and not (coverage[0] <= min_block and max_block <= coverage[1]):
        v.problems.append(
            f"table blocks {min_block}-{max_block} fall outside the landing coverage {coverage}"
        )
    if rows:
        present = _rows_per_block(client, table)
        for from_block, to_block, path in files:
            have = sum(present.get(b, 0) for b in range(from_block, to_block + 1))
            expected = count_lines(path)
            if have != expected:
                v.problems.append(f"{path.name}: {have} rows in the table, {expected} in the file")
                if len(v.problems) > 20:
                    v.problems.append("(more mismatches not listed)")
                    break
    return v


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.loader")
    parser.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    parser.add_argument("--landing", type=Path, help="default: <data dir>/landing")
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    landing_dir = args.landing or config.data_dir() / "landing"
    database = args.database or config.load_clickhouse_config().database
    client = ch.connect(database=database)
    if not args.verify_only:
        summary = load(client, database, landing_dir, args.mode)
        log.info("load (%s): %s", args.mode, summary)
    result = verify(client, database, landing_dir)
    print(json.dumps(result.facts, indent=2))
    for problem in result.problems:
        log.error("VERIFICATION FAILED: %s", problem)
    if result.ok:
        log.info("verification passed")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
