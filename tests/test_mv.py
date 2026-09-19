"""A ClickHouse materialized view is an insert trigger. These tests show what follows."""

import pytest

from univ3_indexer import clickhouse as ch
from univ3_indexer import landing, loader, mv

from .test_loader import make_landing


def insert_files(clickhouse, database, files):
    rows = [row for _, _, path in files for row in loader.rows_of_file(path)]
    clickhouse.insert(ch.qualified(database), rows, column_names=loader.COLUMNS)
    return len(rows)


def target_swaps(clickhouse, database):
    return clickhouse.command(f"SELECT sum(swaps) FROM {ch.qualified(database, mv.TARGET)}")


def view_swaps(clickhouse, database):
    return clickhouse.command(f"SELECT sum(swaps) FROM {ch.qualified(database, mv.READ_VIEW)}")


@pytest.fixture
def files(tmp_path):
    make_landing(tmp_path, pieces=4)
    return landing.landed_files(tmp_path)


@pytest.fixture
def raw(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database)
    return temp_database


# --- (a) ------------------------------------------------------------------------------


def test_a_view_created_over_existing_rows_leaves_its_target_empty(clickhouse, raw, files):
    existing = insert_files(clickhouse, raw, files)
    assert existing > 0
    mv.create(clickhouse, raw)
    assert clickhouse.command(f"SELECT count() FROM {ch.qualified(raw, mv.TARGET)}") == 0
    assert clickhouse.command(f"SELECT count() FROM {ch.qualified(raw, mv.READ_VIEW)}") == 0
    assert len(mv.mismatches(clickhouse, raw)) > 0, "and the comparison must say so"


# --- (b) ------------------------------------------------------------------------------


def test_b_rows_inserted_after_creation_do_appear(clickhouse, raw, files):
    mv.create(clickhouse, raw)
    inserted = insert_files(clickhouse, raw, files[:2])
    assert view_swaps(clickhouse, raw) == inserted
    assert mv.mismatches(clickhouse, raw) == []


# --- (c) ------------------------------------------------------------------------------


def test_c_backfill_below_the_cut_plus_trigger_above_equals_a_direct_group_by(
    clickhouse, raw, files
):
    before = insert_files(clickhouse, raw, files[:2])
    cutoff = mv.max_block(clickhouse, raw)
    mv.create(clickhouse, raw)
    after = insert_files(clickhouse, raw, files[2:])  # through the trigger
    assert view_swaps(clickhouse, raw) == after, "only the new rows so far"

    mv.backfill(clickhouse, raw, cutoff)
    assert view_swaps(clickhouse, raw) == before + after
    assert mv.mismatches(clickhouse, raw) == []

    # the edge: the block AT the cut-off is counted once, the next block once
    table = ch.qualified(raw)
    at_edge = clickhouse.command(f"SELECT count() FROM {table} WHERE block_number = {cutoff}")
    assert at_edge > 0
    day_of_edge = clickhouse.command(
        f"SELECT toString(toDate(max(block_timestamp), 'UTC')) FROM {table} "
        f"WHERE block_number = {cutoff}"
    )
    direct, through_view = (
        clickhouse.command(f"SELECT {agg} FROM {source} WHERE {day} = toDate('{day_of_edge}')")
        for agg, source, day in (
            ("count()", table, "toDate(block_timestamp, 'UTC')"),
            ("sum(swaps)", ch.qualified(raw, mv.READ_VIEW), "block_date"),
        )
    )
    assert direct == through_view


def test_c_a_cut_off_by_one_too_low_is_detected(clickhouse, raw, files):
    insert_files(clickhouse, raw, files[:2])
    cutoff = mv.max_block(clickhouse, raw)
    mv.create(clickhouse, raw)
    insert_files(clickhouse, raw, files[2:])
    mv.backfill(clickhouse, raw, cutoff - 1)  # misses the rows of the cut-off block
    assert len(mv.mismatches(clickhouse, raw)) >= 1


# --- (d) ------------------------------------------------------------------------------


def test_d_running_the_backfill_twice_counts_the_history_twice(clickhouse, raw, files):
    existing = insert_files(clickhouse, raw, files)
    mv.create(clickhouse, raw)
    cutoff = mv.max_block(clickhouse, raw)
    mv.backfill(clickhouse, raw, cutoff)
    assert view_swaps(clickhouse, raw) == existing
    mv.backfill(clickhouse, raw, cutoff)
    assert view_swaps(clickhouse, raw) == 2 * existing
    assert len(mv.mismatches(clickhouse, raw)) > 0

    mv.rebuild(clickhouse, raw)  # the way out
    assert view_swaps(clickhouse, raw) == existing
    assert mv.mismatches(clickhouse, raw) == []


