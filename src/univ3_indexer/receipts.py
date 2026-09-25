"""Transaction receipts for the swaps of one pool in one hour, and what they show in aggregate.

Built for one question: the largest open case of the reconciliation
(docs/RECONCILIATION_FINDINGS.md, USDC/WETH 0.05% on 2026-08-19), whose difference sits mostly
in one hour. A Swap log says which contract called the pool; a receipt adds who signed the
transaction, what else the transaction touched, and what it paid in gas.

* Only transactions that hold a Swap of that pool in that hour are asked for, and the list
  comes from ``raw_swaps``: nothing is fetched speculatively.
* A hard cap on calls (``--max-calls``). The run refuses to start when the transactions that
  are not cached yet would need more than that, instead of stopping half way.
* Every receipt is cached as one JSON file per transaction, OUTSIDE the repository: a receipt
  names every account involved. A second run fetches only what is missing, and ``--report``
  never calls the node.
* What the report carries is aggregates: counts, shares and distributions. It prints no
  address and no transaction hash, and it ranks senders instead of naming them.

    # as root (the API key is root's), once:
    PYTHONPATH=src python -m univ3_indexer.receipts --pool "USDC/WETH 0.05%" \\
        --day 2026-08-19 --hour 15 --fetch --max-calls 1000
    # any time after, no network:
    PYTHONPATH=src python -m univ3_indexer.receipts --pool "USDC/WETH 0.05%" \\
        --day 2026-08-19 --hour 15 --report reports/receipts_2026-08-19_15h.md
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

from univ3_indexer import clickhouse as ch
from univ3_indexer import config, reconcile
from univ3_indexer.abi import (
    SWAP_TOPIC0,
    TOPIC_V2_SWAP,
    TOPIC_V4_SWAP,
    TOPIC_WETH_DEPOSIT,
    TOPIC_WETH_WITHDRAWAL,
)
from univ3_indexer.addresses import is_address, normalize
from univ3_indexer.pools import load_pools

log = logging.getLogger(__name__)

DEFAULT_MAX_CALLS = 1000
# What a transaction is labelled when it emitted no other Swap (v2, v3-style, v4) and no WETH
# wrap: it may still carry other protocols' events, which are not classified here.
NO_OTHER_SWAP = "no other swap, and no WETH wrap or unwrap"
OTHER_SWAPS = {
    "another tracked pool",
    "an untracked v3-style pool",
    "a v2-style pair",
    "the v4 pool manager",
}
DATABASE = "onchain"

# One row per transaction that holds at least one Swap of the pool in the hour, with what
# raw_swaps says about it: how many swaps of THIS pool it holds, their gross USD (every swap
# counted) and their net USD (the stable leg summed with its sign first, so a buy and a sell
# inside one transaction cancel).
SQL_TRANSACTIONS = """
WITH
    arrayElement({stable_is_token0:Array(UInt8)},
                 indexOf({stable_pools:Array(String)}, {pool:String})) = 1 AS stable_is_0,
    arrayElement({stable_decimals:Array(UInt8)},
                 indexOf({stable_pools:Array(String)}, {pool:String}))      AS stable_dec
SELECT
    concat('0x', lower(hex(tx_hash)))                                        AS tx,
    count()                                                                  AS swaps,
    sum(toFloat64(abs(if(stable_is_0, amount0, amount1)))) / pow(10, stable_dec) AS gross_usd,
    abs(toFloat64(sum(if(stable_is_0, amount0, amount1)))) / pow(10, stable_dec) AS net_usd,
    min(block_number)                                                        AS block_number,
    groupUniqArray(concat('0x', lower(hex(sender))))                         AS swap_senders
FROM raw_swaps
WHERE pool_address = {pool:String}
  AND block_timestamp >= toDateTime({day:Date}, 'UTC') + toIntervalHour({hour:UInt8})
  AND block_timestamp <  toDateTime({day:Date}, 'UTC') + toIntervalHour({hour:UInt8} + 1)
