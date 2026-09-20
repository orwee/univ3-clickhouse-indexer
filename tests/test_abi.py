"""Every hard-coded ABI constant must equal what keccak-256 says it is."""

import pytest
from Crypto.Hash import keccak

from univ3_indexer import abi


def keccak256_hex(text: str) -> str:
    return keccak.new(digest_bits=256, data=text.encode("ascii")).hexdigest()


def test_keccak_implementation_is_the_ethereum_one():
    """Guard against SHA3-256 (different padding). Known vector: keccak256("")."""
    assert keccak256_hex("") == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"


@pytest.mark.parametrize(("signature", "selector"), sorted(abi.SELECTORS.items()))
def test_selector_is_first_four_bytes_of_keccak(signature, selector):
    assert selector == "0x" + keccak256_hex(signature)[:8]


def test_every_selector_constant_is_covered():
    constants = {v for k, v in vars(abi).items() if k.startswith("SELECTOR_")}
    assert constants == set(abi.SELECTORS.values())


def test_swap_topic0_is_keccak_of_the_signature():
    assert abi.SWAP_TOPIC0 == "0x" + keccak256_hex(abi.SWAP_SIGNATURE)
