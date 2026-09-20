"""Smart-money DEX trades from the Nansen API, crossed with raw_swaps by transaction hash.

    python -m univ3_indexer.nansen --fetch      # ONE paid call; the body is cached outside the repo
    python -m univ3_indexer.nansen --report     # aggregate cross -> docs/NANSEN_CROSS.md

Read in the official documentation on 2026-09-20, before any call:

* cost table  https://docs.nansen.ai/getting-started/credits.md  ("Endpoint Credit Cost")
  smart-money/dex-trades  5 credits per call, Free and Pro alike
* endpoint    https://docs.nansen.ai/api/smart-money/dex-trades.md
  POST https://api.nansen.ai/api/v1/smart-money/dex-trades, header `apikey`
  body        chains (required), filters, pagination {page, per_page <= 1000}, order_by
  window      "Only the trailing 24 hours of DEX trades is queryable ... there is no
              date-range parameter"
  each trade  chain, block_timestamp, transaction_hash, trader_address ("the signer of the
              transaction"), trader_address_label, both tokens, trade_value_usd
  headers     X-Nansen-Credits-Cost (quoted), X-Nansen-Credits-Used (deducted),
              X-Nansen-Credits-Remaining

Credits are money, so this client is built to spend as little as it is told to:

* every call is checked against a budget BEFORE it is sent, at its documented cost;
* there are no retries: a request that failed may have been billed, and a second one would be;
* `--fetch` refuses to call when a cached response exists;
* the API key travels in one header and appears in no log, error or cached file.

The raw response names wallets and carries their labels. It stays outside the repo, under
`<data dir>/nansen/`. What this module writes into the repo is an aggregate per pool.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from univ3_indexer import clickhouse as ch
from univ3_indexer import config
from univ3_indexer.addresses import normalize
from univ3_indexer.pools import load_pools
from univ3_indexer.reconcile import stable_leg_parameters, stablecoin_symbols

log = logging.getLogger("univ3_indexer.nansen")

BASE_URL = "https://api.nansen.ai/api/v1"
ENDPOINT = "smart-money/dex-trades"
TGM_ENDPOINT = "tgm/dex-trades"
DOCUMENTED_COST = {ENDPOINT: 5, TGM_ENDPOINT: 1}  # credits per call, official cost table
DEFAULT_BUDGET = 40  # for the tgm/dex-trades campaign; spent credits persist in the ledger
LEDGER = "ledger.jsonl"
DAILY_TABLE = "nansen_smart_money_daily"
DAILY_DDL = ch.SQL_DIR / "003_nansen_smart_money_daily.sql"
DAILY_SQL = ch.SQL_DIR / "nansen" / "03_daily_by_tx_hash.sql"
DAILY_COLUMNS = ["pool_address", "date", "named_swaps", "named_transactions", "named_volume_usd",
                 "token_symbol", "window_from", "window_to", "computed_at"]  # fmt: skip
POOLS_YML = config.REPO_ROOT / "pools.yml"
VERIFICATION_DIR = config.REPO_ROOT / "docs" / "verification"
CHAIN = "ethereum"
MAX_PER_PAGE = 1000
CROSS_SQL = ch.SQL_DIR / "nansen" / "01_cross_by_tx_hash.sql"
NAMED_SQL = ch.SQL_DIR / "nansen" / "02_named_transactions.sql"
REPORT = config.REPO_ROOT / "docs" / "NANSEN_CROSS.md"
_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


class NansenError(RuntimeError):
    pass


class BudgetExceeded(NansenError):
    pass


class CreditBudget:
    """Refuses a call whose documented cost does not fit in what is left.

    With a ledger file the budget outlives the process: what earlier runs spent on the same
    endpoint counts against the same ceiling, so a probe and the run after it share it.
    """

    def __init__(self, max_credits: int, ledger: Path | None = None, endpoint: str | None = None):
        self.max_credits, self.spent = max_credits, 0
        self._ledger = ledger
        if ledger is not None and ledger.exists():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                if endpoint is None or entry["endpoint"] == endpoint:
                    self.spent += int(entry["used"])

    def write(self, endpoint: str, used: int, note: str) -> None:
        if self._ledger is None:
            return
        self._ledger.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        entry = {"at": now, "endpoint": endpoint, "used": used, "note": note}
        with self._ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def check(self, cost: int) -> None:
        if self.spent + cost > self.max_credits:
            raise BudgetExceeded(
                f"a call costing {cost} credits does not fit: {self.spent} of "
                f"{self.max_credits} already spent"
            )

    def record(self, used: int) -> None:
        self.spent += used


@dataclass(frozen=True)
class RawResponse:
    body: str
    request: dict
    credits_cost: int | None  # quoted by the API; None when the header is absent
    credits_used: int  # deducted; the documented cost when the API does not say
    credits_remaining: int | None


@dataclass(frozen=True)
class Trade:
    tx_hash: str  # 64 lower-case hex digits, no prefix
    timestamp: datetime.datetime  # UTC
    value_usd: float | None


def _header_int(response, name: str) -> int | None:
    value = response.headers.get(name)
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None


class NansenClient:
    def __init__(
        self,
        api_key: str,
        budget: CreditBudget,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (5.0, 60.0),
    ):
        if not api_key:
            raise NansenError("empty API key")
        self._api_key, self._budget, self._timeout = api_key, budget, timeout
        self._session = session or requests.Session()
        self.requests_sent = 0

    def smart_money_dex_trades_raw(
        self, per_page: int = MAX_PER_PAGE, page: int = 1
    ) -> RawResponse:
        """One page of the trailing 24 hours on Ethereum, newest first. One attempt, no retry."""
        self._check_pagination(per_page, page)
        request = {
            "chains": [CHAIN],
            "pagination": {"page": page, "per_page": per_page},
            "order_by": [{"field": "block_timestamp", "direction": "DESC"}],
        }
        return self._post(ENDPOINT, request)

    def tgm_dex_trades_raw(
        self,
        token_address: str,
        date_from: datetime.date,
        date_to: datetime.date,
        per_page: int = MAX_PER_PAGE,
        page: int = 1,
    ) -> RawResponse:
        """One page of the smart-money DEX trades of one token over the whole UTC days
        `date_from`..`date_to`, oldest first. Oldest first over a closed window: the pages
        do not shift between calls. One attempt, no retry."""
        self._check_pagination(per_page, page)
        if date_to < date_from:
            raise ValueError("date_to is before date_from")
        if token_address not in known_token_addresses().values():
            raise NansenError(f"{token_address} is not a token of pools.yml: refusing to query it")
        request = {
            "chain": CHAIN,
            "token_address": token_address,
            "only_smart_money": True,
            "date": {"from": f"{date_from}T00:00:00Z", "to": f"{date_to}T23:59:59Z"},
            "pagination": {"page": page, "per_page": per_page},
            "order_by": [{"field": "block_timestamp", "direction": "ASC"}],
        }
        return self._post(TGM_ENDPOINT, request)

    @staticmethod
    def _check_pagination(per_page: int, page: int) -> None:
        if not 1 <= per_page <= MAX_PER_PAGE or page < 1:
            raise ValueError(f"per_page must be between 1 and {MAX_PER_PAGE}, page at least 1")

    def _post(self, endpoint: str, request: dict) -> RawResponse:
        cost = DOCUMENTED_COST[endpoint]
        self._budget.check(cost)
        self.requests_sent += 1
        try:
            response = self._session.post(
                f"{BASE_URL}/{endpoint}",
                json=request,
                headers={"apikey": self._api_key, "Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            # It may have reached the server and been billed: count it, and never retry.
            self._budget.record(cost)
            self._budget.write(endpoint, cost, f"{type(exc).__name__}: booked as if billed")
            raise NansenError(
                f"Nansen request failed ({type(exc).__name__}); not retried"
            ) from None
        quoted = _header_int(response, "X-Nansen-Credits-Cost")
        used = _header_int(response, "X-Nansen-Credits-Used")
        remaining = _header_int(response, "X-Nansen-Credits-Remaining")
        if used is None:
            used = cost if response.status_code == 200 else (quoted or 0)
        self._budget.record(used)
        self._budget.write(endpoint, used, f"HTTP {response.status_code}")
        if response.status_code != 200:
            code = ""
            try:
                code = str(response.json().get("code", ""))
            except ValueError:
                pass
            raise NansenError(
                f"Nansen answered HTTP {response.status_code} {code} "
                f"(credits used: {used}); not retried"
            )
        return RawResponse(response.text, request, quoted, used, remaining)


def parse_trades(body: str) -> tuple[list[Trade], bool]:
    """Trades on Ethereum, and whether the API says this was the last page."""
    try:
        payload = json.loads(body)
        data, pagination = payload["data"], payload.get("pagination") or {}
    except (ValueError, KeyError, TypeError) as exc:
        raise NansenError("unexpected Nansen response") from exc
    if not isinstance(data, list):
        raise NansenError("unexpected Nansen response: data is not a list")
    trades = []
    for item in data:
        try:
            chain, raw_hash, raw_time = (
                item["chain"],
                item["transaction_hash"],
                item["block_timestamp"],
            )
        except (KeyError, TypeError) as exc:
            raise NansenError(
                "a Nansen trade lacks chain, transaction_hash or block_timestamp"
            ) from exc
        if chain != CHAIN:
            continue
        if not isinstance(raw_hash, str) or not _TX_HASH.match(raw_hash):
            raise NansenError("a Nansen trade has a malformed transaction hash")
        try:
            when = datetime.datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NansenError("a Nansen trade has an unreadable block_timestamp") from exc
        when = (
            when.replace(tzinfo=datetime.UTC)
            if when.tzinfo is None
            else when.astimezone(datetime.UTC)
        )
        value = item.get("trade_value_usd")
        trades.append(
            Trade(
                bytes.fromhex(raw_hash[2:]).hex(), when, float(value) if value is not None else None
            )
        )
    return trades, bool(pagination.get("is_last_page", True))


_TOKEN_COMMENT = re.compile(r"#\s*token0\s+(0x[0-9a-fA-F]{40}),\s*token1\s+(0x[0-9a-fA-F]{40})")
_SYMBOLS = re.compile(r"^\s*token([01]):\s*(\S+)")


def known_token_addresses() -> dict[str, str]:
    """symbol -> token address, read from pools.yml and from nowhere else.

    pools.yml records both token addresses of every pool in the comment written when the
    pool was verified on-chain. Each address is accepted only if the committed verification
    evidence (docs/verification/*.json, what the pool contract itself answered) holds the
    same 20 bytes; a symbol that maps to two addresses is refused."""
    evidence = "".join(
        p.read_text(encoding="utf-8") for p in sorted(VERIFICATION_DIR.glob("*.json"))
    )
    found: dict[str, str] = {}
    pending: tuple[str, str] | None = None
    symbols: dict[str, str] = {}
    for line in POOLS_YML.read_text(encoding="utf-8").splitlines():
        if match := _TOKEN_COMMENT.search(line):
            pending, symbols = (match.group(1), match.group(2)), {}
        elif pending and (match := _SYMBOLS.match(line)):
            symbols[match.group(1)] = match.group(2).strip("\"'")
            if len(symbols) == 2:
                for index, address in enumerate(pending):
                    symbol = symbols[str(index)]
                    if str(normalize(address))[2:] not in evidence:  # raw words are lower-case
                        raise NansenError(
                            f"{symbol}: the address in pools.yml is not in the evidence"
                        )
                    if found.setdefault(symbol, address) != address:
                        raise NansenError(f"{symbol} has two different addresses in pools.yml")
                pending = None
    return found


def parse_tgm_trades(body: str) -> tuple[list[Trade], bool]:
    """Trades of a tgm/dex-trades page, and whether the API says it was the last page."""
    try:
        payload = json.loads(body)
        data, pagination = payload["data"], payload.get("pagination") or {}
    except (ValueError, KeyError, TypeError) as exc:
        raise NansenError("unexpected Nansen response") from exc
    if not isinstance(data, list):
        raise NansenError("unexpected Nansen response: data is not a list")
    trades = []
    for item in data:
        try:
            raw_hash, raw_time = item["transaction_hash"], item["block_timestamp"]
        except (KeyError, TypeError) as exc:
            raise NansenError("a Nansen trade lacks transaction_hash or block_timestamp") from exc
        if not isinstance(raw_hash, str) or not _TX_HASH.match(raw_hash):
            raise NansenError("a Nansen trade has a malformed transaction hash")
        trades.append(
            Trade(
                bytes.fromhex(raw_hash[2:]).hex(), _utc(raw_time), item.get("estimated_value_usd")
            )
        )
    return trades, bool(pagination.get("is_last_page", True))


def _utc(raw_time) -> datetime.datetime:
    try:
        when = datetime.datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
    except ValueError as exc:
        raise NansenError("a Nansen trade has an unreadable block_timestamp") from exc
    return (
        when.replace(tzinfo=datetime.UTC) if when.tzinfo is None else when.astimezone(datetime.UTC)
    )


def tgm_page_path(directory: Path, symbol: str, date_from, date_to, page: int) -> Path:
    return directory / f"tgm_dex_trades_{symbol}_{date_from}_{date_to}_p{page:03d}.json"


def fetch_tgm(
    client: NansenClient,
    directory: Path,
    symbol: str,
    date_from: datetime.date,
    date_to: datetime.date,
    max_pages: int = 1,
) -> dict:
    """Pages 1..max_pages of one token and one window. A page already cached is read, never
    asked for again; it stops at the page the API calls the last one, or when the budget
    refuses the next call."""
    address = known_token_addresses().get(symbol)
    if address is None:
        raise NansenError(f"{symbol} is not a token of pools.yml")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    summary = {"symbol": symbol, "pages": 0, "called": 0, "trades": 0, "complete": False}
    for page in range(1, max_pages + 1):
        path = tgm_page_path(directory, symbol, date_from, date_to, page)
        if path.exists():
            envelope = json.loads(path.read_text(encoding="utf-8"))
        else:
            raw = client.tgm_dex_trades_raw(address, date_from, date_to, page=page)
            summary["called"] += 1
            envelope = {
                "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
                "endpoint": TGM_ENDPOINT, "symbol": symbol, "request": raw.request,
                "credits": {"documented": DOCUMENTED_COST[TGM_ENDPOINT], "quoted": raw.credits_cost,
                            "used": raw.credits_used, "remaining": raw.credits_remaining},
                "response": json.loads(raw.body),
            }  # fmt: skip
            path.write_text(json.dumps(envelope, indent=1), encoding="utf-8")
            path.chmod(0o600)
        trades, is_last = parse_tgm_trades(json.dumps(envelope["response"]))
        summary["pages"] += 1
        summary["trades"] += len(trades)
        summary["last_credits"] = envelope["credits"]
        if trades:
            summary["newest"] = max(t.timestamp for t in trades).isoformat()
            summary.setdefault("oldest", min(t.timestamp for t in trades).isoformat())
        if is_last:
            summary["complete"] = True
            break
    return summary


def cached_tgm(directory: Path, symbol: str, date_from, date_to) -> tuple[list[Trade], bool, int]:
    """Every cached page of one token and window, in order: trades, complete?, pages."""
    trades, complete, page = [], False, 0
    while (path := tgm_page_path(directory, symbol, date_from, date_to, page + 1)).exists():
        page += 1
        more, is_last = parse_tgm_trades(
            json.dumps(json.loads(path.read_text(encoding="utf-8"))["response"])
        )
        trades += more
        if is_last:
            complete = True
            break
    return trades, complete, page


def store_daily(
    client, database: str, symbol: str, trades: list[Trade], complete: bool,
    date_from: datetime.date, date_to: datetime.date, pools=None,
) -> dict:  # fmt: skip
    """Cross by transaction hash and store the per-pool, per-day aggregate. When the pages are
    not complete the window ends at the newest trade fetched: the days after it were not
    looked at, and get no row."""
    pools = pools if pools is not None else load_pools()
    mine = [str(p.key) for p in pools if symbol in (p.token0, p.token1)]
    window_from = datetime.datetime.combine(date_from, datetime.time.min)
    window_to = datetime.datetime.combine(date_to, datetime.time.max).replace(microsecond=0)
    if not complete:
        if not trades:
            raise NansenError("no complete page and no trade: nothing can be said about any day")
        # only whole days: the day of the newest trade fetched is cut short, so it is dropped
        newest = max(t.timestamp for t in trades).replace(tzinfo=None)
        window_to = datetime.datetime.combine(
            newest.date(), datetime.time.min
        ) - datetime.timedelta(seconds=1)
    our_last = client.query("SELECT max(block_timestamp) FROM raw_swaps",
                            settings={"database": database}).result_rows[0][0]  # fmt: skip
    window_to = min(window_to, our_last.replace(tzinfo=None))
    ch.apply_ddl(client, database, DAILY_DDL)
    parameters = {
        **stable_leg_parameters(pools, stablecoin_symbols()),
        "hashes": sorted({t.tx_hash for t in trades}), "pools": mine,
        "window_from": window_from, "window_to": window_to,
    }  # fmt: skip
    result = client.query(_sql(DAILY_SQL), parameters=parameters, settings={"database": database})
    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0, tzinfo=None)
    rows = [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]
    data = [[r["pool_address"], r["day"], r["named_swaps"], r["named_transactions"],
             r["named_volume_usd"], symbol, window_from, window_to, now] for r in rows]  # fmt: skip
    if data:
        client.insert(ch.qualified(database, DAILY_TABLE), data, column_names=DAILY_COLUMNS)
    return {"symbol": symbol, "pools": len(mine), "pool_days": len(data),
            "window_from": str(window_from), "window_to": str(window_to),
            "named_swaps": sum(r["named_swaps"] for r in rows),
            "named_volume_usd": sum(r["named_volume_usd"] for r in rows),
            "volume_usd": sum(r["volume_usd"] for r in rows)}  # fmt: skip


def cache_dir() -> Path:
    return config.data_dir() / "nansen"


def cached_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("smart_money_dex_trades_*.json")) if directory.is_dir() else []


def fetch(client: NansenClient, directory: Path, now: datetime.datetime | None = None) -> Path:
    """Spend one call, unless a response is already cached: then refuse, and say where it is."""
    if existing := cached_files(directory):
        raise NansenError(
            f"already cached: {existing[-1]}. Delete it to spend credits again; "
            "--report reads it without calling"
        )
    raw = client.smart_money_dex_trades_raw()
    now = now or datetime.datetime.now(datetime.UTC)
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / f"smart_money_dex_trades_{now:%Y%m%dT%H%M%SZ}.json"
    envelope = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "endpoint": ENDPOINT,
        "request": raw.request,
        "credits": {
            "documented": DOCUMENTED_COST[ENDPOINT],
            "quoted": raw.credits_cost,
            "used": raw.credits_used,
            "remaining": raw.credits_remaining,
        },
        "response": json.loads(raw.body),
    }
    path.write_text(json.dumps(envelope, indent=1), encoding="utf-8")
    path.chmod(0o600)
    return path


# --- the cross ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cross:
    fetched_at: str
    credits: dict
    trades: int  # trades on Ethereum in the response
    transactions: int  # distinct transaction hashes among them
    is_last_page: bool
    response_from: datetime.datetime | None
    response_to: datetime.datetime | None
    our_last_swap: datetime.datetime | None
    trades_after_our_data: int
    window_from: datetime.datetime | None
    window_to: datetime.datetime | None
    transactions_in_window: int  # distinct transactions of the response inside the window
    transactions_found: int  # of those, present in raw_swaps, in any pool
    pools: list[dict]


def cross(client, database: str, envelope: dict, pools=None) -> Cross:
    trades, is_last = parse_trades(json.dumps(envelope["response"]))
    pools = pools if pools is not None else load_pools()
    last = client.query(
        "SELECT max(block_timestamp), count() FROM raw_swaps", settings={"database": database}
    ).result_rows[0]
    our_last = last[0].replace(tzinfo=datetime.UTC) if last[1] else None
    base = dict(
        fetched_at=envelope["fetched_at"],
        credits=envelope["credits"],
        trades=len(trades),
        transactions=len({t.tx_hash for t in trades}),
        is_last_page=is_last,
        our_last_swap=our_last,
    )
    if not trades or our_last is None:
        return Cross(
            **base,
            response_from=None,
            response_to=None,
            trades_after_our_data=0,
            window_from=None,
            window_to=None,
            transactions_in_window=0,
            transactions_found=0,
            pools=[],
        )
    first, newest = min(t.timestamp for t in trades), max(t.timestamp for t in trades)
    window_to = min(newest, our_last)
    covered = [t for t in trades if t.timestamp <= window_to]
    rows, hashes, found = [], sorted({t.tx_hash for t in covered}), 0
    if covered:
        window = {
            "hashes": hashes,
            "window_from": first.replace(tzinfo=None),
            "window_to": window_to.replace(tzinfo=None),
        }
        parameters = {**stable_leg_parameters(pools, stablecoin_symbols()), **window}
        result = client.query(
            _sql(CROSS_SQL), parameters=parameters, settings={"database": database}
        )
        found = int(
            client.query(
                _sql(NAMED_SQL), parameters=window, settings={"database": database}
            ).result_rows[0][0]
        )
        labels = {str(p.key): p.label for p in pools}
        for row in result.result_rows:
            r = dict(zip(result.column_names, row, strict=True))
            rows.append({**r, "pool": labels.get(r["pool_address"], r["pool_address"])})
    return Cross(
        **base,
        response_from=first,
        response_to=newest,
        trades_after_our_data=len(trades) - len(covered),
        window_from=first,
        window_to=window_to,
        transactions_in_window=len(hashes),
        transactions_found=found,
        pools=rows,
    )


def _sql(path: Path) -> str:
    return ch.strip_sql_comments(path.read_text(encoding="utf-8")).strip().rstrip(";")


def _share(part: float, whole: float) -> str:
    return f"{100 * part / whole:.4f}%" if whole else "n/a"


def render(result: Cross) -> str:
    c = result.credits
    out = [
        "# Nansen smart-money DEX trades, crossed with raw_swaps",
        "",
        "Generated by `PYTHONPATH=src uv run python -m univ3_indexer.nansen --report`. "
        "Aggregates only: no transaction hash, address or label is written here. The raw "
        "response stays outside the repo.",
        "",
        "## What was asked, and what it cost",
        "",
        f"- Endpoint: `POST /api/v1/{ENDPOINT}`, chain `{CHAIN}`, newest first, "
        f"`per_page` {MAX_PER_PAGE}, page 1. No token or pool filter.",
        "- Documented cost: 5 credits per call "
        '(<https://docs.nansen.ai/getting-started/credits.md>, table "Endpoint Credit Cost").',
        f"- Fetched at {result.fetched_at}. Credits quoted by the API: {c.get('quoted')}; "
        f"deducted: {c.get('used')}; remaining after the call: {c.get('remaining')}.",
        "- The endpoint only serves the trailing 24 hours and has no date parameter, so this "
        "cross cannot be repeated later for the same window.",
        "",
        "## What came back",
        "",
        f"- Trades on Ethereum: {result.trades:,} in {result.transactions:,} distinct "
        "transactions. "
        f"Last page according to the API: {'yes' if result.is_last_page else 'no'}.",
    ]
    if result.response_from is None:
        out += ["- Nothing to cross.", ""]
        return "\n".join(out)
    hours = (result.response_to - result.response_from).total_seconds() / 3600
    out += [
        f"- Oldest trade {result.response_from:%Y-%m-%d %H:%M:%S} UTC, newest "
        f"{result.response_to:%Y-%m-%d %H:%M:%S} UTC ({hours:.1f} h).",
        f"- Our last swap: {result.our_last_swap:%Y-%m-%d %H:%M:%S} UTC. Trades newer than that, "
        f"left out of the cross: {result.trades_after_our_data:,}.",
        f"- Window crossed: {result.window_from:%Y-%m-%d %H:%M:%S} to "
        f"{result.window_to:%Y-%m-%d %H:%M:%S} UTC.",
        "",
        "## The cross, per pool",
        "",
        'A swap of ours is "named" when its transaction hash is among the transactions of the '
        "response. USD is the stablecoin leg at 1 USD.",
        "",
        "| Pool | Our swaps in the window | Our USD | Named swaps | Named transactions | Named USD | Share of swaps | Share of USD |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|",
    ]
    total = {
        "swaps": 0,
        "volume_usd": 0.0,
        "named_swaps": 0,
        "named_transactions": 0,
        "named_volume_usd": 0.0,
    }
    for r in result.pools:
        for key in total:
            total[key] += r[key]
        out.append(
            f"| {r['pool']} | {r['swaps']:,} | {r['volume_usd']:,.0f} | {r['named_swaps']:,} | "
            f"{r['named_transactions']:,} | {r['named_volume_usd']:,.0f} | "
            f"{_share(r['named_swaps'], r['swaps'])} | "
            f"{_share(r['named_volume_usd'], r['volume_usd'])} |"
        )
    out.append(
        f"| **All four** | {total['swaps']:,} | {total['volume_usd']:,.0f} | "
        f"{total['named_swaps']:,} | "
        f"{total['named_transactions']:,} | {total['named_volume_usd']:,.0f} | "
        f"{_share(total['named_swaps'], total['swaps'])} | "
        f"{_share(total['named_volume_usd'], total['volume_usd'])} |"
    )
    out += [
        "",
        "Distinct transactions of the response inside the window: "
        f"{result.transactions_in_window:,}. "
        f"Present in `raw_swaps`, in any of the pools: {result.transactions_found:,}.",
        "",
        "A transaction can route through two of the pools: the per-pool rows then count it once "
        "each, and the total row adds them up.",
        "",
    ]
    return "\n".join(out)


def _date(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.nansen")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--fetch",
        action="store_true",
        help="smart-money/dex-trades: ONE paid call (5 credits), cached",
    )
    action.add_argument(
        "--report",
        action="store_true",
        help="cross the cached smart-money/dex-trades response; no call",
    )
    action.add_argument(
        "--fetch-tgm",
        metavar="SYMBOL",
        help="tgm/dex-trades of one token of pools.yml, smart money only: "
        "1 credit per page NOT yet cached; needs --from, --to, --max-pages",
    )
    action.add_argument(
        "--daily",
        metavar="SYMBOL",
        help="cross the cached tgm pages and store the per-day aggregate; no call",
    )
    parser.add_argument("--from", dest="date_from", type=_date, help="first UTC day, YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=_date, help="last UTC day, inclusive")
    parser.add_argument(
        "--max-pages", type=int, default=1, help="pages to read at most (default 1)"
    )
    parser.add_argument(
        "--max-credits",
        type=int,
        default=DEFAULT_BUDGET,
        help="ceiling for the endpoint, INCLUDING what the ledger says earlier runs spent on it",
    )
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if (args.fetch_tgm or args.daily) and not (args.date_from and args.date_to):
            raise NansenError("--from and --to are required")
        if args.fetch or args.fetch_tgm:
            endpoint = ENDPOINT if args.fetch else TGM_ENDPOINT
            budget = CreditBudget(args.max_credits, cache_dir() / LEDGER, endpoint)
            log.info(
                "%s: %d of %d credits already spent according to the ledger",
                endpoint,
                budget.spent,
                budget.max_credits,
            )
            client = NansenClient(config.require_api_key("NANSEN_API_KEY"), budget)
            try:
                if args.fetch:
                    log.info("cached in %s", fetch(client, cache_dir()))
                else:
                    summary = fetch_tgm(
                        client,
                        cache_dir(),
                        args.fetch_tgm,
                        args.date_from,
                        args.date_to,
                        args.max_pages,
                    )
                    print(json.dumps(summary, indent=1))
            finally:
                log.info(
                    "requests sent: %d, credits spent on %s so far: %d of %d",
                    client.requests_sent,
                    endpoint,
                    budget.spent,
                    budget.max_credits,
                )
            return 0
        database = args.database or config.load_clickhouse_config().database
        if args.daily:
            trades, complete, pages = cached_tgm(
                cache_dir(), args.daily, args.date_from, args.date_to
            )
            if not pages:
                raise NansenError(
                    f"no cached page for {args.daily} {args.date_from}..{args.date_to}"
                )
            summary = store_daily(
                ch.connect(database="default"),
                database,
                args.daily,
                trades,
                complete,
                args.date_from,
                args.date_to,
            )
            print(
                json.dumps(
                    {**summary, "pages": pages, "trades": len(trades), "complete": complete},
                    indent=1,
                )
            )
            return 0
        files = cached_files(cache_dir())
        if not files:
            raise NansenError(f"nothing cached in {cache_dir()}: run --fetch first")
        envelope = json.loads(files[-1].read_text(encoding="utf-8"))
        result = cross(ch.connect(database="default"), database, envelope)
        args.out.write_text(render(result), encoding="utf-8")
        log.info("wrote %s", args.out)
        return 0
    except (NansenError, config.ConfigError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
