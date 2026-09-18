"""Swap decoding, tested against ~200 real mainnet logs and hand-built edge cases.

The fixture file holds raw ``eth_getLogs`` response bodies exactly as the
provider returned them. Several checks below do not depend on my reading of the
ABI: they are relations the protocol guarantees between independently decoded
fields, so a sign or offset mistake in one field breaks them.
"""

import json
from decimal import Decimal, getcontext
from pathlib import Path

import pytest

from univ3_indexer import abi
from univ3_indexer.pools import load_pools
from univ3_indexer.swap import Swap, SwapDecodeError, decode_int, decode_swap

getcontext().prec = 80
FIXTURES = Path(__file__).parent / "fixtures" / "swap_logs.json"
POOLS = {p.address.lower(): p for p in load_pools()}
Q96 = Decimal(2**96)
TICK_BASE = Decimal("1.0001")


def raw_logs() -> list[dict]:
    responses = json.loads(FIXTURES.read_text())
    return [log for response in responses for log in response["result"]]


LOGS = raw_logs()
SWAPS = [decode_swap(log) for log in LOGS]


def price(swap: Swap) -> Decimal:
    """token1 per token0, in raw units, from sqrtPriceX96."""
    return (Decimal(swap.sqrt_price_x96) / Q96) ** 2


# --- the fixtures themselves ------------------------------------------------


def test_fixtures_are_raw_json_rpc_responses():
    responses = json.loads(FIXTURES.read_text())
    assert all(set(r) == {"jsonrpc", "id", "result"} for r in responses)
    assert 150 <= len(LOGS) <= 300


def test_fixtures_cover_every_pool_in_pools_yml():
    assert {s.pool for s in SWAPS} == set(POOLS)


def test_topic0_constant_matches_every_real_log():
    assert {log["topics"][0] for log in LOGS} == {abi.SWAP_TOPIC0}


# --- decoding against real logs ---------------------------------------------


def test_every_real_log_decodes():
    assert len(SWAPS) == len(LOGS)
    assert all(isinstance(s.amount0, int) and isinstance(s.amount1, int) for s in SWAPS)


def test_real_logs_include_negative_amounts_on_both_sides():
    assert any(s.amount0 < 0 for s in SWAPS)
    assert any(s.amount1 < 0 for s in SWAPS)


def test_real_logs_include_negative_and_positive_ticks():
    assert any(s.tick < 0 for s in SWAPS)
    assert any(s.tick > 0 for s in SWAPS)


def test_a_swap_never_moves_both_tokens_in_the_same_direction():
    """The pool receives one token and pays the other: signs must be opposite."""
    for s in SWAPS:
        assert s.amount0 * s.amount1 <= 0, s
        assert s.amount0 != 0 or s.amount1 != 0, s


def test_tick_sign_matches_the_economics_of_each_pair():
    """wstETH (18 dec) priced in USDC (6 dec): raw price << 1, so tick < 0.
    USDC (6 dec) priced in WETH (18 dec): raw price >> 1, so tick > 0."""
    for s in SWAPS:
        pool = POOLS[s.pool]
        if pool.decimals0 > pool.decimals1:
            assert s.tick < 0, s
        else:
            assert s.tick > 0, s


def test_tick_and_sqrt_price_agree():
    """Protocol invariant: 1.0001**tick <= price < 1.0001**(tick + 1).
    tick is decoded as a signed int24 and sqrtPriceX96 as a uint160 from
    different words, so this fails if either decoding is off."""
    for s in SWAPS:
        assert TICK_BASE**s.tick <= price(s) < TICK_BASE ** (s.tick + 1), s


def test_amount_ratio_agrees_with_the_price():
    """|amount1 / amount0| is the execution price, so it must sit close to the
    pool price after the swap. The gap is the fee plus the price impact: the
    thin wstETH/USDC 0.3% pool shows 2.2% in the fixtures, so the tolerance is
    5%. A sign, offset or word-order mistake is off by orders of magnitude, not
    by percent. Skips dust swaps where integer rounding dominates."""
    checked = 0
    for s in SWAPS:
        if min(abs(s.amount0), abs(s.amount1)) < 10_000:
            continue
        execution = Decimal(abs(s.amount1)) / Decimal(abs(s.amount0))
        assert abs(execution / price(s) - 1) < Decimal("0.05"), s
        checked += 1
    assert checked > 100


