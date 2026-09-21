"""Which landed blocks get their hash compared with the chain."""

import sys

from univ3_indexer import landing
from univ3_indexer.backfill import Batch
from univ3_indexer.config import REPO_ROOT
from univ3_indexer.swap import decode_swap

from .test_loader import RAW

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_the_last_log_of_every_file_and_the_unfinalised_tail_of_every_plan(tmp_path):
    import verify_landing_is_canonical as verify

    blocks = sorted({int(e["blockNumber"], 16) for e in RAW})
    middle = blocks[len(blocks) // 2]
    sink = landing.JsonlSink(tmp_path)
    for lo, hi in ((blocks[0], middle), (middle + 1, blocks[-1])):
        logs = tuple(e for e in RAW if lo <= int(e["blockNumber"], 16) <= hi)
        sink.write_batch(Batch(lo, hi, logs, tuple(decode_swap(e) for e in logs)))
    by_block = {int(e["blockNumber"], 16): e["blockHash"] for e in RAW}

    only_file_ends = verify.blocks_to_check(tmp_path, plan_ends=[])
    assert only_file_ends == {middle: by_block[middle], blocks[-1]: by_block[blocks[-1]]}

    with_tail = verify.blocks_to_check(tmp_path, plan_ends=[blocks[-1]])
    tail = {n for n in blocks if blocks[-1] - verify.TAIL_BLOCKS < n <= blocks[-1]}
    assert set(with_tail) == tail | {middle}
    assert all(with_tail[n] == by_block[n] for n in with_tail)
