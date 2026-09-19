"""Reconciliation: A internal (must be exactly zero), B external (reported, with a threshold).

    python -m univ3_indexer.reconcile                       # -> reports/reconciliation.{csv,md}
    python -m univ3_indexer.reconcile --threshold 0.01 --evidence

A  The recomputation in sql/reconciliation/ against swaps_daily, in raw units. Both come
   from the same rows, so the only acceptable difference is none. ANY difference makes
   the command exit non-zero.
B  Our USD volume against the external source, per pool and day. Two independent
   pipelines with different, partly undocumented methods are not expected to be equal.
   Every pool-day is reported with both values and the difference; the ones beyond the
   threshold are counted and listed, and days present on one side only are listed
   apart. B does NOT change the exit code unless --fail-on-external is given: what a
   difference in B means is for a person to decide, not for a script.

--evidence also writes reports/reconciliation_evidence.md: numbers only, no conclusions.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from univ3_indexer import clickhouse as ch
from univ3_indexer import config, external
from univ3_indexer.pools import Pool, load_pools

SQL = ch.SQL_DIR / "reconciliation"
REPORTS = config.REPO_ROOT / "reports"
DEFAULT_THRESHOLD = 0.01
SHIFTS = range(-12, 13)
PENDING = "PENDIENTE — lo escribe Roberto"


def _sql(name: str) -> str:
    return ch.strip_sql_comments((SQL / name).read_text(encoding="utf-8")).strip().rstrip(";")


def stablecoin_symbols() -> list[str]:
    """The single list of what counts as a dollar lives in dbt/dbt_project.yml."""
    project = yaml.safe_load((config.REPO_ROOT / "dbt" / "dbt_project.yml").read_text())
    return list(project["vars"]["stablecoin_symbols"])


def stable_leg_parameters(pools: list[Pool], stables: list[str]) -> dict:
    """Three aligned arrays for the SQL: which pools have a stable leg, which leg, decimals.
    Same rule as stg_swaps: if both tokens are stable, token0 wins."""
    chosen, is_token0, decimals = [], [], []
    for pool in pools:
        if pool.token0 in stables:
            chosen.append(str(pool.key)), is_token0.append(1), decimals.append(pool.decimals0)
        elif pool.token1 in stables:
            chosen.append(str(pool.key)), is_token0.append(0), decimals.append(pool.decimals1)
    return {"stable_pools": chosen, "stable_is_token0": is_token0, "stable_decimals": decimals}


@dataclass
class Result:
    internal: list[dict] = field(default_factory=list)  # A: rows that differ (expected none)
    external: list[dict] = field(default_factory=list)  # B: every pool-day on either side
    threshold: float = DEFAULT_THRESHOLD
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def both(self) -> list[dict]:
        return [r for r in self.external if r["presence"] == "both"]

    @property
    def over_threshold(self) -> list[dict]:
        return [
            r
            for r in self.both
            if r["rel_diff"] is not None and abs(r["rel_diff"]) > self.threshold
        ]  # noqa: E501

    @property
    def one_sided(self) -> list[dict]:
        return [r for r in self.external if r["presence"] != "both"]

    @property
    def internal_ok(self) -> bool:
        return not self.internal


def _rows(client, database: str, name: str, parameters: dict | None = None) -> list[dict]:
    result = client.query(_sql(name), parameters=parameters or {}, settings={"database": database})
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def run(
    client,
    database: str,
    threshold: float = DEFAULT_THRESHOLD,
    pools=None,
    internal_only: bool = False,
) -> Result:
    """``internal_only`` runs A alone: for a database that has no external table at all."""
    ch.qualified(database)
    pools = pools if pools is not None else load_pools()
    parameters = {**stable_leg_parameters(pools, stablecoin_symbols()), "source": external.SOURCE}
    return Result(
        internal=_rows(client, database, "02_internal_a.sql"),
        external=[] if internal_only else _rows(client, database, "03_external_b.sql", parameters),
        threshold=threshold,
        labels={str(p.key): p.label for p in pools},
    )


# --- reports ------------------------------------------------------------------------------

CSV_COLUMNS = ["pool", "pool_address", "date", "presence", "partial_day", "our_swaps",
               "our_volume_usd", "external_volume_usd", "abs_diff_usd", "rel_diff",
               "over_threshold"]  # fmt: skip


def write_csv(result: Result, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for r in result.external:
            over = r["rel_diff"] is not None and abs(r["rel_diff"]) > result.threshold
            writer.writerow([
                result.labels.get(r["pool_address"], ""), r["pool_address"], r["date"], r["presence"],
                int(r["partial_day"]), r["our_swaps"], r["our_volume_usd"], r["external_volume_usd"],
                r["abs_diff_usd"], "" if r["rel_diff"] is None else r["rel_diff"], int(over),
            ])  # fmt: skip


def _pct(value: float | None) -> str:
    return "" if value is None else f"{100 * value:+.2f}%"


def _usd(value: float) -> str:
    return f"{value:,.0f}"


def per_pool_summary(result: Result, include_partial: bool) -> list[dict]:
    summary = []
    for address, label in result.labels.items():
        rows = [r for r in result.both if r["pool_address"] == address
                and (include_partial or not r["partial_day"])]  # fmt: skip
        if not rows:
            continue
        ours = sum(r["our_volume_usd"] for r in rows)
        theirs = sum(r["external_volume_usd"] for r in rows)
        rel = [r["rel_diff"] for r in rows if r["rel_diff"] is not None]
        summary.append({
            "pool": label, "days": len(rows), "ours": ours, "external": theirs,
            "total_rel_diff": (ours - theirs) / theirs if theirs else None,
            "median_rel_diff": statistics.median(rel) if rel else None,
            "max_abs_rel_diff": max((abs(x) for x in rel), default=None),
            "days_over": sum(1 for x in rel if abs(x) > result.threshold),
        })  # fmt: skip
    return summary


def render(result: Result, database: str) -> str:
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Reconciliation report", "",
        f"Database `{database}`, generated {now} by `make reconcile`. "
        f"Threshold for B: **{100 * result.threshold:g}%** (`--threshold`).", "",
        "## Summary", "",
        f"- **A, internal** (recomputation from `raw_swaps` vs `swaps_daily`, raw units): "
        f"**{'exact, 0 differences' if result.internal_ok else f'FAILED, {len(result.internal)} pool-day(s) differ'}**.",  # noqa: E501
        f"- **B, external** (our `volume_usd` vs {external.SOURCE}): {len(result.both)} pool-days "
        f"present on both sides, **{len(result.over_threshold)} beyond the threshold**, "
        f"{len(result.one_sided)} present on one side only.",
        "- The exit code reflects A only. What the differences in B mean is not decided here.", "",
    ]  # fmt: skip
    for include_partial, title in (
        (True, "all days"),
        (False, "excluding the first and last day of the window, which are partial on our side"),
    ):  # noqa: E501
        lines += [f"### B per pool, {title}", "",
                  "| Pool | Days | Ours USD | External USD | Total diff | Median daily diff | Largest daily diff (absolute) | Days beyond threshold |",  # noqa: E501
                  "|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for s in per_pool_summary(result, include_partial):
            lines.append(
                f"| {s['pool']} | {s['days']} | {_usd(s['ours'])} | {_usd(s['external'])} | "
                f"{_pct(s['total_rel_diff'])} | {_pct(s['median_rel_diff'])} | "
                f"{100 * s['max_abs_rel_diff']:.2f}% | {s['days_over']} |"
            )
        lines.append("")
    lines += ["## A: differences (expected: none)", ""]
    if result.internal_ok:
        lines.append("None.")
    else:
        lines += [
            "| pool | date | problem | recomputed swaps | view swaps |",
            "|---|---|---|---|---|",
        ]
        lines += [f"| {result.labels.get(r['pool_address'], r['pool_address'])} | {r['block_date']} | "
                  f"{r['problem']} | {r['recomputed_swaps']} | {r['view_swaps']} |"
                  for r in result.internal[:50]]  # fmt: skip
    lines += ["", "## B: days present on one side only", ""]
    if not result.one_sided:
        lines.append("None.")
    else:
        lines += ["| pool | date | present | our USD | external USD |", "|---|---|---|---|---|"]
        lines += [f"| {result.labels.get(r['pool_address'], r['pool_address'])} | {r['date']} | "
                  f"{r['presence']} | {_usd(r['our_volume_usd'])} | {_usd(r['external_volume_usd'])} |"
                  for r in result.one_sided]  # fmt: skip
    lines += ["", f"## B: pool-days beyond {100 * result.threshold:g}%", "",
              "| pool | date | partial day | our USD | external USD | abs diff USD | rel diff |",
              "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in sorted(result.over_threshold, key=lambda r: -abs(r["rel_diff"])):
        lines.append(
            f"| {result.labels.get(r['pool_address'], '')} | {r['date']} | "
            f"{'yes' if r['partial_day'] else ''} | {_usd(r['our_volume_usd'])} | "
            f"{_usd(r['external_volume_usd'])} | {_usd(r['abs_diff_usd'])} | {_pct(r['rel_diff'])} |"
        )
    lines += ["", "Every pool-day, with both values, is in `reconciliation.csv`.", ""]
    return "\n".join(lines)


# --- evidence: numbers, no conclusions --------------------------------------------------------


def _quantiles(values: list[float]) -> str:
    if not values:
        return "| | | | | |"
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]  # noqa: E731
    return " | ".join(_pct(v) for v in (ordered[0], pick(0.25), pick(0.5), pick(0.75), ordered[-1]))


def render_evidence(client, database: str, result: Result, pools=None) -> str:
    pools = pools if pools is not None else load_pools()
    parameters = {**stable_leg_parameters(pools, stablecoin_symbols()), "source": external.SOURCE}
    days = sorted({r["date"] for r in result.both})
    first_full, last_full = days[1], days[-2]
    labels = result.labels
    out = [
        "# Reconciliation evidence", "",
        "Numbers only. This file describes what was measured; it does not say why, and it does "
        "not say what is acceptable.", "",
        "## Hallazgos", "", PENDING, "",
        "## 1. Day boundary", "",
        f"Our volume recomputed with the day cut moved from -12 h to +12 h in steps of 1 h, "
        f"against the external days, over {first_full} to {last_full} (days complete on our side "
        "under every shift). A positive shift moves swaps from late in the day into the next day. "
        "Cell: sum of |our day - external day| divided by the external total.", "",
    ]  # fmt: skip
    table: dict[str, dict[int, float]] = {}
    for shift in SHIFTS:
        rows = _rows(client, database, "10_evidence_day_boundary.sql",
                     {**parameters, "shift_hours": shift, "first_full_day": first_full,
                      "last_full_day": last_full})  # fmt: skip
        for r in rows:
            table.setdefault(r["pool_address"], {})[shift] = r["abs_diff_over_external"]
    out += ["| Shift (h) | " + " | ".join(labels[a] for a in table) + " |",
            "|---|" + "---|" * len(table)]  # fmt: skip
    for shift in SHIFTS:
        out.append(
            f"| {shift:+d} | " + " | ".join(f"{100 * table[a][shift]:.2f}%" for a in table) + " |"
        )  # noqa: E501
    out += [
        "",
        "| Pool | Shift with the smallest value | Value there | Value at shift 0 |",
        "|---|---|---|---|",
    ]  # noqa: E501
    for address, by_shift in table.items():
        best = min(by_shift, key=by_shift.get)
        out.append(
            f"| {labels[address]} | {best:+d} h | {100 * by_shift[best]:.2f}% | {100 * by_shift[0]:.2f}% |"
        )  # noqa: E501

    out += ["", "## 2. The stablecoin leg against the other leg at the pool's own price", "",
            "Same swaps valued two ways: the stablecoin leg at 1 USD, and the other leg converted "
            "at the pool price right after each swap (`sqrt_price_x96`). Swaps with a zero leg "
            "are left out of this table, and so are swaps that left the pool at the price limit "
            "(|tick| > 800,000), which are counted in their own column.", "",
            "| Pool | Swaps valued | Swaps at the price limit | Stable leg USD | Other leg USD | Other / stable - 1 | Per swap: p1 | median | p99 |",  # noqa: E501
            "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in _rows(client, database, "11_evidence_stablecoin_leg.sql", parameters):
        out.append(f"| {labels[r['pool_address']]} | {r['swaps']:,} | {r['swaps_at_price_limit']} | {_usd(r['stable_leg_usd'])} | "
                   f"{_usd(r['other_leg_usd'])} | {100 * r['other_over_stable_minus_1']:+.4f}% | "
                   f"{100 * r['p01_per_swap']:+.4f}% | {100 * r['median_per_swap']:+.4f}% | "
                   f"{100 * r['p99_per_swap']:+.4f}% |")  # fmt: skip

    out += ["", "## 3. Distribution of the daily relative difference (ours - external) / external", "",
            "Full days only (first and last day of the window excluded).", "",
            "| Pool | Days | min | p25 | median | p75 | max |", "|---|---|---|---|---|---|---|"]  # fmt: skip
    full = [r for r in result.both if not r["partial_day"] and r["rel_diff"] is not None]
    for address, label in labels.items():
        values = [r["rel_diff"] for r in full if r["pool_address"] == address]
        out.append(f"| {label} | {len(values)} | {_quantiles(values)} |")
    out += ["", "By activity level: pool-days sorted by our number of swaps and cut in three "
            "groups of equal size.", "",
            "| Activity | Pool-days | Swaps per day (range) | min | p25 | median | p75 | max |",
            "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    ranked = sorted(full, key=lambda r: r["our_swaps"])
    third = max(1, len(ranked) // 3)
    for name, group in (("low", ranked[:third]), ("middle", ranked[third:2 * third]),
                        ("high", ranked[2 * third:])):  # fmt: skip
        if group:
            out.append(f"| {name} | {len(group)} | {group[0]['our_swaps']:,} to {group[-1]['our_swaps']:,} | "
                       f"{_quantiles([r['rel_diff'] for r in group])} |")  # fmt: skip

    out += ["", "## 4. Partial days", "",
            "The first and the last day of the window are incomplete on our side: the backfill "
            "starts and ends inside a day. The external source reports whole days.", "",
            "| Pool | Date | Our swaps | Our USD | External USD | Rel diff |", "|---|---|---|---|---|---|"]  # fmt: skip
    for r in result.both:
        if r["partial_day"]:
            out.append(f"| {labels.get(r['pool_address'], '')} | {r['date']} | {r['our_swaps']:,} | "
                       f"{_usd(r['our_volume_usd'])} | {_usd(r['external_volume_usd'])} | {_pct(r['rel_diff'])} |")  # fmt: skip
    window = client.query(
        f"SELECT toString(min(block_timestamp)), toString(max(block_timestamp)) FROM {ch.qualified(database)}"  # noqa: E501
    ).result_rows[0]
    out += ["", f"Our first swap: {window[0]} UTC. Our last swap: {window[1]} UTC."]

    out += ["", "## 5. Zero-leg swaps and filters", "",
            "This pipeline filters nothing: every Swap log of the pools is kept and counted. "
            "Whether the external source filters any trades is not documented "
            "(docs/EXTERNAL_SOURCE.md).", "",
            "| Pool | Swaps | With one zero leg | With both legs zero | USD volume of the zero-leg swaps |",  # noqa: E501
            "|---|---|---|---|---|"]  # fmt: skip
    for r in _rows(client, database, "12_evidence_zero_leg.sql", parameters):
        out.append(f"| {labels[r['pool_address']]} | {r['swaps']:,} | {r['zero_leg_swaps']} | "
                   f"{r['both_zero_swaps']} | {r['zero_leg_volume_usd']:,.6f} |")  # fmt: skip
    one_sided = result.one_sided
    out += ["", f"Pool-days present on one side only: {len(one_sided)}."]
    out += [
        f"- {labels.get(r['pool_address'], '')} {r['date']}: {r['presence']}" for r in one_sided
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.reconcile")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="relative difference beyond which a pool-day of B is listed (0.01 = 1%%)",
    )  # noqa: E501
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    parser.add_argument("--out", type=Path, default=REPORTS)
    parser.add_argument(
        "--evidence", action="store_true", help="also write reconciliation_evidence.md"
    )  # noqa: E501
    parser.add_argument("--fail-on-external", action="store_true",
                        help="also exit non-zero when B has pool-days beyond the threshold")  # fmt: skip
    args = parser.parse_args(argv)
    database = args.database or config.load_clickhouse_config().database
    client = ch.connect(database=database)
    result = run(client, database, args.threshold)

    write_csv(result, args.out / "reconciliation.csv")
    (args.out / "reconciliation.md").write_text(render(result, database), encoding="utf-8")
    if args.evidence:
        (args.out / "reconciliation_evidence.md").write_text(
            render_evidence(client, database, result), encoding="utf-8")  # fmt: skip

    print(
        f"A internal : {'exact, 0 differences' if result.internal_ok else f'FAILED: {len(result.internal)} pool-day(s) differ'}"
    )  # noqa: E501
    print(f"B external : {len(result.both)} pool-days on both sides, {len(result.over_threshold)} beyond "
          f"{100 * args.threshold:g}%, {len(result.one_sided)} on one side only")  # fmt: skip
    print(f"reports    : {args.out}")
    if not result.internal_ok:
        return 1
    if args.fail_on_external and (result.over_threshold or result.one_sided):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
