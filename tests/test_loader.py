"""Landing zone -> ClickHouse, against a throw-away database. Skips without a server."""

import json
from pathlib import Path

import pytest

from univ3_indexer import clickhouse as ch
from univ3_indexer import landing, loader
from univ3_indexer.backfill import Batch
from univ3_indexer.swap import decode_swap

FIXTURES = Path(__file__).parent / "fixtures" / "swap_logs.json"
RAW = sorted(
    (log for response in json.loads(FIXTURES.read_text()) for log in response["result"]),
    key=lambda e: (int(e["blockNumber"], 16), int(e["logIndex"], 16)),
)


def make_landing(directory: Path, pieces: int = 4, only: range | None = None) -> int:
    """Cut the fixture logs into `pieces` contiguous files. Returns the number of rows."""
    blocks = sorted({int(e["blockNumber"], 16) for e in RAW})
    cuts = [blocks[i * len(blocks) // pieces] for i in range(pieces)] + [blocks[-1] + 1]
    sink, written = landing.JsonlSink(directory), 0
    for index in range(pieces):
        if only is not None and index not in only:
            continue
        lo, hi = cuts[index], cuts[index + 1] - 1
        logs = tuple(e for e in RAW if lo <= int(e["blockNumber"], 16) <= hi)
        sink.write_batch(Batch(lo, hi, logs, tuple(decode_swap(e) for e in logs)))
        written += len(logs)
    return written


def count(clickhouse, database):
    return clickhouse.command(f"SELECT count() FROM {database}.{ch.RAW_SWAPS}")


# --- pure parts (no server needed) ---------------------------------------------------


def test_rows_carry_binary_hashes_and_exact_integers(tmp_path):
    make_landing(tmp_path, pieces=1)
    (_, _, path), *_ = landing.landed_files(tmp_path)
    rows = loader.rows_of_file(path)
    assert len(rows) == len(RAW) == loader.count_lines(path)
    first, original = rows[0], decode_swap(RAW[0])
    named = dict(zip(loader.COLUMNS, first, strict=True))
    assert named["tx_hash"] == bytes.fromhex(original.tx_hash[2:]) and len(named["tx_hash"]) == 32
    assert len(named["sender"]) == len(named["recipient"]) == 20
    assert (named["amount0"], named["amount1"]) == (original.amount0, original.amount1)
    assert named["pool_address"] == original.pool == original.pool.lower()


def test_a_malformed_hash_is_refused():
    with pytest.raises(loader.LoadError, match="expected 32 bytes"):
        loader._hex_to_bytes("0x1234", 32)


# --- loading -------------------------------------------------------------------------


def test_full_load_matches_the_landing_zone_and_verifies(clickhouse, temp_database, tmp_path):
    total = make_landing(tmp_path)
    summary = loader.load(clickhouse, temp_database, tmp_path, "full")
    assert (summary.rows_inserted, summary.files_loaded) == (total, 4)
    assert summary.inserts == 1, "four small files travel in ONE insert, not four"
    result = loader.verify(clickhouse, temp_database, tmp_path)
    assert result.ok, result.problems
    assert result.facts["table_rows"] == result.facts["landing_lines"] == total


def test_values_survive_the_trip_including_binary_columns(clickhouse, temp_database, tmp_path):
    make_landing(tmp_path)
    loader.load(clickhouse, temp_database, tmp_path, "full")
    biggest = max((decode_swap(e) for e in RAW), key=lambda s: abs(s.amount1))
    row = clickhouse.query(
        f"SELECT amount0, amount1, sqrt_price_x96, liquidity, tick, "
        f"concat('0x', lower(hex(tx_hash))), concat('0x', lower(hex(sender))), pool_address "
        f"FROM {temp_database}.{ch.RAW_SWAPS} "
        f"WHERE block_number = {biggest.block_number} AND log_index = {biggest.log_index}"
    ).result_rows[0]
    assert row == (biggest.amount0, biggest.amount1, biggest.sqrt_price_x96, biggest.liquidity,
                   biggest.tick, biggest.tx_hash, biggest.sender, biggest.pool)  # fmt: skip


def test_full_reload_twice_does_not_duplicate(clickhouse, temp_database, tmp_path):
    total = make_landing(tmp_path)
    loader.load(clickhouse, temp_database, tmp_path, "full")
    loader.load(clickhouse, temp_database, tmp_path, "full")
    assert count(clickhouse, temp_database) == total


def test_incremental_twice_does_not_duplicate(clickhouse, temp_database, tmp_path):
    total = make_landing(tmp_path)
    first = loader.load(clickhouse, temp_database, tmp_path, "incremental")
    second = loader.load(clickhouse, temp_database, tmp_path, "incremental")
    assert (first.files_loaded, first.rows_inserted) == (4, total)
    assert (second.files_loaded, second.files_skipped, second.rows_inserted) == (0, 4, 0)
    assert count(clickhouse, temp_database) == total


def test_incremental_loads_only_the_files_that_arrived_since(clickhouse, temp_database, tmp_path):
    early = make_landing(tmp_path, only=range(0, 2))
    loader.load(clickhouse, temp_database, tmp_path, "incremental")
    assert count(clickhouse, temp_database) == early

    late = make_landing(tmp_path, only=range(2, 4))
    summary = loader.load(clickhouse, temp_database, tmp_path, "incremental")
    assert (summary.files_skipped, summary.files_loaded, summary.rows_inserted) == (2, 2, late)
    assert loader.verify(clickhouse, temp_database, tmp_path).ok


def test_incremental_repairs_a_half_loaded_file(clickhouse, temp_database, tmp_path):
    total = make_landing(tmp_path)
    loader.load(clickhouse, temp_database, tmp_path, "full")
    from_block, to_block, _ = landing.landed_files(tmp_path)[1]
    table = f"{temp_database}.{ch.RAW_SWAPS}"
    clickhouse.command(  # simulate an interrupted load: drop some rows of one file
        f"ALTER TABLE {table} DELETE WHERE block_number BETWEEN {from_block} AND {to_block} "
        f"AND log_index % 2 = 0",
        settings={"mutations_sync": 2},
    )
    assert count(clickhouse, temp_database) < total
    summary = loader.load(clickhouse, temp_database, tmp_path, "incremental")
    assert (summary.files_repaired, summary.files_skipped) == (1, 3)
    assert count(clickhouse, temp_database) == total
    assert loader.verify(clickhouse, temp_database, tmp_path).ok


# --- verification must fail when things do not match -----------------------------------


def test_verification_catches_a_duplicate(clickhouse, temp_database, tmp_path):
    make_landing(tmp_path)
    loader.load(clickhouse, temp_database, tmp_path, "full")
    table = f"{temp_database}.{ch.RAW_SWAPS}"
    clickhouse.command(f"INSERT INTO {table} SELECT * FROM {table} LIMIT 1")
    result = loader.verify(clickhouse, temp_database, tmp_path)
    assert not result.ok
    assert result.facts["duplicate_keys"] == 1
    assert any("more than once" in p for p in result.problems)
    assert any("row count" in p for p in result.problems)


def test_verification_catches_a_missing_row_and_names_the_file(clickhouse, temp_database, tmp_path):
    make_landing(tmp_path)
    loader.load(clickhouse, temp_database, tmp_path, "full")
    table = f"{temp_database}.{ch.RAW_SWAPS}"
    victim = decode_swap(RAW[-1])
    clickhouse.command(
        f"ALTER TABLE {table} DELETE WHERE block_number = {victim.block_number} "
        f"AND log_index = {victim.log_index}",
        settings={"mutations_sync": 2},
    )
    result = loader.verify(clickhouse, temp_database, tmp_path)
    assert not result.ok
    last_file = landing.landed_files(tmp_path)[-1][2].name
    assert any(last_file in p for p in result.problems)


def test_verification_catches_a_gap_in_the_landing_zone(clickhouse, temp_database, tmp_path):
    make_landing(tmp_path)
    loader.load(clickhouse, temp_database, tmp_path, "full")
    landing.landed_files(tmp_path)[1][2].unlink()
    result = loader.verify(clickhouse, temp_database, tmp_path)
    assert any("gap" in p for p in result.problems)


def test_the_command_exits_non_zero_when_verification_fails(clickhouse, temp_database, tmp_path):
    make_landing(tmp_path)
    args = ["--landing", str(tmp_path), "--database", temp_database]
    assert loader.main(["--mode", "full", *args]) == 0
    table = f"{temp_database}.{ch.RAW_SWAPS}"
    clickhouse.command(f"INSERT INTO {table} SELECT * FROM {table} LIMIT 1")
    assert loader.main(["--verify-only", *args]) == 1
    assert loader.main(["--mode", "full", *args]) == 0  # a full reload heals it
