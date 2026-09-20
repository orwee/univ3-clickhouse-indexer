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


def test_the_costs_and_the_ceiling_the_client_works_with_are_pinned():
    # This cannot read Nansen's table: it pins the figures that were read there by hand, so
    # that changing one is a visible edit and not a side effect.
    assert nansen.DOCUMENTED_COST == {"smart-money/dex-trades": 5, "tgm/dex-trades": 1}
    assert nansen.DEFAULT_BUDGET == 40, "the ceiling Roberto set for the tgm/dex-trades campaign"


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


# --- tgm/dex-trades: token from pools.yml, pages cached, a ledger that outlives the process ----

WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
DAY = datetime.date(2026, 9, 1)
ONE_CREDIT = {"X-Nansen-Credits-Cost": "1", "X-Nansen-Credits-Used": "1",
              "X-Nansen-Credits-Remaining": "94"}  # fmt: skip


def tgm_trade(tx_hash, when="2026-09-01T10:00:00", value=500.0):
    return {"block_timestamp": when, "transaction_hash": tx_hash,
            "trader_address": "0x" + "cd" * 20,
            "trader_address_label": "Synthetic Smart Trader", "action": "BUY",
            "token_address": WETH, "token_name": "WETH", "token_amount": 1.0,
            "traded_token_address": "0x" + "03" * 20, "traded_token_name": "USDC",
            "traded_token_amount": 500.0, "estimated_swap_price_usd": 500.0,
            "estimated_value_usd": value}  # fmt: skip


def test_token_addresses_come_from_pools_yml_and_match_the_on_chain_evidence():
    tokens = nansen.known_token_addresses()
    assert set(tokens) == {"USDC", "WETH", "wstETH"}
    text = (nansen.POOLS_YML).read_text()
    assert all(address in text for address in tokens.values())


def test_a_token_that_is_not_in_pools_yml_is_never_queried():
    session = FakeSession()
    with pytest.raises(nansen.NansenError, match="not a token of pools.yml"):
        client(session)[0].tgm_dex_trades_raw("0x" + "99" * 20, DAY, DAY)
    assert session.calls == []


def test_tgm_request_shape_smart_money_only_whole_utc_days_oldest_first():
    session = FakeSession(FakeResponse(200, body([]), ONE_CREDIT))
    api, budget = client(session)
    api.tgm_dex_trades_raw(WETH, DAY, DAY + datetime.timedelta(days=6), page=3)
    (call,) = session.calls
    assert call["url"] == "https://api.nansen.ai/api/v1/tgm/dex-trades"
    assert call["json"] == {
        "chain": "ethereum", "token_address": WETH, "only_smart_money": True,
        "date": {"from": "2026-09-01T00:00:00Z", "to": "2026-09-07T23:59:59Z"},
        "pagination": {"page": 3, "per_page": 1000},
        "order_by": [{"field": "block_timestamp", "direction": "ASC"}],
    }  # fmt: skip
    assert budget.spent == 1


def test_an_inverted_window_is_refused_before_spending():
    session = FakeSession()
    with pytest.raises(ValueError, match="before"):
        client(session)[0].tgm_dex_trades_raw(WETH, DAY, DAY - datetime.timedelta(days=1))
    assert session.calls == []


def test_pages_are_read_until_the_last_and_a_cached_page_is_never_asked_for_again(tmp_path):
    first = FakeSession(FakeResponse(200, body([tgm_trade(HASH_A)], False), ONE_CREDIT),
                        FakeResponse(200, body([tgm_trade(HASH_B)], True), ONE_CREDIT))  # fmt: skip
    summary = nansen.fetch_tgm(client(first)[0], tmp_path, "WETH", DAY, DAY, max_pages=5)
    assert (summary["pages"], summary["called"], summary["trades"], summary["complete"]) == (
        2,
        2,
        2,
        True,
    )
    again = FakeSession()
    summary = nansen.fetch_tgm(client(again)[0], tmp_path, "WETH", DAY, DAY, max_pages=5)
    assert again.calls == [] and summary["called"] == 0 and summary["trades"] == 2
    trades, complete, pages = nansen.cached_tgm(tmp_path, "WETH", DAY, DAY)
    assert [t.tx_hash for t in trades] == ["aa" * 32, "bb" * 32] and complete and pages == 2
    for path in tmp_path.glob("*.json"):
        assert KEY not in path.read_text() and path.stat().st_mode & 0o077 == 0


def test_max_pages_stops_the_reading_and_says_it_is_not_complete(tmp_path):
    session = FakeSession(FakeResponse(200, body([tgm_trade(HASH_A)], False), ONE_CREDIT))
    summary = nansen.fetch_tgm(client(session)[0], tmp_path, "WETH", DAY, DAY, max_pages=1)
    assert summary["complete"] is False and len(session.calls) == 1


