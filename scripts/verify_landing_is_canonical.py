"""Is what was landed still on the canonical chain? Reads the landing zone; changes nothing.

    PYTHONPATH=src uv run python scripts/verify_landing_is_canonical.py    (needs the Alchemy key)

Until 2026-09-21 every backfill window ended 64 blocks behind the tip, which is deep but is
not finality (the finalised block trails the head by 64 to 95 slots). A block fetched in that
gap could, in principle, have been reorganised afterwards. The landing zone keeps the raw log,
blockHash included, so this can be checked after the fact: ask the node for the hash of the
same height today and compare.

Checked: the last log of EVERY landed file, and every log-bearing block in the last 100
blocks of every plan (the part of each window that was not yet finalised when it was read).
Exit code 0 when every hash matches, 1 otherwise. One call per block checked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from univ3_indexer import config, landing
from univ3_indexer.cli import alchemy_mainnet_url
from univ3_indexer.rpc import JsonRpcClient

TAIL_BLOCKS = 100


def landed_hashes(path: Path) -> dict[int, str]:
    """block number -> blockHash of the raw logs of one landed file."""
    hashes: dict[int, str] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            raw = json.loads(line)["raw"]
            hashes[int(raw["blockNumber"], 16)] = raw["blockHash"]
    return hashes


def blocks_to_check(landing_dir: Path, plan_ends: list[int]) -> dict[int, str]:
    wanted: dict[int, str] = {}
    for first, last, path in landing.landed_files(landing_dir):
        hashes = landed_hashes(path)
        if not hashes:
            continue
        newest = max(hashes)
        wanted[newest] = hashes[newest]
        for end in plan_ends:
            if first <= end and last >= end - TAIL_BLOCKS:
                wanted.update({n: h for n, h in hashes.items() if end - TAIL_BLOCKS < n <= end})
    return wanted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--landing", type=Path, help="default: <data dir>/landing")
    parser.add_argument("--rps", type=float, default=5.0)
    args = parser.parse_args()
    data = config.data_dir()
    landing_dir = args.landing or data / "landing"
    plans = [p for p in [data / "plan.json", *sorted(data.glob("*/plan.json"))] if p.exists()]
    ends = sorted({json.loads(p.read_text())["end_block"] for p in plans})
    wanted = blocks_to_check(landing_dir, ends)
    client = JsonRpcClient(alchemy_mainnet_url(config.require_api_key("ALCHEMY_API_KEY")),
                           min_interval=1 / args.rps)  # fmt: skip
    mismatches = []
    for number in sorted(wanted):
        now = client.block_hash(number)
        if now != wanted[number]:
            mismatches.append((number, wanted[number], now))
    print(f"plans: {len(plans)} (window ends: {ends})")
    print(
        f"blocks checked: {len(wanted)} | calls: {client.requests_sent} | retries: {client.retries}"
    )
    for number, then, now in mismatches:
        print(f"REORGANISED: block {number} landed as {then}, canonical is {now}")
    print(
        "every landed block hash is canonical"
        if not mismatches
        else f"{len(mismatches)} MISMATCHES"
    )
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
