"""Analyses that go beyond reconciliation, run from sql/analysis/ and written to one report.

Two questions, each answered by SQL files that can be read on their own:

* Round trips (10_ to 12_): how much of the reported activity is a swap undone by the same
  sender in the same block. Reads the dbt marts built from the definition in
  sql/reconciliation/16_evidence_round_trips.sql. Documented in docs/ROUND_TRIPS.md.
* Cross-pool (01_ to 03_): the price gap between the two pools of the same pair, how long a
  gap wider than the combined fee survives, and which pool moves first. ASOF JOIN on chain
  position. Documented in docs/CROSS_POOL.md.

Every query runs with the query condition cache OFF, so the rows it reports as read are what
the sorting key prunes and not what an earlier run left in the cache. For the cross-pool
queries the report also keeps `EXPLAIN indexes = 1`: granules selected by the primary key for
each scan.

Nothing is fetched and nothing is written to ClickHouse. The pair of pools is found in
pools.yml, never typed: two pools with the same token0 and token1 and different fees.

    PYTHONPATH=src uv run python -m univ3_indexer.analysis            # -> reports/analysis.md
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import sys
from pathlib import Path

from univ3_indexer import clickhouse as ch
from univ3_indexer import config
from univ3_indexer.pools import load_pools

log = logging.getLogger(__name__)

RAW_DB = "onchain"
DBT_DB = "onchain_dbt"
ANALYSIS_DIR = ch.SQL_DIR / "analysis"
SETTINGS = {"use_query_condition_cache": 0}

CROSS_POOL = (
    "01_cross_pool_gap.sql",
    "02_cross_pool_gap_histogram.sql",
    "03_cross_pool_episodes.sql",
)
ROUND_TRIPS = (
    "10_round_trips_by_pool.sql",
    "11_round_trips_by_hour.sql",
    "12_round_trips_concentration.sql",
)


class AnalysisError(RuntimeError):
    pass


def fee_tier_pairs(pools=None) -> list[dict]:
    """Every two pools of pools.yml that hold the same tokens in the same order at different
    fees, lower fee first. Refuses if there is none, or if a pair of tokens has three pools
    (the queries compare exactly two)."""
    pools = list(pools if pools is not None else load_pools())
    by_tokens: dict[tuple[str, str], list] = {}
    for p in pools:
        by_tokens.setdefault((p.token0, p.token1), []).append(p)
    if any(len(ps) > 2 for ps in by_tokens.values()):
        raise AnalysisError("a pair of tokens has more than two pools in pools.yml")
    out = []
    for ps in by_tokens.values():
        if len(ps) != 2:
            continue
        lo, hi = sorted(ps, key=lambda p: p.fee)
        out.append(
            {
                "lo": lo.key,
                "hi": hi.key,
                "lo_label": lo.label,
                "hi_label": hi.label,
                "pair": f"{lo.token0}/{lo.token1}",
                # fee is in hundredths of a basis point: 100 is 0.01% = 1 bp
                "fee_bps": (lo.fee + hi.fee) / 100.0,
            }
        )
    if not out:
        raise AnalysisError("no pair of tokens has two fee tiers in pools.yml")
    return sorted(out, key=lambda d: d["pair"])


def sql_of(name: str) -> str:
    return (
        ch.strip_sql_comments((ANALYSIS_DIR / name).read_text(encoding="utf-8")).strip().rstrip(";")
    )


def run(client, name: str, parameters: dict, database: str = RAW_DB) -> dict:
    """One query: its rows as dicts, and what ClickHouse says it read."""
    result = client.query(
        sql_of(name), parameters=parameters, settings={**SETTINGS, "database": database}
    )
    rows = [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]
    summary = result.summary or {}
    return {
        "name": name,
        "rows": rows,
        "read_rows": int(summary.get("read_rows", 0)),
        "read_bytes": int(summary.get("read_bytes", 0)),
        "memory_usage": int(summary.get("memory_usage", 0)),
        "elapsed_ms": int(summary.get("elapsed_ns", 0)) // 1_000_000,
    }


def granules(client, name: str, parameters: dict, database: str = RAW_DB) -> list[dict]:
    """For every table scan in the plan: the granules the primary key kept, out of how many."""
    result = client.query(
        "EXPLAIN indexes = 1 " + sql_of(name),
        parameters=parameters,
        settings={**SETTINGS, "database": database},
    )
    lines = [row[0] for row in result.result_rows]
    scans, table, in_pk = [], None, False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("ReadFromMergeTree"):
            table = re.search(r"\((.*)\)", stripped).group(1)
            in_pk = False
        elif stripped == "PrimaryKey":
            in_pk = True
        elif in_pk and stripped.startswith("Condition:"):
            condition = stripped[len("Condition: ") :]
        elif in_pk and stripped.startswith("Granules:"):
            kept, total = (int(x) for x in stripped.split(":")[1].strip().split("/"))
            scans.append({"table": table, "condition": condition, "kept": kept, "total": total})
            in_pk = False
    return scans


def cross_pool(client) -> dict:
    """The three cross-pool queries for every pair of fee tiers; EXPLAIN for the first."""
    out = {}
    for pair in fee_tier_pairs():
        params = {"lo": pair["lo"], "hi": pair["hi"], "fee_bps": pair["fee_bps"]}
        out[pair["pair"]] = {
            "pair": pair,
            "queries": {name: run(client, name, params) for name in CROSS_POOL},
            "explain": {CROSS_POOL[0]: granules(client, CROSS_POOL[0], params)},
        }
    return out


def round_trips(client) -> dict:
    params = {"dbt": DBT_DB}
    return {"queries": {name: run(client, name, params) for name in ROUND_TRIPS}}


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.6g}" if abs(v) < 1 else f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)\n"
    head = list(rows[0])
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(_fmt(r[h]) for h in head) + " |" for r in rows]
    return "\n".join(out) + "\n"


def render(result: dict, generated_at: datetime.datetime, max_block: int, rows: int) -> str:
    cp, rt = result["cross_pool"], result["round_trips"]
    parts = [
        "# Analysis report\n",
        f"Database `{RAW_DB}` ({rows:,} swaps, through block {max_block:,}) and the dbt marts "
        f"in `{DBT_DB}`, generated {generated_at:%Y-%m-%d %H:%M} UTC by `make analysis`. "
        "Numbers only; what they mean is in docs/ROUND_TRIPS.md and docs/CROSS_POOL.md. "
        "Every query ran with the query condition cache off.\n",
        "## Round trips in the same block\n",
    ]
    for name in ROUND_TRIPS:
        q = rt["queries"][name]
        parts.append(f"### {name}\n\nRead {q['read_rows']:,} rows in {q['elapsed_ms']:,} ms.\n")
        parts.append(_table(q["rows"]))
    for name_of_pair, one in cp.items():
        pair = one["pair"]
        parts.append(
            f"## Cross-pool: {pair['lo_label']} against {pair['hi_label']}\n\n"
            f"Combined fee: {pair['fee_bps']:g} bps. `lo` is {pair['lo_label']}, `hi` is "
            f"{pair['hi_label']}.\n"
        )
        for name in CROSS_POOL:
            q = one["queries"][name]
            parts.append(
                f"### {name_of_pair}: {name}\n\nRead {q['read_rows']:,} rows "
                f"({q['read_bytes']:,} bytes) in {q['elapsed_ms']:,} ms, "
                f"{q['memory_usage']:,} bytes of memory.\n"
            )
            parts.append(_table(q["rows"]))
        parts.append(
            f"### {name_of_pair}: what the primary key kept, per scan of {CROSS_POOL[0]}\n"
        )
        parts.append(_table(one["explain"][CROSS_POOL[0]]))
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", type=Path, default=config.REPO_ROOT / "reports" / "analysis.md")
    ap.add_argument("--generated-at", default=None, help="ISO timestamp, default now (UTC)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    now = (
        datetime.datetime.fromisoformat(args.generated_at)
        if args.generated_at
        else datetime.datetime.now(datetime.UTC)
    )
    client = ch.connect(RAW_DB)
    rows, max_block = client.query(
        "SELECT count(), max(block_number) FROM raw_swaps", settings={"database": RAW_DB}
    ).result_rows[0]
    try:
        result = {"round_trips": round_trips(client), "cross_pool": cross_pool(client)}
    except AnalysisError as exc:
        log.error("%s", exc)
        return 2
    result["generated_at"] = now.strftime("%Y-%m-%d %H:%M UTC")
    result["raw_swaps"] = rows
    result["max_block"] = max_block
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(result, now, max_block, rows), encoding="utf-8")
    args.report.with_suffix(".json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    log.info("wrote %s and %s", args.report, args.report.with_suffix(".json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