def test_the_ledger_makes_the_ceiling_outlive_the_process(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    responses = [FakeResponse(200, body([], False), ONE_CREDIT) for _ in range(3)]
    budget = nansen.CreditBudget(3, ledger, nansen.TGM_ENDPOINT)
    api = nansen.NansenClient(KEY, budget, session=FakeSession(*responses[:2]))
    api.tgm_dex_trades_raw(WETH, DAY, DAY, page=1)
    api.tgm_dex_trades_raw(WETH, DAY, DAY, page=2)
    # a new process: the two credits are still spent
    reborn = nansen.CreditBudget(3, ledger, nansen.TGM_ENDPOINT)
    assert reborn.spent == 2
    session = FakeSession(responses[2])
    later = nansen.NansenClient(KEY, reborn, session=session)
    later.tgm_dex_trades_raw(WETH, DAY, DAY, page=3)
    with pytest.raises(nansen.BudgetExceeded):
        later.tgm_dex_trades_raw(WETH, DAY, DAY, page=4)
    assert len(session.calls) == 1 and KEY not in ledger.read_text()
    other = nansen.CreditBudget(8, ledger, nansen.ENDPOINT)
    assert other.spent == 0, "each endpoint has its own ceiling"


def test_a_tgm_error_is_not_retried_and_lands_in_the_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    session = FakeSession(FakeResponse(422, json.dumps({"code": "invalid_date_range"}),
                                       {"X-Nansen-Credits-Used": "0"}))  # fmt: skip
    api = nansen.NansenClient(
        KEY, nansen.CreditBudget(40, ledger, nansen.TGM_ENDPOINT), session=session
    )
    with pytest.raises(nansen.NansenError, match="HTTP 422 invalid_date_range"):
        nansen.fetch_tgm(api, tmp_path, "WETH", DAY, DAY, max_pages=3)
    assert len(session.calls) == 1 and list(tmp_path.glob("tgm_*.json")) == []
    assert json.loads(ledger.read_text())["used"] == 0


BAD_TGM = [
    body([{"block_timestamp": "2026-09-01T10:00:00"}]),
    body([tgm_trade("0xzz")]),
    body([tgm_trade(HASH_A, when="noon")]),
]


@pytest.mark.parametrize("bad", BAD_TGM)
def test_malformed_tgm_responses_are_refused(bad):
    with pytest.raises(nansen.NansenError):
        nansen.parse_tgm_trades(bad)


# --- the daily aggregate, against a throw-away database ----------------------------------------


def fixture_by_tx():
    by_tx = {}
    for entry in RAW:
        by_tx.setdefault(entry["transactionHash"], []).append(entry)
    return by_tx


def test_the_daily_aggregate_stores_zeros_and_only_the_pools_of_the_token(clickhouse, loaded):
    first, last = fixture_times()
    weth_pools = {
        "0xe0554a476a092703abdb3ef35c80e0d76d32939f",
        "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
    }
    named = next(h for h, logs in fixture_by_tx().items() if logs[0]["address"] in weth_pools)
    trades = [nansen.Trade(named[2:], first, 1.0), nansen.Trade("aa" * 32, first, 1.0)]
    summary = nansen.store_daily(
        clickhouse, loaded, "WETH", trades, True, first.date(), last.date()
    )
    rows = clickhouse.query(
        f"SELECT pool_address, date, named_swaps, named_volume_usd, token_symbol FROM "
        f"{ch.qualified(loaded, nansen.DAILY_TABLE)} FINAL"
    ).result_rows
    assert {r[0] for r in rows} == weth_pools, "a WETH list says nothing about the wstETH pools"
    assert sum(r[2] for r in rows) == len(fixture_by_tx()[named]) == summary["named_swaps"]
    assert any(r[2] == 0 for r in rows), "a fetched day with no match is a row with a zero"
    assert {r[4] for r in rows} == {"WETH"}
    swaps = clickhouse.command(
        f"SELECT count() FROM {ch.qualified(loaded)} WHERE pool_address IN {tuple(weth_pools)}"
    )
    assert summary["pool_days"] == len(rows) and swaps > 0


def test_incomplete_pages_only_speak_for_the_whole_days_before_the_newest_trade(clickhouse, loaded):
    first, last = fixture_times()
    assert first.date() < last.date(), "the fixture spans two UTC days"
    newest = datetime.datetime.combine(last.date(), datetime.time(0, 5), tzinfo=UTC)
    nansen.store_daily(clickhouse, loaded, "WETH", [nansen.Trade("aa" * 32, newest, 1.0)], False,
                       first.date(), last.date())  # fmt: skip
    table = ch.qualified(loaded, nansen.DAILY_TABLE)
    days = {r[0] for r in clickhouse.query(f"SELECT date FROM {table} FINAL").result_rows}
    assert days == {first.date()}, "the day the pages stopped in is cut short: it gets no row"


def test_recomputing_supersedes_under_final(clickhouse, loaded):
    first, last = fixture_times()
    for _ in range(2):
        nansen.store_daily(clickhouse, loaded, "WETH", [], True, first.date(), last.date())
    table = ch.qualified(loaded, nansen.DAILY_TABLE)
    assert clickhouse.command(f"SELECT count() FROM {table} FINAL") <= clickhouse.command(
        f"SELECT count() FROM {table}"
    )
    keys = clickhouse.command(f"SELECT uniqExact(pool_address, date) FROM {table}")
    assert clickhouse.command(f"SELECT count() FROM {table} FINAL") == keys


# --- what is committed about Nansen names nobody -------------------------------------------------


@pytest.mark.parametrize("name", ["NANSEN.md", "NANSEN_CROSS.md"])
def test_the_committed_nansen_documents_carry_no_hash_and_no_address(name):
    text = (nansen.config.REPO_ROOT / "docs" / name).read_text()
    assert not re.search(r"0x[0-9a-fA-F]{40}", text), "neither a wallet nor a transaction hash"
    assert not re.search(r"\b[0-9a-fA-F]{64}\b", text)


def test_the_aggregate_table_has_no_column_that_could_hold_a_wallet_or_a_hash():
    ddl = nansen.DAILY_DDL.read_text()
    columns = re.findall(r"^\s{4}(\w+)\s+", ddl.split("(", 1)[1], flags=re.M)
    assert set(columns) == set(nansen.DAILY_COLUMNS)
    assert not {"tx_hash", "trader_address", "label", "trader_address_label"} & set(columns)
