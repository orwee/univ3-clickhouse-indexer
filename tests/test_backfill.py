"""Checkpointing and resumption, against a fake chain and an in-memory sink."""

import json
from collections import Counter

import pytest

from univ3_indexer import abi
from univ3_indexer.backfill import (
    BackfillError,
    Batch,
    Checkpoint,
    FileCheckpointStore,
    run_backfill,
)

POOL = "0x" + "ab" * 20
OTHER_POOL = "0x" + "cd" * 20


def word(value: int) -> str:
    return (value % 2**256).to_bytes(32, "big").hex()


def make_log(block: int, log_index: int, address: str = POOL) -> dict:
    return {
        "address": address,
        "topics": [abi.SWAP_TOPIC0, "0x" + "00" * 12 + "11" * 20, "0x" + "00" * 12 + "22" * 20],
        "data": "0x" + "".join(word(v) for v in (block, -block, 2**96, 1, -5)),
        "blockNumber": hex(block),
        "blockHash": "0x" + word(block),
        "transactionHash": "0x" + word(block * 1000 + log_index),
        "transactionIndex": "0x0",
        "logIndex": hex(log_index),
        "removed": False,
    }


class FakeChain:
    """Two logs in every block. Records each range it is asked for."""

    def __init__(self, fail_on_call: int | None = None, max_range: int = 10):
        self.calls: list[tuple[int, int]] = []
        self.fail_on_call = fail_on_call
        self.max_range = max_range

    def get_logs(self, from_block, to_block, addresses, topics):
        assert to_block - from_block + 1 <= self.max_range, "range wider than the provider allows"
        assert topics == [abi.SWAP_TOPIC0]
        self.calls.append((from_block, to_block))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise ConnectionError("node went away")
        return [make_log(b, i) for b in range(from_block, to_block + 1) for i in (0, 1)]

    def blocks_fetched(self) -> list[int]:
        return [b for lo, hi in self.calls for b in range(lo, hi + 1)]


class InMemorySink:
    """All-or-nothing, like a real sink must be. Plain append: it does NOT deduplicate,
    so any duplicate delivery by the runner shows up in the assertions."""

    def __init__(self, fail_on_batch: int | None = None):
        self.batches: list[Batch] = []
        self.attempts = 0
        self.fail_on_batch = fail_on_batch

    def write_batch(self, batch: Batch) -> None:
        self.attempts += 1
        if self.attempts == self.fail_on_batch:
            raise OSError("disk full")
        self.batches.append(batch)

    def identities(self) -> list[tuple[int, int]]:
        return [(s.block_number, s.log_index) for b in self.batches for s in b.swaps]


class MemoryCheckpoints:
    def __init__(self, fail_on_save: int | None = None):
        self.value: Checkpoint | None = None
        self.saves = 0
        self.fail_on_save = fail_on_save

    def load(self):
        return self.value

    def save(self, checkpoint):
        self.saves += 1
        if self.saves == self.fail_on_save:
            raise OSError("cannot write checkpoint")
        self.value = checkpoint


def run(chain, sink, checkpoints, start=1000, end=1099, chunks_per_batch=3, pools=(POOL,)):
    return run_backfill(
        get_logs=chain.get_logs,
        sink=sink,
        checkpoints=checkpoints,
        pools=pools,
        start_block=start,
        end_block=end,
        chunk_size=10,
        chunks_per_batch=chunks_per_batch,
    )


def expected_identities(start, end):
    return [(b, i) for b in range(start, end + 1) for i in (0, 1)]


# --- a clean run -----------------------------------------------------------------


def test_every_block_is_fetched_exactly_once_and_every_log_arrives_once():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    summary = run(chain, sink, checkpoints)
    assert chain.blocks_fetched() == list(range(1000, 1100))
    assert sink.identities() == expected_identities(1000, 1099)
    assert (summary.batches, summary.chunks, summary.logs) == (4, 10, 200)
    assert checkpoints.value.last_block == 1099