def test_human_price_is_plausible_for_usdc_weth():
    """Decimals from pools.yml + decoded price give USD per ETH in a sane range."""
    for s in SWAPS:
        pool = POOLS[s.pool]
        if (pool.token0, pool.token1) != ("USDC", "WETH"):
            continue
        weth_per_usdc = price(s) * Decimal(10) ** (pool.decimals0 - pool.decimals1)
        assert 200 < 1 / weth_per_usdc < 100_000, s


def test_metadata_fields():
    for log, s in zip(LOGS, SWAPS, strict=True):
        assert s.block_number == int(log["blockNumber"], 16)
        assert s.log_index == int(log["logIndex"], 16)
        assert s.tx_hash == log["transactionHash"].lower() and len(s.tx_hash) == 66
        assert len(s.sender) == len(s.recipient) == 42
        assert s.block_timestamp is None or s.block_timestamp > 1_600_000_000
    keys = [(s.block_hash, s.log_index) for s in SWAPS]
    assert len(set(keys)) == len(keys), "(block_hash, log_index) must identify a log"


# --- hand-built edge cases ---------------------------------------------------


def word(value: int) -> str:
    return (value % 2**256).to_bytes(32, "big").hex()


def make_log(amount0=1, amount1=-1, sqrt_price=2**96, liquidity=1, tick=0, **overrides) -> dict:
    log = {
        "address": "0x" + "ab" * 20,
        "topics": [abi.SWAP_TOPIC0, "0x" + "00" * 12 + "11" * 20, "0x" + "00" * 12 + "22" * 20],
        "data": "0x" + "".join(word(v) for v in (amount0, amount1, sqrt_price, liquidity, tick)),
        "blockNumber": "0x10",
        "blockHash": "0x" + "cd" * 32,
        "transactionHash": "0x" + "ef" * 32,
        "transactionIndex": "0x1",
        "logIndex": "0x2",
        "removed": False,
    }
    log.update(overrides)
    return log


@pytest.mark.parametrize(
    "value",
    [0, 1, -1, 2**255 - 1, -(2**255), -123456789012345678901234567890, 10**40],
)
def test_int256_round_trips_without_loss(value):
    s = decode_swap(make_log(amount0=value, amount1=-value if value > -(2**255) else 0))
    assert s.amount0 == value


def test_minus_one_is_all_ff_bytes():
    assert decode_int(bytes.fromhex("ff" * 32)) == -1
    assert decode_int(bytes.fromhex("80" + "00" * 31)) == -(2**255)
    assert decode_int(bytes.fromhex("7f" + "ff" * 31)) == 2**255 - 1


@pytest.mark.parametrize("tick", [-1, -887272, 887272, -(2**23), 2**23 - 1])
def test_signed_tick(tick):
    assert decode_swap(make_log(tick=tick)).tick == tick


def test_block_timestamp_is_optional():
    assert decode_swap(make_log()).block_timestamp is None
    assert decode_swap(make_log(blockTimestamp="0x65000000")).block_timestamp == 0x65000000


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"removed": True}, "removed"),
        ({"topics": [abi.SWAP_TOPIC0]}, "3 topics"),
        ({"topics": ["0x" + "00" * 32, "0x" + "00" * 32, "0x" + "00" * 32]}, "Swap event"),
        ({"data": "0x" + "00" * 31}, "160 bytes"),
        ({"data": "0xzz"}, "valid hex"),
        ({"data": None}, "hex string"),
        ({"blockNumber": None}, "blockNumber"),
    ],
)
def test_malformed_logs_are_rejected(overrides, message):
    with pytest.raises(SwapDecodeError, match=message):
        decode_swap(make_log(**overrides))


def test_out_of_range_values_are_rejected():
    with pytest.raises(SwapDecodeError, match="int24"):
        decode_swap(make_log(tick=2**23))
    with pytest.raises(SwapDecodeError, match="uint160"):
        decode_swap(make_log(sqrt_price=2**160))
    with pytest.raises(SwapDecodeError, match="uint128"):
        decode_swap(make_log(liquidity=2**128))
    bad_topic = make_log()
    bad_topic["topics"][1] = "0x" + "01" + "00" * 11 + "11" * 20
    with pytest.raises(SwapDecodeError, match="left-padded"):
        decode_swap(bad_topic)
