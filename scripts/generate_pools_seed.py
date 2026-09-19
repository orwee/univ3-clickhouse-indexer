"""Generate dbt/seeds/pools.csv from pools.yml, the single source of pool metadata.

    PYTHONPATH=src uv run python scripts/generate_pools_seed.py          # rewrite the seed
    PYTHONPATH=src uv run python scripts/generate_pools_seed.py --check  # exit 1 if stale

Addresses are written lower-case because that is how they are stored in the raw table;
pools.yml keeps the EIP-55 checksummed form. tests/test_pools_seed.py fails when the
committed CSV and pools.yml diverge.
"""

from __future__ import annotations

import csv
import io
import sys

from univ3_indexer.config import REPO_ROOT
from univ3_indexer.pools import load_pools

SEED = REPO_ROOT / "dbt" / "seeds" / "pools.csv"
HEADER = ["pool_address", "token0", "token1", "decimals0", "decimals1", "fee", "label"]


def render() -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    for p in sorted(load_pools(), key=lambda p: p.address.lower()):
        writer.writerow(
            [p.address.lower(), p.token0, p.token1, p.decimals0, p.decimals1, p.fee, p.label]
        )  # noqa: E501
    return out.getvalue()


def main(argv: list[str]) -> int:
    expected = render()
    if "--check" in argv:
        current = SEED.read_text(encoding="utf-8") if SEED.exists() else ""
        if current != expected:
            print(f"{SEED} is stale: run scripts/generate_pools_seed.py", file=sys.stderr)
            return 1
        return 0
    SEED.parent.mkdir(parents=True, exist_ok=True)
    SEED.write_text(expected, encoding="utf-8")
    print(f"wrote {SEED} ({expected.count(chr(10)) - 1} pools)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