def test_batch_edges_are_contiguous_neither_skipped_nor_counted_twice():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    run(chain, sink, checkpoints, start=1000, end=1074)
    edges = [(b.from_block, b.to_block) for b in sink.batches]
    assert edges == [(1000, 1029), (1030, 1059), (1060, 1074)]
    for (_, previous_to), (next_from, _) in zip(edges, edges[1:], strict=False):
        assert next_from == previous_to + 1
    # logs sitting exactly on an edge land in exactly one batch
    counts = Counter(sink.identities())
    for edge_block in (1029, 1030, 1059, 1060, 1074):
        assert counts[(edge_block, 0)] == 1 and counts[(edge_block, 1)] == 1
    # and each batch holds only its own blocks
    for batch in sink.batches:
        assert all(batch.from_block <= s.block_number <= batch.to_block for s in batch.swaps)


def test_a_range_not_divisible_by_the_chunk_size_ends_exactly_at_the_end_block():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    run(chain, sink, checkpoints, start=1000, end=1003)
    assert chain.calls == [(1000, 1003)]
    assert sink.identities() == expected_identities(1000, 1003)


def test_logs_inside_a_batch_are_ordered_by_block_and_log_index():
    class ShuffledChain(FakeChain):
        def get_logs(self, *args):
            return list(reversed(super().get_logs(*args)))

    sink = InMemorySink()
    run(ShuffledChain(), sink, MemoryCheckpoints(), end=1029)
    assert sink.identities() == expected_identities(1000, 1029)


# --- resuming --------------------------------------------------------------------


def test_resuming_after_completion_does_nothing():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    run(chain, sink, checkpoints)
    calls_before = len(chain.calls)
    summary = run(chain, sink, checkpoints)
    assert (summary.batches, len(chain.calls)) == (0, calls_before)
    assert sink.identities() == expected_identities(1000, 1099)


def test_resuming_with_a_later_end_block_continues_without_duplicates():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    run(chain, sink, checkpoints, end=1044)
    run(chain, sink, checkpoints, end=1099)
    assert sink.identities() == expected_identities(1000, 1099)
    assert chain.blocks_fetched() == list(range(1000, 1100))


def test_rpc_failure_mid_batch_delivers_nothing_and_keeps_the_checkpoint():
    # batch 1 = calls 1-3, batch 2 = calls 4-6: fail on the 5th call
    chain, sink, checkpoints = FakeChain(fail_on_call=5), InMemorySink(), MemoryCheckpoints()
    with pytest.raises(ConnectionError):
        run(chain, sink, checkpoints)
    assert [(b.from_block, b.to_block) for b in sink.batches] == [(1000, 1029)]
    assert checkpoints.value.last_block == 1029  # not 1039, not 1049

    chain.fail_on_call = None
    run(chain, sink, checkpoints)
    assert sink.identities() == expected_identities(1000, 1099)  # no gap, no duplicate


def test_sink_failure_does_not_advance_the_checkpoint():
    chain, checkpoints = FakeChain(), MemoryCheckpoints()
    sink = InMemorySink(fail_on_batch=2)
    with pytest.raises(OSError, match="disk full"):
        run(chain, sink, checkpoints)
    assert checkpoints.value.last_block == 1029

    run(chain, sink, checkpoints)
    assert sink.identities() == expected_identities(1000, 1099)


def test_decode_failure_mid_batch_delivers_nothing():
    class PoisonedChain(FakeChain):
        def get_logs(self, from_block, to_block, addresses, topics):
            logs = super().get_logs(from_block, to_block, addresses, topics)
            if from_block == 1040:
                logs[0]["data"] = "0x00"
            return logs

    sink, checkpoints = InMemorySink(), MemoryCheckpoints()
    with pytest.raises(ValueError, match="160 bytes"):
        run(PoisonedChain(), sink, checkpoints)
    assert checkpoints.value.last_block == 1029
    assert sink.identities() == expected_identities(1000, 1029)


