"""receipts.py: capped, cached, and aggregates only. No network: the node is a fake."""

import json
import re
import stat

import pytest

from univ3_indexer import receipts
from univ3_indexer.abi import SWAP_TOPIC0, TOPIC_V2_SWAP, TOPIC_WETH_DEPOSIT

POOL, SIBLING = "0x" + "ab" * 20, "0x" + "cd" * 20
ROUTER, BOT = "0x" + "11" * 20, "0x" + "22" * 20
ALICE, BOB = "0x" + "a1" * 20, "0x" + "b0" * 20


def tx(n: int) -> str:
    return "0x" + f"{n:064x}"


class FakeNode:
    def __init__(self, answers: dict):
        self.answers, self.requests_sent, self.retries = answers, 0, 0

    def call(self, method, params):
        assert method == "eth_getTransactionReceipt"
        self.requests_sent += 1
        return self.answers[params[0]]


def receipt(n, signer, to, logs, gas=100_000, price=2_000_000_000, index=5):
    return {"transactionHash": tx(n), "from": signer, "to": to, "status": "0x1", "type": "0x2",
            "gasUsed": hex(gas), "effectiveGasPrice": hex(price), "transactionIndex": hex(index),
            "logs": [{"address": a, "topics": [t]} for a, t in logs]}  # fmt: skip


def test_the_run_refuses_to_start_when_the_cap_is_too_small(tmp_path):
    node = FakeNode({tx(i): receipt(i, ALICE, ROUTER, []) for i in range(3)})
    with pytest.raises(receipts.ReceiptsError, match="refusing"):
        receipts.fetch(node, [tx(0), tx(1), tx(2)], tmp_path / "c", max_calls=2)
    assert node.requests_sent == 0, "a refused run must not have called the node at all"


