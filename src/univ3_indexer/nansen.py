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
from univ3_indexer.pools import load_pools
from univ3_indexer.reconcile import stable_leg_parameters, stablecoin_symbols

log = logging.getLogger("univ3_indexer.nansen")

BASE_URL = "https://api.nansen.ai/api/v1"
ENDPOINT = "smart-money/dex-trades"
DOCUMENTED_COST = {ENDPOINT: 5}  # credits per call, from the official cost table
DEFAULT_BUDGET = 8
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
    """Refuses a call whose documented cost does not fit in what is left."""

    def __init__(self, max_credits: int):
        self.max_credits, self.spent = max_credits, 0

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
        if not 1 <= per_page <= MAX_PER_PAGE or page < 1:
            raise ValueError(f"per_page must be between 1 and {MAX_PER_PAGE}, page at least 1")
        cost = DOCUMENTED_COST[ENDPOINT]
        self._budget.check(cost)
        request = {
            "chains": [CHAIN],
            "pagination": {"page": page, "per_page": per_page},
            "order_by": [{"field": "block_timestamp", "direction": "DESC"}],
        }
        self.requests_sent += 1
        try:
            response = self._session.post(
                f"{BASE_URL}/{ENDPOINT}",
                json=request,
                headers={"apikey": self._api_key, "Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            # It may have reached the server and been billed: count it, and never retry.
            self._budget.record(cost)
            raise NansenError(
                f"Nansen request failed ({type(exc).__name__}); not retried"
            ) from None
        quoted = _header_int(response, "X-Nansen-Credits-Cost")
        used = _header_int(response, "X-Nansen-Credits-Used")
        remaining = _header_int(response, "X-Nansen-Credits-Remaining")
        if used is None:
            used = cost if response.status_code == 200 else (quoted or 0)
        self._budget.record(used)
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
        "Generated by `python -m univ3_indexer.nansen --report`. Aggregates only: no transaction "
        "hash, address or label is written here. The raw response stays outside the repo.",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.nansen")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--fetch", action="store_true", help="ONE paid call, cached outside the repo"
    )
    action.add_argument("--report", action="store_true", help="cross the cached response; no call")
    parser.add_argument("--max-credits", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.fetch:
            budget = CreditBudget(args.max_credits)
            client = NansenClient(config.require_api_key("NANSEN_API_KEY"), budget)
            try:
                path = fetch(client, cache_dir())
            finally:
                log.info(
                    "requests sent: %d, credits spent: %d of %d",
                    client.requests_sent,
                    budget.spent,
                    budget.max_credits,
                )
            log.info("cached in %s", path)
            return 0
        files = cached_files(cache_dir())
        if not files:
            raise NansenError(f"nothing cached in {cache_dir()}: run --fetch first")
        envelope = json.loads(files[-1].read_text(encoding="utf-8"))
        database = args.database or config.load_clickhouse_config().database
        result = cross(ch.connect(database="default"), database, envelope)
        args.out.write_text(render(result), encoding="utf-8")
        log.info("wrote %s", args.out)
        return 0
    except (NansenError, config.ConfigError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
