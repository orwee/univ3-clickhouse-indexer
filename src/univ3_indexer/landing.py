"""Raw landing zone: one JSONL file per batch of blocks.

Why it exists: the backfill costs ~21,600 provider calls. Landing the result on
disk first means ClickHouse can be loaded, dropped and reloaded as many times
as the schema changes, at zero calls. It also turns the runner's at-least-once
delivery into an idempotent load, because the unit of delivery is a FILE NAMED
AFTER ITS BLOCK RANGE: delivering a batch again rewrites the same file.

One line per Swap log::

    {"decoded": {...}, "raw": {...}}

``raw`` is the log exactly as the node returned it, so decoding can be redone
later without going back to the provider. ``decoded`` is ``swap.Swap`` with
every integer written as a STRING: amounts are int256 and would be silently
mangled by any JSON reader that goes through a float (2**53 limit).

A file exists for every batch, including batches with no swaps (empty file):
the set of file names proves which blocks were fetched.

File size. The CLI's default batch is 100 chunks = 1,000 blocks (`run_backfill` itself
defaults to 50): ~4,000 rows and
~6 MB per file, ~216 files for 30 days. Small enough that a crash loses at most
100 calls (~20 s at 5 calls per second) and a batch fits in memory trivially;
large enough not to litter the directory with tens of thousands of files.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

from univ3_indexer.backfill import Batch
from univ3_indexer.swap import Swap, decode_swap

_NAME = re.compile(r"swaps_(\d{10})_(\d{10})\.jsonl")
_INT_FIELDS = tuple(f.name for f in dataclasses.fields(Swap) if f.type in ("int", "int | None"))


class LandingError(RuntimeError):
    """The landing directory is not a clean, gap-free sequence of batches."""


def file_name(from_block: int, to_block: int) -> str:
    return f"swaps_{from_block:010d}_{to_block:010d}.jsonl"


def encode_swap(swap: Swap) -> dict:
    record = dataclasses.asdict(swap)
    for name in _INT_FIELDS:
        if record[name] is not None:
            record[name] = str(record[name])
    return record


def decode_record(record: dict) -> Swap:
    values = dict(record)
    for name in _INT_FIELDS:
        if values[name] is not None:
            values[name] = int(values[name])
    return Swap(**values)


class JsonlSink:
    """Implements ``backfill.Sink``. Atomic per file, idempotent per block range."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def write_batch(self, batch: Batch) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        final = self.directory / file_name(batch.from_block, batch.to_block)
        temporary = self.directory / f".{final.name}.{os.getpid()}.tmp"
        try:
            with temporary.open("w", encoding="utf-8") as fh:
                for raw, swap in zip(batch.logs, batch.swaps, strict=True):
                    line = {"decoded": encode_swap(swap), "raw": raw}
                    fh.write(json.dumps(line, separators=(",", ":"), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, final)  # atomic: readers see the old file or the new one
        finally:
            temporary.unlink(missing_ok=True)
        self._fsync_directory()
        # A short final batch can come back later with a larger end block (the
        # chain moved on). The new file is a superset: drop the one it replaces.
        for other in self.directory.glob(f"swaps_{batch.from_block:010d}_*.jsonl"):
            if other != final:
                other.unlink()

    def _fsync_directory(self) -> None:
        fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def landed_files(directory: Path) -> list[tuple[int, int, Path]]:
    """(from_block, to_block, path), sorted. Stray temporaries are ignored."""
    found = []
    for path in Path(directory).iterdir():
        match = _NAME.fullmatch(path.name)
        if match:
            found.append((int(match[1]), int(match[2]), path))
    return sorted(found)


def check_coverage(directory: Path) -> tuple[int, int] | None:
    """Raise unless the files form one contiguous, non-overlapping block range."""
    files = landed_files(directory)
    if not files:
        return None
    for (_, previous_to, previous), (next_from, _, following) in zip(
        files, files[1:], strict=False
    ):
        if next_from <= previous_to:
            raise LandingError(f"overlap between {previous.name} and {following.name}")
        if next_from != previous_to + 1:
            raise LandingError(f"gap between {previous.name} and {following.name}")
    return files[0][0], files[-1][1]


def read_landing(directory: Path, *, redecode: bool = False) -> Iterator[Swap]:
    """Every landed swap, in block order, after checking coverage.

    With ``redecode=True`` the stored decoded form is ignored and each swap is
    decoded again from its raw log: the way to apply a fixed decoder to data
    that is already on disk.
    """
    check_coverage(directory)
    for from_block, to_block, path in landed_files(directory):
        with path.open(encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                try:
                    record = json.loads(line)
                    swap = (
                        decode_swap(record["raw"]) if redecode else decode_record(record["decoded"])
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    raise LandingError(f"{path.name}:{number}: unreadable line") from exc
                if not from_block <= swap.block_number <= to_block:
                    raise LandingError(f"{path.name}:{number}: block outside the file's range")
                yield swap
