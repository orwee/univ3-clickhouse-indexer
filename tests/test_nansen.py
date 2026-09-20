"""The Nansen client spends credits: these tests are about not spending them by accident.

Every response here is synthetic. No test reaches the network, and none needs an API key.
"""

import datetime
import json
import logging
import re

import pytest
import requests

from univ3_indexer import clickhouse as ch
from univ3_indexer import landing, loader, nansen

from .test_loader import RAW, make_landing

KEY = "synthetic-key-that-must-never-show-up"  # noqa: S105 - not a secret, a marker to search for
UTC = datetime.UTC


def trade(tx_hash, when="2026-09-20T10:00:00", chain="ethereum", value=1234.5):
    return {
        "chain": chain,
        "block_timestamp": when,
        "transaction_hash": tx_hash,
        "trader_address": "0x" + "ab" * 20,
        "trader_address_label": "Synthetic Fund",
        "token_bought_address": "0x" + "01" * 20,
        "token_sold_address": "0x" + "02" * 20,
        "token_bought_symbol": "AAA",
        "token_sold_symbol": "BBB",
        "token_bought_age_days": 1,
        "token_sold_age_days": 2,
        "trade_value_usd": value,
    }


def body(trades, is_last_page=True):
    return json.dumps(
        {"data": trades, "pagination": {"page": 1, "per_page": 1000, "is_last_page": is_last_page}}
    )


