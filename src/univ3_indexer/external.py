"""A second, independent source of daily volume: the public GeckoTerminal API.

    python -m univ3_indexer.external --fetch        # every pool in pools.yml -> ClickHouse

No API key. Checked against the official documentation on 2026-09-20:

* OpenAPI spec  https://api.geckoterminal.com/docs/v2/swagger.json
  endpoint      GET /networks/{network}/pools/{pool_address}/ohlcv/{timeframe}
  parameters    aggregate, before_timestamp, limit (max 1000), currency (usd|token)
  version       header  Accept: application/json;version=20230203
  freshness     "All endpoints listed below are cached for 1 minute"
  rate limit    "approximately 10 calls/minute, which may fluctuate"
* FAQ           https://apiguide.geckoterminal.com/faq  says 30 calls per minute.

The two official pages disagree on the rate limit, so the client assumes the lower one
and spaces requests 7 seconds apart. Neither page documents how far back the daily
history goes nor which day boundary a daily candle uses; both are observed from the
responses and written down in docs/EXTERNAL_SOURCE.md.

Pool addresses come from pools.yml and from nowhere else: the client refuses any other.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from univ3_indexer import clickhouse as ch
from univ3_indexer import config
from univ3_indexer.addresses import Address, normalize
from univ3_indexer.pools import load_pools

log = logging.getLogger("univ3_indexer.external")

SOURCE = "geckoterminal"
BASE_URL = "https://api.geckoterminal.com/api/v2"
NETWORK = "eth"
API_VERSION_HEADER = {"Accept": "application/json;version=20230203"}
MIN_INTERVAL_SECONDS = 7.0  # under the lower of the two documented limits (~10 per minute)
MAX_LIMIT = 1000
TABLE = "external_daily_volume"
DDL = ch.SQL_DIR / "002_external_daily_volume.sql"
COLUMNS = ["source", "pool_address", "date", "volume_usd", "close_usd", "fetched_at"]
HOURLY_TABLE = "external_hourly_volume"
HOURLY_DDL = ch.SQL_DIR / "004_external_hourly_volume.sql"
HOURLY_COLUMNS = ["source", "pool_address", "hour", "volume_usd", "fetched_at"]
TIMEFRAMES = ("day", "hour")
_RETRYABLE = {429, 500, 502, 503, 504}


class ExternalSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyVolume:
    pool_address: Address
    date: datetime.date
    timestamp: int  # the source's own candle timestamp, seconds
    volume_usd: float
    close_usd: float


class GeckoTerminalClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        min_interval: float = MIN_INTERVAL_SECONDS,
        max_attempts: int = 5,
        backoff_base: float = 10.0,
        backoff_cap: float = 120.0,
        timeout: tuple[float, float] = (5.0, 30.0),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
    ):
        self._session = session or requests.Session()
        self._min_interval, self._max_attempts = min_interval, max_attempts
        self._backoff_base, self._backoff_cap, self._timeout = backoff_base, backoff_cap, timeout
        self._sleep, self._clock, self._rng = sleep, clock, rng
        self._last: float | None = None
        self._allowed = {p.key for p in load_pools()}
        self.requests_sent = 0

    def daily_ohlcv_raw(self, pool: str, limit: int = MAX_LIMIT) -> str:
        """The response body, untouched, for one pool of pools.yml."""
        return self.ohlcv_raw(pool, "day", limit)

    def ohlcv_raw(self, pool: str, timeframe: str, limit: int = MAX_LIMIT) -> str:
        """Daily or hourly candles, newest first, for one pool of pools.yml."""
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
        key = normalize(pool)
        if key not in self._allowed:
            raise ExternalSourceError(f"{key} is not in pools.yml: refusing to query it")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        url = f"{BASE_URL}/networks/{NETWORK}/pools/{key}/ohlcv/{timeframe}"
        params = {"aggregate": 1, "limit": limit, "currency": "usd"}
        problem = "no attempt made"
        for attempt in range(1, self._max_attempts + 1):
            self._pace()
            self.requests_sent += 1
            try:
                response = self._session.get(
                    url, params=params, headers=API_VERSION_HEADER, timeout=self._timeout
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                problem = type(exc).__name__
            else:
                if response.status_code == 200:
                    return response.text
                problem = f"HTTP {response.status_code}"
                if response.status_code not in _RETRYABLE:
                    raise ExternalSourceError(f"GeckoTerminal answered {problem} for {key}")
            if attempt < self._max_attempts:
                delay = min(self._backoff_cap, self._backoff_base * 2 ** (attempt - 1))
                delay *= 0.5 + self._rng() / 2
                log.warning("GeckoTerminal %s (attempt %d/%d), retrying in %.0fs", problem,
                            attempt, self._max_attempts, delay)  # fmt: skip
                self._sleep(delay)
        raise ExternalSourceError(
            f"GeckoTerminal: gave up after {self._max_attempts} attempts: {problem}"
        )  # noqa: E501

    def _pace(self) -> None:
        now = self._clock()
        if self._last is not None and (wait := self._min_interval - (now - self._last)) > 0:
            self._sleep(wait)
            now = self._clock()
        self._last = now


def parse_daily(pool: str, body: str) -> list[DailyVolume]:
    """Candles are [timestamp, open, high, low, close, volume], newest first."""
    key = normalize(pool)
    try:
        candles = json.loads(body)["data"]["attributes"]["ohlcv_list"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ExternalSourceError(f"unexpected GeckoTerminal response for {key}") from exc
    by_day: dict[datetime.date, DailyVolume] = {}
    for candle in candles:
        if len(candle) != 6:
            raise ExternalSourceError(f"a candle for {key} does not have 6 fields")
        timestamp = int(candle[0])
        day = datetime.datetime.fromtimestamp(timestamp, datetime.UTC).date()
        row = DailyVolume(key, day, timestamp, float(candle[5]), float(candle[4]))
        seen = by_day.get(day)
        if seen is None:
            by_day[day] = row
        elif (seen.timestamp, seen.volume_usd) == (row.timestamp, row.volume_usd):
            # Seen for real on 2026-09-20: the same candle twice (same timestamp, same
            # volume, a different open). One copy is kept. Anything else is refused.
            log.warning("GeckoTerminal repeated the candle of %s for %s: kept once", day, key)
        else:
            raise ExternalSourceError(
                f"GeckoTerminal returned two DIFFERENT candles for {day} of {key}: "
                "refusing to choose"
            )
    return [by_day[day] for day in sorted(by_day)]


def parse_hourly(pool: str, body: str) -> list[tuple[datetime.datetime, float]]:
    """(start of the hour in UTC, volume in USD), oldest first. The same candle twice is kept
    once; two different candles for one hour are refused, as for the days."""
    key = normalize(pool)
    try:
        candles = json.loads(body)["data"]["attributes"]["ohlcv_list"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ExternalSourceError(f"unexpected GeckoTerminal response for {key}") from exc
    by_hour: dict[int, float] = {}
    for candle in candles:
        if len(candle) != 6:
            raise ExternalSourceError(f"a candle for {key} does not have 6 fields")
        timestamp, volume = int(candle[0]), float(candle[5])
        if timestamp % 3600:
            raise ExternalSourceError(f"an hourly candle for {key} does not start on the hour")
        if by_hour.setdefault(timestamp, volume) != volume:
            raise ExternalSourceError(f"two DIFFERENT hourly candles for {key}: refusing to choose")
    return [(datetime.datetime.fromtimestamp(t, datetime.UTC), by_hour[t]) for t in sorted(by_hour)]


def fetch_hourly(client, database: str, gecko: GeckoTerminalClient, raw_dir: Path | None) -> dict:
    ch.apply_ddl(client, database, HOURLY_DDL)
    fetched_at = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    summary = {}
    for pool in load_pools():
        body = gecko.ohlcv_raw(pool.key, "hour")
        if raw_dir:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{pool.key}.hour.json").write_text(body, encoding="utf-8")
        rows = parse_hourly(pool.key, body)
        data = [[SOURCE, str(pool.key), hour, volume, fetched_at] for hour, volume in rows]
        if data:
            client.insert(ch.qualified(database, HOURLY_TABLE), data, column_names=HOURLY_COLUMNS)
        summary[pool.label] = {"hours": len(rows), "first": str(rows[0][0]) if rows else None,
                               "last": str(rows[-1][0]) if rows else None}  # fmt: skip
        log.info("%s: %d hourly candles", pool.label, len(rows))
    return summary


def store(client, database: str, rows: list[DailyVolume], fetched_at: datetime.datetime) -> int:
    ch.apply_ddl(client, database, DDL)
    data = [
        [SOURCE, str(r.pool_address), r.date, r.volume_usd, r.close_usd, fetched_at] for r in rows
    ]  # noqa: E501
    if data:
        client.insert(ch.qualified(database, TABLE), data, column_names=COLUMNS)
    return len(data)


def fetch_all(client, database: str, gecko: GeckoTerminalClient, raw_dir: Path | None) -> dict:
    fetched_at = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    summary = {}
    for pool in load_pools():
        body = gecko.daily_ohlcv_raw(pool.key)
        if raw_dir:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{pool.key}.json").write_text(body, encoding="utf-8")
        rows = parse_daily(pool.key, body)
        store(client, database, rows, fetched_at)
        summary[pool.label] = {
            "days": len(rows),
            "first": str(rows[0].date) if rows else None,
            "last": str(rows[-1].date) if rows else None,
        }
        log.info("%s: %d days (%s to %s)", pool.label, len(rows), summary[pool.label]["first"],
                 summary[pool.label]["last"])  # fmt: skip
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.external")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--fetch", action="store_true", help="daily candles")
    action.add_argument(
        "--fetch-hourly",
        action="store_true",
        help="the last 1,000 hourly candles, to localise a day that differs",
    )
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database = args.database or config.load_clickhouse_config().database
    raw_dir = config.data_dir() / "external" / SOURCE  # outside the working copy
    fetcher = fetch_hourly if args.fetch_hourly else fetch_all
    summary = fetcher(ch.connect(database=database), database, GeckoTerminalClient(), raw_dir)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