def test_receipts_are_cached_privately_and_never_fetched_twice(tmp_path):
    node = FakeNode({tx(i): receipt(i, ALICE, ROUTER, []) for i in range(2)})
    cache = tmp_path / "c"
    first = receipts.fetch(node, [tx(0), tx(1)], cache, max_calls=10)
    assert (first["fetched"], node.requests_sent) == (2, 2)
    assert stat.S_IMODE((cache / f"{tx(0)}.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(cache.stat().st_mode) == 0o700
    second = receipts.fetch(node, [tx(0), tx(1)], cache, max_calls=10)
    assert (second["fetched"], second["cached_before"], node.requests_sent) == (0, 2, 2)


def test_a_receipt_for_another_transaction_is_rejected(tmp_path):
    node = FakeNode({tx(0): receipt(99, ALICE, ROUTER, [])})
    with pytest.raises(receipts.ReceiptsError, match="another transaction"):
        receipts.fetch(node, [tx(0)], tmp_path / "c", max_calls=10)


ROWS = [
    {"tx": tx(0), "swaps": 1, "gross_usd": 100.0, "net_usd": 100.0, "swap_senders": [ROUTER]},
    {"tx": tx(1), "swaps": 2, "gross_usd": 300.0, "net_usd": 10.0, "swap_senders": [BOT]},
    {"tx": tx(2), "swaps": 1, "gross_usd": 600.0, "net_usd": 600.0, "swap_senders": [ROUTER]},
]
RECEIPTS = {
    tx(0): receipt(0, ALICE, ROUTER, [(POOL, SWAP_TOPIC0)], index=0),
    tx(1): receipt(1, BOB, BOT, [(POOL, SWAP_TOPIC0), (POOL, SWAP_TOPIC0),
                                 (SIBLING, SWAP_TOPIC0), ("0x" + "77" * 20, TOPIC_V2_SWAP)]),
    tx(2): receipt(2, ALICE, ROUTER, [(POOL, SWAP_TOPIC0), ("0x" + "88" * 20, TOPIC_WETH_DEPOSIT)],
                   index=1),
}  # fmt: skip


def test_the_summary_counts_what_the_receipts_show():
    s = receipts.summarize(POOL, ROWS, RECEIPTS, {POOL: "A 0.05%", SIBLING: "A 0.01%"})
    assert s["transactions"] == 3 and s["swaps_in_this_pool"] == 4
    assert s["gross_usd"] == 1000.0 and s["net_usd_within_each_transaction"] == 710.0
    assert s["transactions_with_more_than_one_swap_here"] == 1
    assert (s["their_gross_usd"], s["their_net_usd"]) == (300.0, 10.0)
    assert s["distinct_signers"] == 2
    assert s["top1_signer_share_of_usd"] == pytest.approx(70.0)  # ALICE: 100 + 600 of 1,000
    assert s["top1_signer_share_of_transactions"] == pytest.approx(200 / 3)
    assert s["contract_called_is_the_swap_sender"] == 3
    assert s["v3_swap_logs_per_transaction"] == {"1": 2, "3": 1}
    assert s["swaps_of_this_pool_per_transaction"] == {"1": 2, "2": 1}
    touched = s["transactions_that_also_touch"]
    assert touched["another tracked pool"] == 1 and touched["a v2-style pair"] == 1
    assert touched["a WETH wrap or unwrap"] == 1
    assert touched["nothing but this pool and token transfers"] == 1
    usd = s["usd_of_transactions_that_also_touch"]
    assert usd["another tracked pool"] == 300.0 and usd["a WETH wrap or unwrap"] == 600.0
    assert usd["nothing but this pool and token transfers"] == 100.0
    assert s["usd_in_the_first_three_slots"] == 700.0  # positions 0 and 1: tx 0 and tx 2
    assert s["transactions_in_the_first_three_slots"] == 2
    assert s["fees_paid_eth"] == pytest.approx(3 * 100_000 * 2e9 / 1e18)


def test_the_summary_refuses_a_transaction_without_its_receipt():
    with pytest.raises(receipts.ReceiptsError, match="no cached receipt"):
        receipts.summarize(POOL, ROWS, {tx(0): RECEIPTS[tx(0)]}, {})


def test_the_report_names_no_account_and_no_transaction():
    import datetime

    s = receipts.summarize(POOL, ROWS, RECEIPTS, {POOL: "A 0.05%", SIBLING: "A 0.01%"})
    text = receipts.render("A 0.05%", datetime.date(2026, 8, 19), 15, s, "note")
    assert not re.search(r"0x[0-9a-fA-F]{8,}", text), "an address or a hash reached the report"
    assert "A 0.05%, 2026-08-19, 15:00-16:00 UTC" in text
    assert json.dumps(s).count("0x") == 0, "the JSON summary must be aggregates only too"


def test_the_transactions_of_the_hour_come_from_raw_swaps(clickhouse, temp_database):
    """Two swaps of one transaction and one of another inside the hour, one just outside it."""
    import datetime

    from univ3_indexer import clickhouse as ch
    from univ3_indexer import loader
    from univ3_indexer.pools import load_pools

    pool = next(p.key for p in load_pools() if p.token0 == "USDC")  # USDC is token0: 6 decimals
    day = datetime.date(2026, 8, 19)

    def row(minute_of_day, tx_byte, log_index, usdc):
        when = datetime.datetime.combine(day, datetime.time(0), tzinfo=datetime.UTC)
        when += datetime.timedelta(minutes=minute_of_day)
        sender = b"\x05" * 20
        return [pool, 1000 + log_index, when, bytes([tx_byte]) * 32, log_index, sender, sender,
                int(usdc * 1e6), -1, 2**96, 10**18, 0]  # fmt: skip

    ch.apply_ddl(clickhouse, temp_database)
    rows = [row(15 * 60 + 1, 1, 0, 1_000), row(15 * 60 + 1, 1, 1, -900),
            row(15 * 60 + 30, 2, 2, 50), row(16 * 60, 3, 3, 7)]  # fmt: skip
    clickhouse.insert(ch.qualified(temp_database), rows, column_names=loader.COLUMNS)
    got = receipts.transactions(clickhouse, temp_database, pool, day, 15)
    assert [r["swaps"] for r in got] == [2, 1], "16:00 belongs to the next hour"
    first = got[0]
    assert first["tx"] == "0x" + "01" * 32
    assert first["gross_usd"] == pytest.approx(1_900) and first["net_usd"] == pytest.approx(100)