GROUP BY tx_hash
ORDER BY block_number, tx
"""


class ReceiptsError(RuntimeError):
    pass


def transactions(client, database: str, pool: str, day: datetime.date, hour: int) -> list[dict]:
    stable = reconcile.stable_leg_parameters(load_pools(), reconcile.stablecoin_symbols())
    params = {**stable, "pool": pool, "day": day, "hour": hour}
    result = client.query(SQL_TRANSACTIONS, parameters=params, settings={"database": database})
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def cache_dir_for(root: Path, pool: str, day: datetime.date, hour: int) -> Path:
    return root / f"{normalize(pool)}_{day.isoformat()}_{hour:02d}h"


def cached(cache_dir: Path, tx: str) -> dict | None:
    path = cache_dir / f"{tx}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def fetch(rpc, txs: list[str], cache_dir: Path, max_calls: int) -> dict:
    """Receipts for ``txs``: from the cache when there, from the node otherwise. Refuses up
    front when the missing ones exceed ``max_calls``; stops if retries push past it."""
    missing = [tx for tx in txs if not (cache_dir / f"{tx}.json").exists()]
    if len(missing) > max_calls:
        raise ReceiptsError(
            f"{len(missing)} receipts are not cached and --max-calls is {max_calls}: refusing"
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cache_dir, 0o700)
    fetched = 0
    for tx in missing:
        if rpc.requests_sent >= max_calls:
            raise ReceiptsError(f"stopped at the cap: {rpc.requests_sent} calls, {max_calls}")
        receipt = rpc.call("eth_getTransactionReceipt", [tx])
        if not isinstance(receipt, dict) or receipt.get("transactionHash", "").lower() != tx:
            raise ReceiptsError("the node answered a receipt for another transaction, or none")
        tmp = cache_dir / f".{tx}.json.tmp"
        tmp.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(cache_dir / f"{tx}.json")
        fetched += 1
    return {
        "asked": len(missing),
        "fetched": fetched,
        "calls": rpc.requests_sent,
        "retries": getattr(rpc, "retries", 0),
        "cached_before": len(txs) - len(missing),
    }


def verified_token(symbol: str) -> str:
    """A token address as the on-chain verification of the pools recorded it
    (docs/verification/pools-*.json: symbol() and the address it was read from). Never typed:
    AGENTS.md forbids writing a token address anywhere. Refuses if the files disagree."""
    found = set()
    for path in sorted((config.REPO_ROOT / "docs" / "verification").glob("pools-*.json")):
        for pool in json.loads(path.read_text(encoding="utf-8")).get("pools", []):
            for side in ("token0", "token1"):
                token = pool.get(side) or {}
                if isinstance(token, dict) and token.get("symbol") == symbol:
                    found.add(normalize(token["address"]))
    if len(found) != 1:
        raise ReceiptsError(f"{symbol}: {len(found)} verified addresses, expected exactly one")
    return found.pop()


def _addr(value: str | None) -> str:
    """An address from a receipt, comparable; '' for none (a contract creation has no `to`)."""
    return normalize(value) if value else ""


def _topic0(log_entry: dict) -> str:
    topics = log_entry.get("topics") or [""]
    return topics[0].lower()


def _buckets(counter: Counter) -> dict:
    return {("5+" if k == 5 else str(k)): v for k, v in sorted(counter.items())}


def _pct(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole else 0.0


def _quantile(values: list[float], q: float) -> float:
    """The median for q = 0.5 (the mean of the two middle values when n is even); otherwise
    the nearest-rank quantile, which is what the report calls a percentile."""
    if not values:
        return 0.0
    if q == 0.5:
        return statistics.median(values)
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def summarize(
    pool: str, rows: list[dict], receipts: dict, tracked: dict[str, str], weth: str = ""
) -> dict:
    """Aggregates only. ``tracked`` maps the addresses of pools.yml to their labels; ``weth``
    is the WETH9 contract, the only emitter whose Deposit and Withdrawal count as a wrap."""
    pool = normalize(pool)
    weth = normalize(weth) if weth else ""
    tracked = {normalize(k): v for k, v in tracked.items()}
    by_tx = {r["tx"]: r for r in rows}
    missing = [tx for tx in by_tx if tx not in receipts]
    if missing:
        raise ReceiptsError(f"{len(missing)} transactions have no cached receipt: fetch first")

    signers: Counter = Counter()
    signer_usd: Counter = Counter()
    targets: Counter = Counter()
    v3_swaps_per_tx: Counter = Counter()
    this_pool_swaps_per_tx: Counter = Counter()
    touches: Counter = Counter()
    touches_usd: Counter = Counter()
    with_another_swap, with_another_swap_usd = 0, 0.0
    usd_first_slots = 0.0
    contracts_per_tx: list[int] = []
    gas_used: list[float] = []
    gas_price_gwei: list[float] = []
    fee_eth = 0.0
    tx_index: list[int] = []
    status: Counter = Counter()
    tx_type: Counter = Counter()
    target_is_swap_sender = 0

    for tx, row in by_tx.items():
        rc = receipts[tx]
        signer = _addr(rc.get("from"))
        target = _addr(rc.get("to"))
        signers[signer] += 1
        signer_usd[signer] += row["gross_usd"]
        targets[target] += 1
        if target and target in {_addr(s) for s in row["swap_senders"]}:
            target_is_swap_sender += 1
        logs = rc.get("logs") or []
        emitters = {_addr(lg.get("address")) for lg in logs}
        contracts_per_tx.append(len(emitters))
        v3 = [lg for lg in logs if _topic0(lg) == SWAP_TOPIC0]
        v3_swaps_per_tx[min(len(v3), 5)] += 1
        here = sum(1 for lg in v3 if _addr(lg.get("address")) == pool)
        this_pool_swaps_per_tx[min(here, 5)] += 1
        kinds = set()
        for lg in logs:
            topic = _topic0(lg)
            where = _addr(lg.get("address"))
            if topic == SWAP_TOPIC0 and where != pool:
                kinds.add(
                    "another tracked pool" if where in tracked else "an untracked v3-style pool"
                )
            elif topic == TOPIC_V2_SWAP:
                kinds.add("a v2-style pair")
            elif topic == TOPIC_V4_SWAP:
                kinds.add("the v4 pool manager")
            elif topic in (TOPIC_WETH_DEPOSIT, TOPIC_WETH_WITHDRAWAL) and where == weth:
                kinds.add("a WETH wrap or unwrap")
        if kinds & OTHER_SWAPS:
            with_another_swap += 1
            with_another_swap_usd += row["gross_usd"]
        if not kinds:
            kinds.add(NO_OTHER_SWAP)
        for kind in kinds:
            touches[kind] += 1
            touches_usd[kind] += row["gross_usd"]
        used = int(rc.get("gasUsed", "0x0"), 16)
        price = int(rc.get("effectiveGasPrice", "0x0"), 16)
        gas_used.append(used)
        gas_price_gwei.append(price / 1e9)
        fee_eth += used * price / 1e18
        tx_index.append(int(rc.get("transactionIndex", "0x0"), 16))
        if tx_index[-1] <= 2:
            usd_first_slots += row["gross_usd"]
        status["success" if rc.get("status") == "0x1" else "reverted"] += 1
        tx_type[f"type {int(rc.get('type', '0x0'), 16)}"] += 1

    n = len(by_tx)
    gross = sum(r["gross_usd"] for r in rows)
    net = sum(r["net_usd"] for r in rows)
    multi = [r for r in rows if r["swaps"] > 1]
    ranked_usd = [v for _, v in signer_usd.most_common()]
    ranked_tx = [v for _, v in signers.most_common()]
    return {
        "transactions": n,
        "swaps_in_this_pool": sum(r["swaps"] for r in rows),
        "gross_usd": gross,
        "net_usd_within_each_transaction": net,
        "transactions_with_more_than_one_swap_here": len(multi),
        "their_gross_usd": sum(r["gross_usd"] for r in multi),
        "their_net_usd": sum(r["net_usd"] for r in multi),
        "status": dict(status),
        "tx_type": dict(sorted(tx_type.items())),
        "distinct_signers": len(signers),
        "top1_signer_share_of_transactions": _pct(sum(ranked_tx[:1]), n),
        "top5_signers_share_of_transactions": _pct(sum(ranked_tx[:5]), n),
        "top1_signer_share_of_usd": _pct(sum(ranked_usd[:1]), gross),
        "top5_signers_share_of_usd": _pct(sum(ranked_usd[:5]), gross),
        "distinct_contracts_called": len(targets),
        "top1_contract_share_of_transactions": _pct(targets.most_common(1)[0][1], n) if n else 0.0,
        "contract_called_is_the_swap_sender": target_is_swap_sender,
        "v3_swap_logs_per_transaction": _buckets(v3_swaps_per_tx),
        "swaps_of_this_pool_per_transaction": _buckets(this_pool_swaps_per_tx),
        "transactions_that_also_touch": dict(touches.most_common()),
        "usd_of_transactions_that_also_touch": {
            k: touches_usd[k] for k, _ in touches.most_common()
        },
        "usd_in_the_first_three_slots": usd_first_slots,
        "transactions_with_another_swap": with_another_swap,
        "usd_of_transactions_with_another_swap": with_another_swap_usd,
        "contracts_emitting_logs_p50": _quantile(contracts_per_tx, 0.5),
        "contracts_emitting_logs_p90": _quantile(contracts_per_tx, 0.9),
        "gas_used_p50": _quantile(gas_used, 0.5),
        "gas_used_p90": _quantile(gas_used, 0.9),
        "gas_used_max": max(gas_used) if gas_used else 0,
        "gas_price_gwei_p50": _quantile(gas_price_gwei, 0.5),
        "gas_price_gwei_p90": _quantile(gas_price_gwei, 0.9),
        "fees_paid_eth": fee_eth,
        "position_in_block_p50": _quantile(tx_index, 0.5),
        "transactions_in_the_first_three_slots": sum(1 for i in tx_index if i <= 2),
        "gas_used_mean": statistics.fmean(gas_used) if gas_used else 0.0,
    }  # fmt: skip


def _rows(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"| {k} | {v} |" for k, v in pairs)


def render(label: str, day: datetime.date, hour: int, s: dict, fetch_note: str) -> str:
    """Markdown with numbers only: no address, no hash, senders ranked and never named."""

    def table(d: dict) -> str:
        return "\n".join(f"| {k} | {v:,} |" for k, v in d.items())

    hour_rows = _rows([
        ("transactions", f"{s['transactions']:,}"),
        ("swaps of this pool", f"{s['swaps_in_this_pool']:,}"),
        ("USD, every swap counted (what the pipeline reports)", f"{s['gross_usd']:,.0f}"),
        ("USD, netted inside each transaction first",
         f"{s['net_usd_within_each_transaction']:,.0f}"),
        ("transactions with more than one swap of this pool",
         f"{s['transactions_with_more_than_one_swap_here']:,}"),
        ("their USD, every swap counted", f"{s['their_gross_usd']:,.0f}"),
        ("their USD, netted inside the transaction", f"{s['their_net_usd']:,.0f}"),
    ])  # fmt: skip
    who_rows = _rows([
        ("distinct accounts that signed", f"{s['distinct_signers']:,}"),
        ("share of transactions signed by the largest one",
         f"{s['top1_signer_share_of_transactions']:.1f}%"),
        ("share of transactions signed by the largest five",
         f"{s['top5_signers_share_of_transactions']:.1f}%"),
        ("share of the hour's USD signed by the largest one",
         f"{s['top1_signer_share_of_usd']:.1f}%"),
        ("share of the hour's USD signed by the largest five",
         f"{s['top5_signers_share_of_usd']:.1f}%"),
        ("distinct contracts called (`to`)", f"{s['distinct_contracts_called']:,}"),
        ("share of transactions calling the most-called one",
         f"{s['top1_contract_share_of_transactions']:.1f}%"),
        ("transactions whose `to` is also the `sender` of its Swap log",
         f"{s['contract_called_is_the_swap_sender']:,}"),
        ("status", ", ".join(f"{k} {v:,}" for k, v in s["status"].items())),
        ("transaction type", ", ".join(f"{k} {v:,}" for k, v in s["tx_type"].items())),
    ])  # fmt: skip
    touch_rows = "\n".join(
        f"| {k} | {v:,} | {s['usd_of_transactions_that_also_touch'][k]:,.0f} |"
        for k, v in s["transactions_that_also_touch"].items()
    )
    gas_rows = _rows([
        ("gas used, median", f"{s['gas_used_p50']:,.0f}"),
        ("gas used, 90th percentile", f"{s['gas_used_p90']:,.0f}"),
        ("gas used, largest", f"{s['gas_used_max']:,.0f}"),
        ("effective gas price, median (gwei)", f"{s['gas_price_gwei_p50']:.3f}"),
        ("effective gas price, 90th percentile (gwei)", f"{s['gas_price_gwei_p90']:.3f}"),
        ("fees paid by all of them (ETH)", f"{s['fees_paid_eth']:.4f}"),
        ("position in the block, median", f"{s['position_in_block_p50']:,.0f}"),
        ("transactions in the first three positions of their block",
         f"{s['transactions_in_the_first_three_slots']:,}"),
        ("USD of this pool's swaps in those", f"{s['usd_in_the_first_three_slots']:,.0f}"),
    ])  # fmt: skip
    return f"""# Receipts: {label}, {day.isoformat()}, {hour:02d}:00-{hour + 1:02d}:00 UTC

