"""GeckoTerminal client and loader, against responses recorded from the real API."""

import datetime
import json
from pathlib import Path

import pytest
import requests

from univ3_indexer import clickhouse as ch
from univ3_indexer import external
from univ3_indexer.pools import load_pools

RECORDED = Path(__file__).parent / "fixtures" / "geckoterminal"
POOLS = load_pools()
QUIET_POOL = "0x173821f6ad4c5324cd35753a9fd12d92f2eaab29"  # wstETH/USDC 0.3%


def recorded(pool_key: str) -> str:
    return (RECORDED / f"{pool_key}.json").read_text()


class FakeResponse:
    def __init__(self, status=200, text=""):
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def get(self, url, params, headers, timeout):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeTime:
    def __init__(self):
        self.now, self.sleeps = 100.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def client(session, **kwargs):
    fake = FakeTime()
    return external.GeckoTerminalClient(
        session=session, sleep=fake.sleep, clock=fake.clock, rng=lambda: 1.0, **kwargs
    ), fake


# --- the recorded responses -------------------------------------------------------------


def test_there_is_a_recorded_response_for_every_pool_in_pools_yml():
    assert {p.name for p in RECORDED.glob("*.json")} == {f"{p.key}.json" for p in POOLS}


@pytest.mark.parametrize("pool", POOLS, ids=lambda p: p.label)
def test_daily_candles_sit_on_utc_midnight(pool):
    """Observed, not documented: a daily candle starts at 00:00:00 UTC."""
    rows = external.parse_daily(pool.key, recorded(pool.key))
    assert len(rows) > 150
    assert {r.timestamp % 86400 for r in rows} == {0}
    assert all(
        r.date == datetime.datetime.fromtimestamp(r.timestamp, datetime.UTC).date() for r in rows
    )
    assert [r.date for r in rows] == sorted({r.date for r in rows}), "ascending, one row per day"
    assert all(r.volume_usd >= 0 and r.close_usd > 0 for r in rows)
    assert all(r.pool_address == pool.key for r in rows)


def test_the_source_really_repeats_a_candle_and_it_is_kept_once(caplog):
    raw = json.loads(recorded(QUIET_POOL))["data"]["attributes"]["ohlcv_list"]
    stamps = [c[0] for c in raw]
    assert len(stamps) - len(set(stamps)) == 1, "the recorded response holds the duplicate"
    rows = external.parse_daily(QUIET_POOL, recorded(QUIET_POOL))
    assert len(rows) == len(set(stamps))
    assert "repeated the candle" in caplog.text


def test_two_different_candles_for_one_day_are_refused():
    body = json.loads(recorded(QUIET_POOL))
    candles = body["data"]["attributes"]["ohlcv_list"]
    candles.append([candles[0][0], 1, 1, 1, 1, candles[0][5] + 1000])
    with pytest.raises(external.ExternalSourceError, match="two DIFFERENT candles"):
        external.parse_daily(QUIET_POOL, json.dumps(body))


def test_the_quiet_pool_has_days_the_source_does_not_list():
    """GeckoTerminal omits days without trades: a missing day is not a zero."""
    rows = external.parse_daily(QUIET_POOL, recorded(QUIET_POOL))
    span = (rows[-1].date - rows[0].date).days + 1
    assert len(rows) < span


@pytest.mark.parametrize(
    "body", ["not json", "{}", '{"data": {"attributes": {"ohlcv_list": [[1, 2]]}}}']
)
def test_malformed_responses_are_refused(body):
    with pytest.raises(external.ExternalSourceError):
        external.parse_daily(QUIET_POOL, body)


# --- the client ---------------------------------------------------------------------------


def test_request_shape_version_header_and_timeouts():
    session = FakeSession(FakeResponse(200, recorded(QUIET_POOL)))
    gecko, _ = client(session)
    gecko.daily_ohlcv_raw(POOLS[0].address)  # EIP-55 in, lower-case out
    (call,) = session.calls
    assert call["url"].endswith(f"/networks/eth/pools/{POOLS[0].key}/ohlcv/day")
    assert call["params"] == {"aggregate": 1, "limit": 1000, "currency": "usd"}
    assert call["headers"]["Accept"] == "application/json;version=20230203"
    assert call["timeout"] == (5.0, 30.0)


def test_an_address_that_is_not_in_pools_yml_is_never_queried():
    session = FakeSession()
    gecko, _ = client(session)
    with pytest.raises(external.ExternalSourceError, match="not in pools.yml"):
        gecko.daily_ohlcv_raw("0x" + "ab" * 20)
    assert session.calls == []


def test_requests_are_spaced_under_the_lower_documented_rate_limit():
    ok = FakeResponse(200, recorded(QUIET_POOL))
    gecko, fake = client(FakeSession(ok, ok, ok))
    for _ in range(3):
        gecko.daily_ohlcv_raw(QUIET_POOL)
    assert fake.sleeps == [7.0, 7.0]
    assert 60 / external.MIN_INTERVAL_SECONDS < 10, "documented: ~10 calls per minute"


def test_429_and_network_errors_back_off_then_succeed():
    session = FakeSession(FakeResponse(429), requests.Timeout("slow"), FakeResponse(200, "{}"))
    gecko, fake = client(session, min_interval=0)
    assert gecko.daily_ohlcv_raw(QUIET_POOL) == "{}"
    assert fake.sleeps == [10.0, 20.0]


def test_gives_up_after_max_attempts_and_does_not_retry_a_404():
    gecko, _ = client(FakeSession(*[FakeResponse(503)] * 3), min_interval=0, max_attempts=3)
    with pytest.raises(external.ExternalSourceError, match="gave up after 3"):
        gecko.daily_ohlcv_raw(QUIET_POOL)
    session = FakeSession(FakeResponse(404))
    gecko, fake = client(session, min_interval=0)
    with pytest.raises(external.ExternalSourceError, match="HTTP 404"):
        gecko.daily_ohlcv_raw(QUIET_POOL)
    assert len(session.calls) == 1 and fake.sleeps == []


# --- into ClickHouse ------------------------------------------------------------------------


def test_a_second_fetch_supersedes_the_first_only_under_final(clickhouse, temp_database):
    rows = external.parse_daily(QUIET_POOL, recorded(QUIET_POOL))
    first = datetime.datetime(2026, 9, 20, 1, 0, tzinfo=datetime.UTC)
    external.store(clickhouse, temp_database, rows, first)
    revised = [
        external.DailyVolume(r.pool_address, r.date, r.timestamp, r.volume_usd * 2, r.close_usd)
        for r in rows
    ]
    external.store(clickhouse, temp_database, revised, first + datetime.timedelta(hours=1))

    table = ch.qualified(temp_database, external.TABLE)
    clickhouse.command(f"SYSTEM STOP MERGES {table}")
    plain = clickhouse.command(f"SELECT count() FROM {table}")
    final = clickhouse.command(f"SELECT count() FROM {table} FINAL")
    assert (plain, final) == (2 * len(rows), len(rows)), "without FINAL both fetches are visible"
    newest = float(clickhouse.command(f"SELECT sum(volume_usd) FROM {table} FINAL"))
    assert newest == pytest.approx(2 * sum(r.volume_usd for r in rows))


def test_the_table_is_the_decided_one(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database, external.DDL)
    engine, sorting_key = clickhouse.query(
        "SELECT engine, sorting_key FROM system.tables WHERE database = %(db)s AND name = %(t)s",
        parameters={"db": temp_database, "t": external.TABLE},
    ).result_rows[0]
    assert engine == "ReplacingMergeTree"
    assert sorting_key == "source, pool_address, date"
