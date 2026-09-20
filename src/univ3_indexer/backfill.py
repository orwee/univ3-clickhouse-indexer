"""Resumable backfill: RPC chunks -> batches -> a sink, with a checkpoint.

Nothing here knows where the data ends up. A ``Sink`` receives batches; the only
one is the JSONL landing zone (landing.py), and loader.py takes it from there.

Vocabulary
    chunk  one ``eth_getLogs`` call: at most 10 blocks (provider limit).
    batch  several consecutive chunks, delivered to the sink in one call.
           The checkpoint moves once per batch.

Guarantees, each covered by a test in tests/test_backfill.py
    * A batch always starts at checkpoint + 1, so a batch that is delivered
      again starts at the same block as the first time. Its end is the same
      too, except for the short final batch of a run whose end block has since
      moved forward: then the second delivery is a superset of the first.
    * Blocks are fetched exactly once per successful batch: no gap and no
      overlap between chunks, or between batches.
    * The checkpoint is saved only AFTER the sink accepted the whole batch. A
      failure while fetching or decoding any chunk of a batch delivers nothing
      and leaves the checkpoint where it was.
    * Delivery is therefore at-least-once: if the process dies after the sink
      accepted a batch but before the checkpoint was saved, that batch is
      delivered again (see the first point for its boundaries). Whether that
      produces duplicates is the sink's business, and it has what it needs to
      prevent it: the block range of the batch and a stable per-log identity.

The end block is chosen by the caller. Stay some blocks behind the chain tip
(``CONFIRMATIONS``) so that reorganised blocks are never ingested.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from univ3_indexer.abi import SWAP_TOPIC0
from univ3_indexer.addresses import normalize
from univ3_indexer.rpc import MAX_BLOCK_RANGE, chunk_ranges
from univ3_indexer.swap import Swap, decode_swap

log = logging.getLogger(__name__)

# 64 blocks = two epochs behind the tip. NOT the same as finalised: under normal conditions
# the finalised checkpoint trails the head by 64 to 95 slots, and the node is never asked for
# the `finalized` tag. Deep enough that a reorg is not a practical concern; no more than that.
CONFIRMATIONS = 64
CHECKPOINT_VERSION = 1


class BackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class Batch:
    from_block: int  # inclusive
    to_block: int  # inclusive
    logs: tuple[dict, ...]  # raw, exactly as returned by the node
    swaps: tuple[Swap, ...]  # the same logs decoded, same order


class Sink(Protocol):
    def write_batch(self, batch: Batch) -> None:
        """Persist the batch completely, or raise. Must not persist half of it."""


class GetLogs(Protocol):
    def __call__(
        self, from_block: int, to_block: int, addresses: Sequence[str], topics: Sequence[str]
    ) -> list[dict]: ...


# --- checkpoint ------------------------------------------------------------------


@dataclass(frozen=True)
class Checkpoint:
    start_block: int
    last_block: int  # last block whose batch the sink has accepted
    pools: tuple[str, ...]  # sorted lower-case addresses this backfill is about


class CheckpointStore(Protocol):
    def load(self) -> Checkpoint | None: ...
    def save(self, checkpoint: Checkpoint) -> None: ...


class FileCheckpointStore:
    """One small JSON file, replaced atomically (write temp, fsync, rename)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> Checkpoint | None:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if document.get("version") != CHECKPOINT_VERSION:
            raise BackfillError(f"{self.path}: unknown checkpoint version")
        return Checkpoint(
            start_block=int(document["start_block"]),
            last_block=int(document["last_block"]),
            pools=tuple(document["pools"]),
        )

    def save(self, checkpoint: Checkpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "version": CHECKPOINT_VERSION,
            "start_block": checkpoint.start_block,
            "last_block": checkpoint.last_block,
            "pools": list(checkpoint.pools),
            "saved_at": int(time.time()),
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, self.path)


# --- the run ---------------------------------------------------------------------


@dataclass(frozen=True)
class RunSummary:
    batches: int
    chunks: int
    logs: int
    first_block: int | None
    last_block: int | None


def _validated(logs: list[dict], from_block: int, to_block: int, pools: set[str]) -> list[dict]:
    for entry in logs:
        number = int(entry["blockNumber"], 16)
        if not from_block <= number <= to_block:
            raise BackfillError(
                f"node returned a log from block {number}, outside {from_block}-{to_block}"
            )
        if normalize(entry["address"]) not in pools:
            raise BackfillError(f"node returned a log from an unrequested address in {number}")
    return logs


def run_backfill(
    *,
    get_logs: GetLogs,
    sink: Sink,
    checkpoints: CheckpointStore,
    pools: Sequence[str],
    start_block: int,
    end_block: int,
    chunk_size: int = MAX_BLOCK_RANGE,
    chunks_per_batch: int = 50,
    decode: Callable[[dict], Swap] = decode_swap,
    on_batch: Callable[[Batch], None] | None = None,
) -> RunSummary:
    """Fetch [start_block, end_block] (inclusive), resuming from the checkpoint."""
    if chunks_per_batch < 1:
        raise ValueError("chunks_per_batch must be at least 1")
    wanted = tuple(sorted(normalize(p) for p in pools))
    if not wanted:
        raise BackfillError("no pools to index")

    checkpoint = checkpoints.load()
    if checkpoint is not None:
        if checkpoint.pools != wanted:
            raise BackfillError(
                "the checkpoint was written for a different set of pools: resuming would leave "
                "holes for the new ones. Use a new checkpoint for a new pool set."
            )
        if checkpoint.start_block != start_block:
            raise BackfillError(
                f"the checkpoint starts at block {checkpoint.start_block}, not {start_block}: "
                "blocks before the old start were never fetched, or blocks would be skipped. "
                "Use the same start block or a new checkpoint."
            )

    batch_blocks = chunk_size * chunks_per_batch
    done_through = checkpoint.last_block if checkpoint else start_block - 1

    batches = chunks = total_logs = 0
    first: int | None = None
    pool_set = set(wanted)
    for batch_from, batch_to in chunk_ranges(done_through + 1, end_block, batch_blocks):
        raw: list[dict] = []
        for chunk_from, chunk_to in chunk_ranges(batch_from, batch_to, chunk_size):
            raw.extend(
                _validated(
                    get_logs(chunk_from, chunk_to, wanted, [SWAP_TOPIC0]),
                    chunk_from,
                    chunk_to,
                    pool_set,
                )
            )
            chunks += 1
        raw.sort(key=lambda e: (int(e["blockNumber"], 16), int(e["logIndex"], 16)))
        batch = Batch(batch_from, batch_to, tuple(raw), tuple(decode(e) for e in raw))

        sink.write_batch(batch)  # may raise: then the checkpoint stays put
        checkpoints.save(Checkpoint(start_block, batch_to, wanted))

        batches += 1
        total_logs += len(raw)
        first = batch_from if first is None else first
        done_through = batch_to
        log.info("batch %d-%d: %d logs", batch_from, batch_to, len(raw))
        if on_batch:
            on_batch(batch)

    return RunSummary(batches, chunks, total_logs, first, done_through if batches else None)