Every transaction that holds a Swap of this pool in this hour, from `raw_swaps`, and its
receipt from the node (`eth_getTransactionReceipt`). Aggregates only: this report names no
account and no transaction. {fetch_note}

## What `raw_swaps` holds for the hour

| | |
|---|---|
{hour_rows}

## Who signed, and what they called

| | |
|---|---|
{who_rows}

## What else each transaction touched

Swap logs with the Uniswap v3 event signature per transaction, any emitter (5+ grouped):

| logs | transactions |
|---|---|
{table(s["v3_swap_logs_per_transaction"])}

Swaps of this pool per transaction:

| swaps | transactions |
|---|---|
{table(s["swaps_of_this_pool_per_transaction"])}

Transactions that also emitted a log from, and the USD of this pool's swaps in them (a
transaction can be in more than one row, so the USD column does not add up to the hour):

| | transactions | USD of this pool's swaps |
|---|---|---|
{touch_rows}

Transactions with at least one swap in another pool (any row above but the WETH one):
{s["transactions_with_another_swap"]:,}, with {s["usd_of_transactions_with_another_swap"]:,.0f}
USD of this pool's swaps.

Contracts emitting a log, per transaction: median {s["contracts_emitting_logs_p50"]:,.0f},
90th percentile {s["contracts_emitting_logs_p90"]:,.0f}.

