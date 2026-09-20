"""The JSONL landing zone: atomic per file, idempotent per block range, lossless."""

import json
import os
from pathlib import Path

import pytest

from univ3_indexer import landing
from univ3_indexer.backfill import Batch
from univ3_indexer.swap import decode_swap

FIXTURES = Path(__file__).parent / "fixtures" / "swap_logs.json"
RAW = [log for response in json.loads(FIXTURES.read_text()) for log in response["result"]]


def batch_of(logs, from_block=None, to_block=None) -> Batch:
    numbers = [int(entry["blockNumber"], 16) for entry in logs]
    return Batch(
        from_block if from_block is not None else min(numbers),
        to_block if to_block is not None else max(numbers),
        tuple(logs),
        tuple(decode_swap(entry) for entry in logs),
    )


FIRST = batch_of(RAW[:40])


def files(directory):
    return sorted(p.name for p in directory.iterdir())


# --- format ---------------------------------------------------------------------


def test_one_line_per_log_with_decoded_and_untouched_raw(tmp_path):
    landing.JsonlSink(tmp_path).write_batch(FIRST)
    (path,) = tmp_path.iterdir()
    assert path.name == landing.file_name(FIRST.from_block, FIRST.to_block)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 40
    assert [line["raw"] for line in lines] == list(FIRST.logs)
    assert set(lines[0]) == {"decoded", "raw"}


def test_every_integer_is_written_as_a_string(tmp_path):
    landing.JsonlSink(tmp_path).write_batch(FIRST)
    (path,) = tmp_path.iterdir()
    decoded = json.loads(path.read_text().splitlines()[0])["decoded"]
    for name in ("amount0", "amount1", "sqrt_price_x96", "liquidity", "tick", "block_number"):
        assert isinstance(decoded[name], str), name
    assert not any(isinstance(v, int | float) for v in decoded.values())


def test_round_trip_is_lossless_including_the_extreme_values(tmp_path):
    whole = batch_of(RAW)
    landing.JsonlSink(tmp_path).write_batch(whole)
    assert list(landing.read_landing(tmp_path)) == list(whole.swaps)
    biggest = max(whole.swaps, key=lambda s: abs(s.amount1))
    assert abs(biggest.amount1) > 2**63, "the fixtures hold an amount that overflows Int64"


def test_decoding_can_be_redone_from_the_raw_logs_alone(tmp_path):
    landing.JsonlSink(tmp_path).write_batch(FIRST)
    (path,) = tmp_path.iterdir()
    vandalised = [json.loads(line) for line in path.read_text().splitlines()]
    for line in vandalised:
        line["decoded"]["amount0"] = "0"  # pretend the old decoder had a bug
    path.write_text("".join(json.dumps(line) + "\n" for line in vandalised))
    assert all(s.amount0 == 0 for s in landing.read_landing(tmp_path))
    assert list(landing.read_landing(tmp_path, redecode=True)) == list(FIRST.swaps)


def test_a_batch_without_swaps_still_leaves_an_empty_file(tmp_path):
    landing.JsonlSink(tmp_path).write_batch(Batch(100, 199, (), ()))
    assert files(tmp_path) == [landing.file_name(100, 199)]
    assert landing.check_coverage(tmp_path) == (100, 199)
    assert list(landing.read_landing(tmp_path)) == []


# --- idempotency ------------------------------------------------------------------


def test_writing_the_same_range_twice_neither_duplicates_nor_changes_a_byte(tmp_path):
    sink = landing.JsonlSink(tmp_path)
    sink.write_batch(FIRST)
    (path,) = tmp_path.iterdir()
    before = path.read_bytes()
    sink.write_batch(FIRST)
    assert files(tmp_path) == [path.name]
    assert path.read_bytes() == before
    assert len(list(landing.read_landing(tmp_path))) == 40


def test_a_redelivered_batch_replaces_a_damaged_file(tmp_path):
    sink = landing.JsonlSink(tmp_path)
    sink.write_batch(FIRST)
    (path,) = tmp_path.iterdir()
    path.write_text("garbage\n")
    sink.write_batch(FIRST)
    assert list(landing.read_landing(tmp_path)) == list(FIRST.swaps)


def test_a_longer_redelivery_of_the_final_short_batch_replaces_it(tmp_path):
    sink = landing.JsonlSink(tmp_path)
    short = batch_of(RAW[:10], from_block=FIRST.from_block)
    sink.write_batch(short)
    longer = batch_of(RAW[:40], from_block=FIRST.from_block)
    sink.write_batch(longer)
    assert files(tmp_path) == [landing.file_name(longer.from_block, longer.to_block)]
    assert len(list(landing.read_landing(tmp_path))) == 40


# --- atomicity --------------------------------------------------------------------


def test_a_crash_before_the_rename_leaves_no_file_and_no_temporary(tmp_path, monkeypatch):
    def exploding_replace(src, dst):
        raise OSError("power cut")

    monkeypatch.setattr(landing.os, "replace", exploding_replace)
    with pytest.raises(OSError, match="power cut"):
        landing.JsonlSink(tmp_path).write_batch(FIRST)
    assert files(tmp_path) == []


def test_a_crash_while_rewriting_keeps_the_previous_good_file(tmp_path, monkeypatch):
    sink = landing.JsonlSink(tmp_path)
    sink.write_batch(FIRST)
    (path,) = tmp_path.iterdir()
    before = path.read_bytes()
    real_fsync = os.fsync

    def exploding_fsync(fd):
        raise OSError("disk full")

    monkeypatch.setattr(landing.os, "fsync", exploding_fsync)
    with pytest.raises(OSError, match="disk full"):
        sink.write_batch(FIRST)
    monkeypatch.setattr(landing.os, "fsync", real_fsync)
    assert files(tmp_path) == [path.name]
    assert path.read_bytes() == before


def test_stray_temporaries_from_a_killed_process_are_ignored_by_the_reader(tmp_path):
    landing.JsonlSink(tmp_path).write_batch(FIRST)
    (tmp_path / f".{landing.file_name(1, 2)}.999.tmp").write_text("half a li")
    assert len(list(landing.read_landing(tmp_path))) == 40


# --- coverage checks ----------------------------------------------------------------


def test_gaps_and_overlaps_are_detected(tmp_path):
    sink = landing.JsonlSink(tmp_path)
    sink.write_batch(Batch(100, 199, (), ()))
    sink.write_batch(Batch(200, 299, (), ()))
    assert landing.check_coverage(tmp_path) == (100, 299)
    sink.write_batch(Batch(400, 499, (), ()))
    with pytest.raises(landing.LandingError, match="gap"):
        landing.check_coverage(tmp_path)
    (tmp_path / landing.file_name(400, 499)).unlink()
    (tmp_path / landing.file_name(250, 349)).write_text("")
    with pytest.raises(landing.LandingError, match="overlap"):
        landing.check_coverage(tmp_path)


def test_a_row_outside_its_file_range_is_rejected(tmp_path):
    wrong = Batch(1, 2, FIRST.logs, FIRST.swaps)
    landing.JsonlSink(tmp_path).write_batch(wrong)
    with pytest.raises(landing.LandingError, match="outside"):
        list(landing.read_landing(tmp_path))


def test_an_unreadable_line_names_the_file_and_line(tmp_path):
    landing.JsonlSink(tmp_path).write_batch(FIRST)
    (path,) = tmp_path.iterdir()
    with path.open("a") as fh:
        fh.write("{not json\n")
    with pytest.raises(landing.LandingError, match=rf"{path.name}:41"):
        list(landing.read_landing(tmp_path))