class FakeResponse:
    def __init__(self, status=200, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def post(self, url, json, headers, timeout):  # noqa: A002 - the requests signature
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def client(session, max_credits=8):
    budget = nansen.CreditBudget(max_credits)
    return nansen.NansenClient(KEY, budget, session=session), budget


HASH_A, HASH_B = "0x" + "aa" * 32, "0x" + "bb" * 32
CREDIT_HEADERS = {
    "X-Nansen-Credits-Cost": "5",
    "X-Nansen-Credits-Used": "5",
    "X-Nansen-Credits-Remaining": "95",
}

# --- the documented cost and the budget -----------------------------------------------------------


def test_the_documented_cost_is_the_one_read_in_the_official_table():
    assert nansen.DOCUMENTED_COST == {"smart-money/dex-trades": 5}
    assert nansen.DEFAULT_BUDGET == 8, "the ceiling Roberto set"


def test_one_call_fits_in_eight_credits_and_a_second_is_refused_before_it_is_sent():
    session = FakeSession(FakeResponse(200, body([trade(HASH_A)]), CREDIT_HEADERS))
    api, budget = client(session)
    api.smart_money_dex_trades_raw()
    assert budget.spent == 5
    with pytest.raises(nansen.BudgetExceeded):
        api.smart_money_dex_trades_raw(page=2)
    assert len(session.calls) == 1, "the refused call never left"


def test_a_budget_under_the_documented_cost_sends_nothing():
    session = FakeSession()
    api, _ = client(session, max_credits=4)
    with pytest.raises(nansen.BudgetExceeded):
        api.smart_money_dex_trades_raw()
    assert session.calls == []


def test_the_credits_the_api_says_it_deducted_are_the_ones_recorded():
    dearer = {**CREDIT_HEADERS, "X-Nansen-Credits-Used": "7"}
    api, budget = client(FakeSession(FakeResponse(200, body([]), dearer)))
    raw = api.smart_money_dex_trades_raw()
    assert (raw.credits_cost, raw.credits_used, raw.credits_remaining) == (5, 7, 95)
    assert budget.spent == 7


def test_without_credit_headers_a_success_is_booked_at_the_documented_cost():
    api, budget = client(FakeSession(FakeResponse(200, body([]), {})))
    assert api.smart_money_dex_trades_raw().credits_used == 5 and budget.spent == 5


# --- no retries -----------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 403])
def test_an_error_status_is_never_retried(status):
    error = json.dumps({"code": "rate_limit_exceeded", "message": "x"})
    session = FakeSession(FakeResponse(status, error, {"X-Nansen-Credits-Used": "0"}))
    api, budget = client(session)
    with pytest.raises(nansen.NansenError, match=f"HTTP {status}"):
        api.smart_money_dex_trades_raw()
    assert len(session.calls) == 1 and budget.spent == 0


def test_a_network_failure_is_not_retried_and_is_booked_as_if_billed():
    session = FakeSession(requests.ConnectionError(f"boom apikey={KEY}"))
    api, budget = client(session)
    with pytest.raises(nansen.NansenError) as caught:
        api.smart_money_dex_trades_raw()
    assert len(session.calls) == 1 and budget.spent == 5
    assert KEY not in str(caught.value) and caught.value.__cause__ is None


# --- the request and the key ------------------------------------------------------------------


def test_request_shape():
    session = FakeSession(FakeResponse(200, body([]), CREDIT_HEADERS))
    client(session)[0].smart_money_dex_trades_raw()
    (call,) = session.calls
    assert call["url"] == "https://api.nansen.ai/api/v1/smart-money/dex-trades"
    assert call["headers"]["apikey"] == KEY
    assert call["json"] == {
        "chains": ["ethereum"],
        "pagination": {"page": 1, "per_page": 1000},
        "order_by": [{"field": "block_timestamp", "direction": "DESC"}],
    }
    assert call["timeout"]


@pytest.mark.parametrize("per_page, page", [(0, 1), (1001, 1), (10, 0)])
def test_bad_pagination_is_refused_before_spending(per_page, page):
    session = FakeSession()
    with pytest.raises(ValueError, match="per_page"):
        client(session)[0].smart_money_dex_trades_raw(per_page=per_page, page=page)
    assert session.calls == []


def test_the_key_reaches_neither_the_cache_nor_the_log(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    session = FakeSession(FakeResponse(200, body([trade(HASH_A)]), CREDIT_HEADERS))
    path = nansen.fetch(client(session)[0], tmp_path / "nansen")
    assert KEY not in path.read_text() and KEY not in caplog.text
    assert path.stat().st_mode & 0o077 == 0, "the raw response names wallets: owner only"
    envelope = json.loads(path.read_text())
    assert envelope["credits"] == {"documented": 5, "quoted": 5, "used": 5, "remaining": 95}
    assert envelope["request"]["chains"] == ["ethereum"]


def test_an_empty_key_is_refused():
    with pytest.raises(nansen.NansenError):
        nansen.NansenClient("", nansen.CreditBudget(8))


# --- the cache is what stops a second spend --------------------------------------------------


def test_fetch_refuses_to_call_when_a_response_is_cached(tmp_path):
    first = FakeSession(FakeResponse(200, body([trade(HASH_A)]), CREDIT_HEADERS))
    nansen.fetch(client(first)[0], tmp_path)
    second = FakeSession()
    with pytest.raises(nansen.NansenError, match="already cached"):
        nansen.fetch(client(second)[0], tmp_path)
    assert second.calls == []


def test_a_failed_call_caches_nothing(tmp_path):
    api, _ = client(FakeSession(FakeResponse(500, "{}", {})))
    with pytest.raises(nansen.NansenError):
        nansen.fetch(api, tmp_path)
    assert nansen.cached_files(tmp_path) == []


# --- parsing ------------------------------------------------------------------------------------


def test_parse_keeps_ethereum_trades_and_the_hash_in_one_form():
    mixed_case = "0x" + "aB" * 32
    trades, last = nansen.parse_trades(
        body(
            [
                trade(mixed_case),
                trade(HASH_B, chain="base"),
                trade(HASH_B, "2026-09-20T11:00:00Z", value=None),
            ],
            False,
        )
    )
    assert [t.tx_hash for t in trades] == ["ab" * 32, "bb" * 32] and last is False
    assert trades[0].timestamp == datetime.datetime(2026, 9, 20, 10, tzinfo=UTC)
    assert trades[1].timestamp == datetime.datetime(2026, 9, 20, 11, tzinfo=UTC)
    assert trades[1].value_usd is None


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{}",
        json.dumps({"data": {}}),
        body([{"chain": "ethereum"}]),
        body([trade("0x1234")]),
        body([trade(HASH_A, when="yesterday")]),
    ],
)
def test_malformed_responses_are_refused(text):
    with pytest.raises(nansen.NansenError):
        nansen.parse_trades(text)