def test_crash_between_sink_and_checkpoint_redelivers_the_same_range():
    """The one window where at-least-once shows: the sink accepted batch 2 but the
    checkpoint was not saved. The runner must deliver the SAME range again, which is
    what lets a real sink recognise it. This plain-append sink shows the duplicate."""
    chain, sink = FakeChain(), InMemorySink()
    checkpoints = MemoryCheckpoints(fail_on_save=2)
    with pytest.raises(OSError, match="cannot write checkpoint"):
        run(chain, sink, checkpoints)
    assert checkpoints.value.last_block == 1029

    run(chain, sink, checkpoints)
    ranges = [(b.from_block, b.to_block) for b in sink.batches]
    assert ranges.count((1030, 1059)) == 2  # redelivered with identical boundaries
    duplicated = {k for k, n in Counter(sink.identities()).items() if n > 1}
    assert duplicated == set(expected_identities(1030, 1059))  # and nothing else


# --- refusing to resume into a hole ----------------------------------------------


def test_a_checkpoint_for_other_pools_is_refused():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    run(chain, sink, checkpoints, end=1029)
    with pytest.raises(BackfillError, match="different set of pools"):
        run(chain, sink, checkpoints, pools=(POOL, OTHER_POOL))


def test_pool_comparison_ignores_case_and_order():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    checkpoints.value = Checkpoint(1000, 1029, tuple(sorted((POOL, OTHER_POOL))))
    run(chain, sink, checkpoints, pools=(OTHER_POOL.upper().replace("0X", "0x"), POOL))
    assert checkpoints.value.last_block == 1099


def test_a_different_start_block_is_refused():
    chain, sink, checkpoints = FakeChain(), InMemorySink(), MemoryCheckpoints()
    run(chain, sink, checkpoints, end=1029)
    with pytest.raises(BackfillError, match="starts at block 1000"):
        run(chain, sink, checkpoints, start=900)


def test_logs_outside_the_requested_range_or_pool_set_are_rejected():
    class LyingChain(FakeChain):
        def get_logs(self, from_block, to_block, addresses, topics):
            return [make_log(to_block + 1, 0)]

    with pytest.raises(BackfillError, match="outside"):
        run(LyingChain(), InMemorySink(), MemoryCheckpoints())

    class WrongAddressChain(FakeChain):
        def get_logs(self, from_block, to_block, addresses, topics):
            return [make_log(from_block, 0, address=OTHER_POOL)]

    with pytest.raises(BackfillError, match="unrequested address"):
        run(WrongAddressChain(), InMemorySink(), MemoryCheckpoints())


def test_no_pools_is_an_error():
    with pytest.raises(BackfillError, match="no pools"):
        run(FakeChain(), InMemorySink(), MemoryCheckpoints(), pools=())


# --- the file store --------------------------------------------------------------


def test_file_checkpoint_round_trip_and_atomic_replace(tmp_path):
    store = FileCheckpointStore(tmp_path / "nested" / "checkpoint.json")
    assert store.load() is None
    store.save(Checkpoint(1000, 1029, (POOL,)))
    store.save(Checkpoint(1000, 1059, (POOL,)))
    assert store.load() == Checkpoint(1000, 1059, (POOL,))
    assert [p.name for p in (tmp_path / "nested").iterdir()] == ["checkpoint.json"]


def test_file_checkpoint_survives_a_restart_of_the_whole_run(tmp_path):
    path = tmp_path / "checkpoint.json"
    chain, sink = FakeChain(fail_on_call=5), InMemorySink()
    with pytest.raises(ConnectionError):
        run(chain, sink, FileCheckpointStore(path))
    assert json.loads(path.read_text())["last_block"] == 1029

    run(FakeChain(), sink, FileCheckpointStore(path))  # a brand new process, in effect
    assert sink.identities() == expected_identities(1000, 1099)


def test_unknown_checkpoint_version_is_refused(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps({"version": 99}))
    with pytest.raises(BackfillError, match="version"):
        FileCheckpointStore(path).load()