## Gas and position in the block

| | |
|---|---|
{gas_rows}
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pool", required=True, help="label or address, as in pools.yml")
    ap.add_argument("--day", required=True, type=datetime.date.fromisoformat)
    ap.add_argument("--hour", required=True, type=int, choices=range(24))
    ap.add_argument("--fetch", action="store_true", help="ask the node for missing receipts")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    ap.add_argument("--rps", type=float, default=5.0)
    ap.add_argument("--cache-dir", type=Path, help="default: <data dir>/receipts")
    ap.add_argument("--report", type=Path, help="write the aggregate report here")
    ap.add_argument("--database", default=DATABASE)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pools = {p.key: p.label for p in load_pools()}
    labels = {v: k for k, v in pools.items()}
    pool = labels.get(args.pool) or (normalize(args.pool) if is_address(args.pool) else "")
    if pool not in pools:
        log.error("%s is not a pool of pools.yml", args.pool)
        return 2
    root = (args.cache_dir or config.data_dir() / "receipts").resolve()
    if root == config.REPO_ROOT or config.REPO_ROOT in root.parents:
        log.error("the receipt cache must live outside the working copy")
        return 2
    cache_dir = cache_dir_for(root, pool, args.day, args.hour)

    client = ch.connect(args.database)
    rows = transactions(client, args.database, pool, args.day, args.hour)
    log.info("%d transactions hold a swap of %s in that hour", len(rows), pools[pool])
    note = ""
    if args.fetch:
        from univ3_indexer.rpc import JsonRpcClient, alchemy_mainnet_url

        key = config.require_api_key("ALCHEMY_API_KEY")
        rpc = JsonRpcClient(alchemy_mainnet_url(key), min_interval=1 / args.rps)
        try:
            outcome = fetch(rpc, [r["tx"] for r in rows], cache_dir, args.max_calls)
        except ReceiptsError as exc:
            log.error("%s", exc)
            return 3
        log.info("receipts: %s", outcome)
        print(json.dumps(outcome))
    if args.report:
        receipts = {r["tx"]: cached(cache_dir, r["tx"]) for r in rows}
        receipts = {k: v for k, v in receipts.items() if v is not None}
        try:
            summary = summarize(pool, rows, receipts, pools, verified_token("WETH"))
        except ReceiptsError as exc:
            log.error("%s", exc)
            return 3
        note = (
            f"{len(receipts):,} receipts, cached outside the repository; built "
            f"{datetime.datetime.now(datetime.UTC):%Y-%m-%d %H:%M} UTC."
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            render(pools[pool], args.day, args.hour, summary, note), encoding="utf-8"
        )
        (args.report.with_suffix(".json")).write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        log.info("wrote %s", args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