# --- the cross, against a throw-away database -------------------------------------------------


@pytest.fixture
def loaded(clickhouse, temp_database, tmp_path):
    ch.apply_ddl(clickhouse, temp_database)
    make_landing(tmp_path, pieces=1)
    rows = [
        row for _, _, path in landing.landed_files(tmp_path) for row in loader.rows_of_file(path)
    ]
    clickhouse.insert(ch.qualified(temp_database), rows, column_names=loader.COLUMNS)
    return temp_database


def fixture_times():
    stamps = [int(e["blockTimestamp"], 16) for e in RAW]
    return (
        datetime.datetime.fromtimestamp(min(stamps), UTC),
        datetime.datetime.fromtimestamp(max(stamps), UTC),
    )


def envelope(trades, is_last_page=True):
    return {
        "fetched_at": "2026-09-20T12:00:00+00:00",
        "endpoint": nansen.ENDPOINT,
        "credits": {"documented": 5, "quoted": 5, "used": 5, "remaining": 95},
        "response": json.loads(body(trades, is_last_page)),
    }


def test_the_cross_counts_every_swap_of_a_named_transaction_and_nothing_else(clickhouse, loaded):
    first, last = fixture_times()
    by_tx = {}
    for entry in RAW:
        by_tx.setdefault(entry["transactionHash"], []).append(entry)
    several = next(h for h, logs in by_tx.items() if len(logs) > 1)
    single = next(h for h, logs in by_tx.items() if len(logs) == 1)
    iso = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
    result = nansen.cross(
        clickhouse,
        loaded,
        envelope(
            [
                trade(several, iso(last)),
                trade(single, iso(first)),
                trade(single, iso(first)),  # the same transaction listed twice
                trade(HASH_A, iso(first)),  # a transaction that is not ours
                trade(HASH_B, iso(last + datetime.timedelta(hours=1))),  # newer than our data
            ]
        ),
    )
    assert (result.trades, result.transactions, result.trades_after_our_data) == (5, 4, 1)
    assert (result.window_from, result.window_to) == (first, last)
    assert (result.transactions_in_window, result.transactions_found) == (3, 2)
    assert sum(r["swaps"] for r in result.pools) == len(RAW), "the window holds the whole fixture"
    assert sum(r["named_swaps"] for r in result.pools) == len(by_tx[several]) + 1
    direct = clickhouse.command(
        f"SELECT count() FROM {ch.qualified(loaded)} WHERE lower(hex(tx_hash)) IN "
        f"('{several[2:]}', '{single[2:]}')"
    )
    assert direct == len(by_tx[several]) + 1
    for row in result.pools:
        assert 0 <= row["named_volume_usd"] <= row["volume_usd"]
        assert row["pool"] != row["pool_address"], "labelled from pools.yml"


def test_an_empty_cross_is_a_result_not_an_error(clickhouse, loaded):
    first, _ = fixture_times()
    result = nansen.cross(
        clickhouse, loaded, envelope([trade(HASH_A, first.strftime("%Y-%m-%dT%H:%M:%S"))])
    )
    assert result.transactions_found == 0 and sum(r["named_swaps"] for r in result.pools) == 0
    assert sum(r["swaps"] for r in result.pools) > 0, "our side of the window is still reported"
    text = nansen.render(result)
    assert "0.0000%" in text


def test_a_response_without_trades_renders_without_a_table(clickhouse, loaded):
    result = nansen.cross(clickhouse, loaded, envelope([]))
    assert result.pools == [] and "Nothing to cross" in nansen.render(result)


def test_the_report_carries_no_hash_address_or_label(clickhouse, loaded):
    first, last = fixture_times()
    named = RAW[0]["transactionHash"]
    text = nansen.render(
        nansen.cross(
            clickhouse, loaded, envelope([trade(named, last.strftime("%Y-%m-%dT%H:%M:%S"))])
        )
    )
    assert named[2:12] not in text and "ab" * 20 not in text and "Synthetic Fund" not in text
    assert not re.search(r"0x[0-9a-fA-F]{40}", text), "not even a pool address"
