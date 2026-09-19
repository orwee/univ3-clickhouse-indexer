"""Decode a raw Uniswap v3 ``Swap`` log into Python integers, without loss.

Pure functions: no I/O, no floats, no rounding. Python integers are arbitrary
precision, so an int256 survives intact. What a storage layer does with these
values afterwards is a separate decision and is deliberately not made here.

Layout of the event (see abi.SWAP_SIGNATURE):

    topics[0]  keccak of the signature
    topics[1]  sender     (indexed address, left-padded to 32 bytes)
    topics[2]  recipient  (indexed address, left-padded to 32 bytes)
    data       5 words of 32 bytes:
               amount0       int256   two's complement, SIGNED
               amount1       int256   two's complement, SIGNED
               sqrtPriceX96  uint160
               liquidity     uint128
               tick          int24    sign-extended to 32 bytes, SIGNED

Sign convention, from the pool's point of view: a positive amount is what the
pool received, a negative amount is what it paid out.
"""

from __future__ import annotations

from dataclasses import dataclass

from univ3_indexer.abi import SWAP_TOPIC0
from univ3_indexer.addresses import Address, normalize

WORD = 32
_DATA_WORDS = 5

INT24_MIN, INT24_MAX = -(2**23), 2**23 - 1
UINT128_MAX = 2**128 - 1
UINT160_MAX = 2**160 - 1


class SwapDecodeError(ValueError):
    """The log is not a well-formed, canonical Swap log."""


@dataclass(frozen=True)
class Swap:
    pool: str  # lower-case 0x address of the emitting pool
    block_number: int
    block_hash: str
    block_timestamp: int | None  # seconds; not every provider includes it in a log
    tx_hash: str
    tx_index: int
    log_index: int
    sender: str
    recipient: str
    amount0: int  # signed
    amount1: int  # signed
    sqrt_price_x96: int
    liquidity: int
    tick: int  # signed


def _hex_to_bytes(value: str, what: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise SwapDecodeError(f"{what}: expected a 0x-prefixed hex string")
    try:
        return bytes.fromhex(value[2:])
    except ValueError as exc:
        raise SwapDecodeError(f"{what}: not valid hex") from exc


def decode_int(word: bytes) -> int:
    """32-byte two's complement -> signed Python int."""
    if len(word) != WORD:
        raise SwapDecodeError(f"expected a {WORD}-byte word, got {len(word)} bytes")
    return int.from_bytes(word, "big", signed=True)


def decode_uint(word: bytes) -> int:
    if len(word) != WORD:
        raise SwapDecodeError(f"expected a {WORD}-byte word, got {len(word)} bytes")
    return int.from_bytes(word, "big", signed=False)


def _topic_to_address(topic: str, what: str) -> str:
    raw = _hex_to_bytes(topic, what)
    if len(raw) != WORD or any(raw[:12]):
        raise SwapDecodeError(f"{what}: not a left-padded 20-byte address")
    return "0x" + raw[12:].hex()


def _quantity(log: dict, key: str) -> int:
    try:
        return int(log[key], 16)
    except (KeyError, TypeError, ValueError) as exc:
        raise SwapDecodeError(f"{key}: missing or not a hex quantity") from exc


def _pool_address(log: dict) -> Address:
    try:
        return normalize(log.get("address"))
    except ValueError as exc:
        raise SwapDecodeError("address: missing or not an address") from exc


def decode_swap(log: dict) -> Swap:
    """Decode one log exactly as returned by ``eth_getLogs``."""
    if log.get("removed"):
        raise SwapDecodeError("log is flagged removed=true (chain reorganisation)")

    topics = log.get("topics") or []
    if len(topics) != 3:
        raise SwapDecodeError(f"expected 3 topics, got {len(topics)}")
    if topics[0].lower() != SWAP_TOPIC0:
        raise SwapDecodeError("topics[0] is not the Swap event signature")

    data = _hex_to_bytes(log.get("data"), "data")
    if len(data) != _DATA_WORDS * WORD:
        raise SwapDecodeError(f"data: expected {_DATA_WORDS * WORD} bytes, got {len(data)}")
    words = [data[i : i + WORD] for i in range(0, len(data), WORD)]

    sqrt_price_x96 = decode_uint(words[2])
    liquidity = decode_uint(words[3])
    tick = decode_int(words[4])
    if sqrt_price_x96 > UINT160_MAX:
        raise SwapDecodeError("sqrtPriceX96 does not fit in uint160")
    if liquidity > UINT128_MAX:
        raise SwapDecodeError("liquidity does not fit in uint128")
    if not INT24_MIN <= tick <= INT24_MAX:
        raise SwapDecodeError("tick does not fit in int24")

    timestamp = log.get("blockTimestamp")
    return Swap(
        pool=_pool_address(log),
        block_number=_quantity(log, "blockNumber"),
        block_hash=str(log.get("blockHash", "")).lower(),
        block_timestamp=int(timestamp, 16) if timestamp else None,
        tx_hash=str(log.get("transactionHash", "")).lower(),
        tx_index=_quantity(log, "transactionIndex"),
        log_index=_quantity(log, "logIndex"),
        sender=_topic_to_address(topics[1], "topics[1]"),
        recipient=_topic_to_address(topics[2], "topics[2]"),
        amount0=decode_int(words[0]),
        amount1=decode_int(words[1]),
        sqrt_price_x96=sqrt_price_x96,
        liquidity=liquidity,
        tick=tick,
    )
