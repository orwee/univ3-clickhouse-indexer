"""Addresses change format in exactly one place, and mixing formats is an error."""

import re

import pytest

from univ3_indexer import addresses
from univ3_indexer.addresses import Address, MixedAddressFormat, normalize
from univ3_indexer.config import REPO_ROOT
from univ3_indexer.pools import load_pools
from univ3_indexer.swap import decode_swap

CHECKSUMMED = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"
LOWER = CHECKSUMMED.lower()


def test_normalize_gives_the_lower_case_form_whatever_comes_in():
    assert (
        normalize(CHECKSUMMED)
        == normalize(LOWER)
        == normalize(CHECKSUMMED.upper().replace("0X", "0x"))
    )
    assert str(normalize(CHECKSUMMED)) == LOWER
    assert isinstance(normalize(CHECKSUMMED), Address)


@pytest.mark.parametrize("bad", ["", "0x1234", "88e6a0c2ddd26feeb64f039a2c41296fcb3f5640", None, 5])
def test_normalize_rejects_what_is_not_an_address(bad):
    with pytest.raises(ValueError, match="not an Ethereum address"):
        normalize(bad)


def test_comparing_a_normalised_address_with_a_checksummed_one_raises():
    """The point of the module: this used to be a silent False (zero rows matched)."""
    key = normalize(CHECKSUMMED)
    with pytest.raises(MixedAddressFormat, match="normalize"):
        _ = key == CHECKSUMMED
    with pytest.raises(MixedAddressFormat):
        _ = key != CHECKSUMMED
    with pytest.raises(MixedAddressFormat):
        _ = CHECKSUMMED == key  # reflected: str defers to the subclass
    with pytest.raises(MixedAddressFormat):
        _ = key in [CHECKSUMMED]


def test_comparisons_in_the_same_format_behave_like_strings():
    key = normalize(CHECKSUMMED)
    assert key == LOWER and LOWER == key
    assert key != normalize("0x" + "ab" * 20)
    assert key != "not an address" and key != 7
    assert {key: 1}[LOWER] == 1 and LOWER in {key}
    assert sorted([normalize("0x" + "bb" * 20), normalize("0x" + "aa" * 20)])[0] == "0x" + "aa" * 20


def test_same_is_format_insensitive():
    assert addresses.same(CHECKSUMMED, LOWER)
    assert not addresses.same(CHECKSUMMED, "0x" + "00" * 20)


def test_every_pool_exposes_a_normalised_key_next_to_its_checksummed_address():
    for pool in load_pools():
        assert pool.address != pool.address.lower(), "pools.yml keeps the EIP-55 form"
        assert isinstance(pool.key, Address) and str(pool.key) == pool.address.lower()
        with pytest.raises(MixedAddressFormat):
            _ = pool.key == pool.address


def test_decoded_swaps_carry_a_normalised_pool():
    log = {
        "address": CHECKSUMMED,
        "topics": [__import__("univ3_indexer.abi", fromlist=["x"]).SWAP_TOPIC0,
                   "0x" + "00" * 12 + "11" * 20, "0x" + "00" * 12 + "22" * 20],
        "data": "0x" + "00" * 160,
        "blockNumber": "0x1", "blockHash": "0x" + "00" * 32, "transactionHash": "0x" + "00" * 32,
        "transactionIndex": "0x0", "logIndex": "0x0", "removed": False,
    }  # fmt: skip
    swap = decode_swap(log)
    assert isinstance(swap.pool, Address) and swap.pool == LOWER


# --- the source itself ------------------------------------------------------------------

SOURCES = [p for d in ("src", "scripts") for p in (REPO_ROOT / d).rglob("*.py")]
# .lower() is fine on hashes and topics, which have no second format
NOT_AN_ADDRESS = re.compile(r"topics\[0\]|blockHash|transactionHash")


def test_no_other_module_lower_cases_an_address():
    offenders = []
    for path in SOURCES:
        if path.name == "addresses.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if ".lower()" in line and not NOT_AN_ADDRESS.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "use addresses.normalize() instead of .lower():\n" + "\n".join(offenders)


def test_the_checksummed_pool_address_is_only_read_where_it_is_shown_or_normalised():
    """`Pool.address` is the EIP-55 form. Code that compares must use `Pool.key`."""
    allowed = {"src/univ3_indexer/pools.py"}
    offenders = []
    for path in SOURCES:
        relative = str(path.relative_to(REPO_ROOT))
        if relative in allowed:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"\bp(ool)?\.address\b", line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, "use pool.key for anything that is compared or stored:\n" + "\n".join(
        offenders
    )
