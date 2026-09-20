"""pools.yml is the single source of pool addresses. This module only reads it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from univ3_indexer.addresses import Address, normalize
from univ3_indexer.config import REPO_ROOT

POOLS_FILE = REPO_ROOT / "pools.yml"
FEE_TIERS = (100, 500, 3000, 10000)
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_FIELDS = ("address", "token0", "token1", "decimals0", "decimals1", "fee", "label")


class PoolsFileError(ValueError):
    """pools.yml does not follow its own schema."""


@dataclass(frozen=True)
class Pool:
    address: str
    token0: str
    token1: str
    decimals0: int
    decimals1: int
    fee: int
    label: str

    @property
    def key(self) -> Address:
        """The address as stored and compared everywhere outside pools.yml: lower-case."""
        return normalize(self.address)


def load_pools(path: Path = POOLS_FILE) -> list[Pool]:
    with path.open(encoding="utf-8") as fh:
        document = yaml.safe_load(fh) or {}
    entries = document.get("pools")
    if not isinstance(entries, list):
        raise PoolsFileError(f"{path}: top-level 'pools' must be a list")

    pools: list[Pool] = []
    for index, entry in enumerate(entries):
        where = f"{path}: pools[{index}]"
        if not isinstance(entry, dict) or set(entry) != set(_FIELDS):
            raise PoolsFileError(f"{where}: expected exactly the fields {', '.join(_FIELDS)}")
        pool = Pool(**entry)
        if not isinstance(pool.address, str) or not _ADDRESS.fullmatch(pool.address):
            raise PoolsFileError(f"{where}: address must be a quoted 0x + 40 hex string")
        if pool.fee not in FEE_TIERS:
            raise PoolsFileError(f"{where}: fee {pool.fee} is not one of {FEE_TIERS}")
        for name in ("decimals0", "decimals1"):
            value = getattr(pool, name)
            if not isinstance(value, int) or not 0 <= value <= 255:
                raise PoolsFileError(f"{where}: {name} must be an integer between 0 and 255")
        pools.append(pool)

    addresses = [p.key for p in pools]
    if len(set(addresses)) != len(addresses):
        raise PoolsFileError(f"{path}: the same pool address is listed twice")
    return pools
