"""The loader enforces the schema, and the committed pools.yml passes it."""

import pytest
from Crypto.Hash import keccak

from univ3_indexer import pools

GOOD = """
pools:
  - address: "0x00000000000000000000000000000000000000AA"
    token0: AAA
    token1: BBB
    decimals0: 6
    decimals1: 18
    fee: 500
    label: "AAA/BBB 0.05%"
"""


def eip55(address: str) -> str:
    raw = address.lower().removeprefix("0x")
    digest = keccak.new(digest_bits=256, data=raw.encode("ascii")).hexdigest()
    return "0x" + "".join(c.upper() if int(digest[i], 16) >= 8 else c for i, c in enumerate(raw))


def write(tmp_path, text):
    path = tmp_path / "pools.yml"
    path.write_text(text)
    return path


def test_loads_a_well_formed_file(tmp_path):
    (pool,) = pools.load_pools(write(tmp_path, GOOD))
    assert (pool.token0, pool.token1, pool.decimals0, pool.decimals1, pool.fee) == (
        "AAA",
        "BBB",
        6,
        18,
        500,
    )


def test_empty_list_is_allowed(tmp_path):
    assert pools.load_pools(write(tmp_path, "pools: []\n")) == []


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("fee: 500", "fee: 501", "fee 501"),
        ("decimals0: 6", "decimals0: six", "decimals0"),
        ('    label: "AAA/BBB 0.05%"\n', "", "expected exactly the fields"),
        ("fee: 500", "fee: 500\n    chain: mainnet", "expected exactly the fields"),
        ('"0x00000000000000000000000000000000000000AA"', '"0x1234"', "address"),
        # unquoted, YAML reads a hex literal as an integer and the address is destroyed
        ('"0x00000000000000000000000000000000000000AA"', "0x00000000000000AA", "address"),
    ],
)
def test_schema_violations_are_rejected(tmp_path, old, new, message):
    assert old in GOOD
    with pytest.raises(pools.PoolsFileError, match=message):
        pools.load_pools(write(tmp_path, GOOD.replace(old, new)))


def test_duplicate_address_is_rejected_case_insensitively(tmp_path):
    second = GOOD.split("pools:\n")[1].replace("AA", "aa", 1)
    with pytest.raises(pools.PoolsFileError, match="listed twice"):
        pools.load_pools(write(tmp_path, GOOD + second))


def test_committed_pools_file_is_valid_and_checksummed():
    for pool in pools.load_pools():
        assert pool.address == eip55(pool.address), f"{pool.label}: address is not EIP-55"