# --- why the read view has a GROUP BY ---------------------------------------------------


def test_the_target_holds_several_rows_per_key_until_a_merge_and_the_view_does_not(
    clickhouse, raw, files
):
    mv.create(clickhouse, raw)
    clickhouse.command(f"SYSTEM STOP MERGES {ch.qualified(raw, mv.TARGET)}")
    for file in files:  # one insert per file: several blocks touch the same (pool, day)
        insert_files(clickhouse, raw, [file])
    target = ch.qualified(raw, mv.TARGET)
    rows = clickhouse.command(f"SELECT count() FROM {target}")
    keys = clickhouse.command(f"SELECT uniqExact(pool_address, block_date) FROM {target}")
    assert rows > keys, "the same (pool, day) is stored more than once before merging"
    in_view = clickhouse.command(f"SELECT count() FROM {ch.qualified(raw, mv.READ_VIEW)}")
    assert in_view == keys
    assert mv.mismatches(clickhouse, raw) == []


# --- the gotchas with loads that remove rows --------------------------------------------


def test_truncate_and_reload_without_care_double_counts(clickhouse, raw, files):
    """What load-full used to do. Kept as a test so the reason for the fix stays visible."""
    mv.create(clickhouse, raw)
    existing = insert_files(clickhouse, raw, files)
    clickhouse.command(f"TRUNCATE TABLE {ch.qualified(raw)}")
    assert target_swaps(clickhouse, raw) == existing, "the trigger never saw the TRUNCATE"
    insert_files(clickhouse, raw, files)
    assert view_swaps(clickhouse, raw) == 2 * existing


def test_load_full_with_the_view_attached_stays_exact(clickhouse, raw, files, tmp_path):
    mv.create(clickhouse, raw)
    first = loader.load(clickhouse, raw, tmp_path, "full")
    assert view_swaps(clickhouse, raw) == first.rows_inserted
    loader.load(clickhouse, raw, tmp_path, "full")
    loader.load(clickhouse, raw, tmp_path, "full")
    assert view_swaps(clickhouse, raw) == first.rows_inserted
    result = loader.verify(clickhouse, raw, tmp_path)
    assert result.ok, result.problems
    assert result.facts["materialized_view_mismatches"] == 0


def test_an_incremental_repair_with_the_view_attached_stays_exact(clickhouse, raw, files, tmp_path):
    mv.create(clickhouse, raw)
    total = loader.load(clickhouse, raw, tmp_path, "full").rows_inserted
    from_block, to_block, _ = files[1]
    clickhouse.command(
        f"ALTER TABLE {ch.qualified(raw)} DELETE WHERE block_number BETWEEN {from_block} "
        f"AND {to_block} AND log_index % 2 = 0",
        settings={"mutations_sync": 2},
    )
    assert len(mv.mismatches(clickhouse, raw)) > 0, "a DELETE is invisible to the trigger"
    summary = loader.load(clickhouse, raw, tmp_path, "incremental")
    assert summary.files_repaired == 1
    assert view_swaps(clickhouse, raw) == total
    assert loader.verify(clickhouse, raw, tmp_path).ok


def test_verification_fails_when_the_view_and_the_table_disagree(clickhouse, raw, files, tmp_path):
    mv.create(clickhouse, raw)
    loader.load(clickhouse, raw, tmp_path, "full")
    mv.backfill(clickhouse, raw, mv.max_block(clickhouse, raw))  # someone backfills again
    result = loader.verify(clickhouse, raw, tmp_path)
    assert not result.ok
    assert any("swaps_daily differs" in p for p in result.problems)
    assert mv.main(["--check", "--database", raw]) == 1
    assert mv.main(["--rebuild", "--database", raw]) == 0


def test_setup_is_safe_to_run_twice(clickhouse, raw, files, capsys):
    total = insert_files(clickhouse, raw, files)
    assert mv.main(["--setup", "--database", raw]) == 0
    assert "target rows right after creation: 0" in capsys.readouterr().out
    assert mv.main(["--setup", "--database", raw]) == 0
    assert "already exists" in capsys.readouterr().out
    assert view_swaps(clickhouse, raw) == total
