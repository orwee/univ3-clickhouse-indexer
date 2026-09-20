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
DEFAULT_THRESHOLD = 0.01  # relative: |ours - external| / external
DEFAULT_ABS_THRESHOLD = 1000.0  # USD: a pool-day is flagged only beyond BOTH thresholds
PARTIAL = "partial on our side (first or last day of our window)"
OPEN_CANDLE = "external candle still open when it was downloaded"
SINGLE_SWAP_TOLERANCE = 0.05
MIDNIGHT_MINUTES = 10
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
    abs_threshold: float = DEFAULT_ABS_THRESHOLD
    complete_days_only: bool = True

    @property
    def both(self) -> list[dict]:
        return [r for r in self.external if r["presence"] == "both"]

    def exclusion(self, row: dict) -> list[str]:
        """Why a pool-day present on both sides is not compared. Empty: it is compared."""
        if not self.complete_days_only:
            return []
        reasons = [PARTIAL] if row["partial_day"] else []
        fetched = row.get("external_fetched_at")
        if fetched is not None:
            if fetched.tzinfo is not None:
                fetched = fetched.astimezone(datetime.UTC)
            if row["date"] >= fetched.date():  # the candle of the day of the download, or later
                reasons.append(OPEN_CANDLE)
        return reasons

    @property
    def compared(self) -> list[dict]:
        return [r for r in self.both if not self.exclusion(r)]

    @property
    def excluded(self) -> list[dict]:
        return [r for r in self.both if self.exclusion(r)]

    @property
    def over_relative(self) -> list[dict]:
        return [
            r
            for r in self.compared
            if r["rel_diff"] is not None and abs(r["rel_diff"]) > self.threshold
        ]

    @property
    def over_threshold(self) -> list[dict]:
        """Flagged: beyond the relative threshold AND beyond the absolute one."""
        return [r for r in self.over_relative if abs(r["abs_diff_usd"]) > self.abs_threshold]

    @property
    def below_absolute(self) -> list[dict]:
        """Beyond the relative threshold only: listed apart, not flagged."""
        return [r for r in self.over_relative if abs(r["abs_diff_usd"]) <= self.abs_threshold]

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
    abs_threshold: float = DEFAULT_ABS_THRESHOLD,
    complete_days_only: bool = True,
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
        abs_threshold=abs_threshold,
        complete_days_only=complete_days_only,
    )


# --- reports ------------------------------------------------------------------------------

CSV_COLUMNS = ["pool", "pool_address", "date", "presence", "partial_day", "our_swaps",
               "our_volume_usd", "external_volume_usd", "abs_diff_usd", "rel_diff",
               "over_threshold", "over_relative_only", "excluded_reason"]  # fmt: skip


def write_csv(result: Result, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        flagged = {id(r) for r in result.over_threshold}
        relative_only = {id(r) for r in result.below_absolute}
        for r in result.external:
            over = id(r) in flagged
            reasons = result.exclusion(r) if r["presence"] == "both" else []
            writer.writerow([
                result.labels.get(r["pool_address"], ""), r["pool_address"], r["date"], r["presence"],
                int(r["partial_day"]), r["our_swaps"], r["our_volume_usd"], r["external_volume_usd"],
                r["abs_diff_usd"], "" if r["rel_diff"] is None else r["rel_diff"], int(over),
                int(id(r) in relative_only), "; ".join(reasons),
            ])  # fmt: skip


def _pct(value: float | None) -> str:
    return "" if value is None else f"{100 * value:+.2f}%"


def _usd(value: float) -> str:
    return f"{value:,.0f}"


def per_pool_summary(result: Result, compared_only: bool) -> list[dict]:
    summary = []
    source = result.compared if compared_only else result.both
    flagged = {id(r) for r in result.over_threshold}
    for address, label in result.labels.items():
        rows = [r for r in source if r["pool_address"] == address]
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
            "days_flagged": sum(1 for r in rows if id(r) in flagged),
        })  # fmt: skip
    return summary


def _rules(result: Result) -> str:
    days = (
        "only days complete on our side whose external candle was closed when downloaded"
        if result.complete_days_only
        else "every day present on both sides, incomplete ones included (`--include-incomplete-days`)"
    )
    return (
        f"Compared: {days}. Flagged: beyond **{100 * result.threshold:g}%** (`--threshold`) AND "
        f"beyond **{result.abs_threshold:,.0f} USD** (`--abs-threshold`)."
    )


def _day_table(result: Result, rows: list[dict], with_reason: bool = False) -> list[str]:
    head = "| pool | date | our USD | external USD | abs diff USD | rel diff |"
    lines = [
        head + (" why |" if with_reason else ""),
        "|---|---|---|---|---|---|" + ("---|" if with_reason else ""),
    ]
    for r in rows:
        line = (
            f"| {result.labels.get(r['pool_address'], '')} | {r['date']} | "
            f"{_usd(r['our_volume_usd'])} | {_usd(r['external_volume_usd'])} | "
            f"{_usd(r['abs_diff_usd'])} | {_pct(r['rel_diff'])} |"
        )
        lines.append(line + (f" {'; '.join(result.exclusion(r))} |" if with_reason else ""))
    return lines


def render(result: Result, database: str) -> str:
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Reconciliation report", "",
        f"Database `{database}`, generated {now} by `make reconcile`. {_rules(result)}", "",
        "## Summary", "",
        f"- **A, internal** (recomputation from `raw_swaps` vs `swaps_daily`, raw units): "
        f"**{'exact, 0 differences' if result.internal_ok else f'FAILED, {len(result.internal)} pool-day(s) differ'}**.",  # noqa: E501
        f"- **B, external** (our `volume_usd` vs {external.SOURCE}): {len(result.both)} pool-days "
        f"present on both sides, {len(result.compared)} compared, "
        f"**{len(result.over_threshold)} beyond both thresholds**, "
        f"{len(result.below_absolute)} beyond the relative threshold only, "
        f"{len(result.excluded)} excluded (listed below with the reason), "
        f"{len(result.one_sided)} present on one side only.",
        "- The exit code reflects A only. What the differences in B mean is not decided here.", "",
    ]  # fmt: skip
    for compared_only, title in (
        (True, "compared days"),
        (False, "every day present on both sides, for reference"),
    ):  # noqa: E501
        lines += [f"### B per pool, {title}", "",
                  "| Pool | Days | Ours USD | External USD | Total diff | Median daily diff | Largest daily diff (absolute) | Days beyond the relative threshold | Days beyond both |",  # noqa: E501
                  "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for s in per_pool_summary(result, compared_only):
            lines.append(
                f"| {s['pool']} | {s['days']} | {_usd(s['ours'])} | {_usd(s['external'])} | "
                f"{_pct(s['total_rel_diff'])} | {_pct(s['median_rel_diff'])} | "
                f"{100 * s['max_abs_rel_diff']:.2f}% | {s['days_over']} | "
                f"{s['days_flagged'] if compared_only else ''} |"
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
    by_size = lambda r: -abs(r["rel_diff"])  # noqa: E731
    lines += ["", f"## B: pool-days beyond {100 * result.threshold:g}% and "
              f"{result.abs_threshold:,.0f} USD", ""]  # fmt: skip
    lines += (
        _day_table(result, sorted(result.over_threshold, key=by_size))
        if result.over_threshold
        else ["None."]
    )
    lines += ["", f"## B: beyond {100 * result.threshold:g}%, but below the absolute threshold of "
              f"{result.abs_threshold:,.0f} USD", "",
              "Listed, not flagged.", ""]  # fmt: skip
    lines += (
        _day_table(result, sorted(result.below_absolute, key=by_size))
        if result.below_absolute
        else ["None."]
    )
    lines += ["", "## B: pool-days excluded from the comparison", "",
              "Present on both sides, shown with both values, and not compared.", ""]  # fmt: skip
    lines += _day_table(result, result.excluded, with_reason=True) if result.excluded else ["None."]
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
            "Compared days only (see the rules at the top of `reconciliation.md`).", "",
            "| Pool | Days | min | p25 | median | p75 | max |", "|---|---|---|---|---|---|---|"]  # fmt: skip
    full = [r for r in result.compared if r["rel_diff"] is not None]
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
    out += _evidence_pairs(result, pools)
    out += _evidence_source_effect(result)
    out += _evidence_single_swap(client, database, result, parameters)
    return "\n".join(out) + "\n"


def _evidence_pairs(result: Result, pools) -> list[str]:
    """Pools that trade the same two tokens, added up per day."""
    out = ["", "## 6. Pools of the same pair, added up", "",
           "For every compared day: ours and the external figure summed over the pools that trade "
           "the same two tokens. Listed: the days on which at least one pool of the pair is beyond "
           f"{100 * result.threshold:g}% while the sum is within it.", ""]  # fmt: skip
    groups: dict[tuple[str, str], list] = {}
    for pool in pools:
        groups.setdefault((pool.token0, pool.token1), []).append(pool)
    by_key = {(r["pool_address"], r["date"]): r for r in result.compared}
    for (token0, token1), members in groups.items():
        if len(members) < 2:
            continue
        keys = [str(m.key) for m in members]
        days = sorted({d for (a, d) in by_key if a in keys})
        days = [d for d in days if all((k, d) in by_key for k in keys)]
        out += [f"### {token0}/{token1}: " + " + ".join(m.label for m in members), "",
                f"Days with every pool of the pair compared: {len(days)}.", "",
                "| date | " + " | ".join(f"{m.label} rel diff" for m in members)
                + " | pair ours USD | pair external USD | pair abs diff USD | pair rel diff |",
                "|---|" + "---|" * (len(members) + 4)]  # fmt: skip
        pair_rel, listed = [], 0
        for day in days:
            rows = [by_key[(k, day)] for k in keys]
            ours = sum(r["our_volume_usd"] for r in rows)
            theirs = sum(r["external_volume_usd"] for r in rows)
            rel = (ours - theirs) / theirs if theirs else None
            if rel is None:
                continue
            pair_rel.append(rel)
            if (
                any(abs(r["rel_diff"]) > result.threshold for r in rows)
                and abs(rel) <= result.threshold
            ):
                listed += 1
                out.append(f"| {day} | " + " | ".join(_pct(r["rel_diff"]) for r in rows)
                           + f" | {_usd(ours)} | {_usd(theirs)} | {_usd(ours - theirs)} | {_pct(rel)} |")  # fmt: skip
        if not listed:
            out.append("| none | " + " | " * (len(members) + 4))
        over = sum(1 for x in pair_rel if abs(x) > result.threshold)
        out += ["", f"Pair-days beyond {100 * result.threshold:g}%: {over} of {len(pair_rel)}. "
                f"Pair daily rel diff: min, p25, median, p75, max = {_quantiles(pair_rel)}.", ""]  # fmt: skip
    return out


def _evidence_source_effect(result: Result) -> list[str]:
    """Days on which several pools move away from the source in the same direction."""
    labels = result.labels
    out = ["", "## 7. The same day across the pools", "",
           "Compared days. Volume vs median: our USD volume of the day, all pools, over the median "
           f"of that figure. Marked `<<`: three or more pools beyond {100 * result.threshold:g}% "
           "with the same sign.", "",
           "| date | weekday | volume vs median | " + " | ".join(labels.values()) + " | |",
           "|---|---|---|" + "---|" * (len(labels) + 1)]  # fmt: skip
    by_day: dict = {}
    for r in result.compared:
        by_day.setdefault(r["date"], {})[r["pool_address"]] = r
    totals = {d: sum(r["our_volume_usd"] for r in rows.values()) for d, rows in by_day.items()}
    median = statistics.median(totals.values()) if totals else 0
    marked = []
    for day in sorted(by_day):
        rels = [by_day[day][a]["rel_diff"] if a in by_day[day] else None for a in labels]
        up = sum(1 for x in rels if x is not None and x > result.threshold)
        down = sum(1 for x in rels if x is not None and x < -result.threshold)
        mark = "<<" if max(up, down) >= 3 else ""
        if mark:
            marked.append(str(day))
        ratio = f"{totals[day] / median:.2f}x" if median else ""
        out.append(
            f"| {day} | {day:%a} | {ratio} | " + " | ".join(_pct(x) for x in rels) + f" | {mark} |"
        )
    out += ["", f"Days marked: {', '.join(marked) if marked else 'none'}."]
    return out


def _evidence_single_swap(client, database: str, result: Result, parameters: dict) -> list[str]:
    """For each compared pool-day beyond the relative threshold: one swap about that size?"""
    out = ["", "## 8. One swap the size of the difference", "",
           f"For each compared pool-day beyond {100 * result.threshold:g}%: our swaps of that pool "
           f"whose USD value is within {100 * SINGLE_SWAP_TOLERANCE:g}% of the absolute difference, "
           f"looking at the UTC day plus {MIDNIGHT_MINUTES} minutes before its first midnight and "
           "after its last. The day's median tick and liquidity are given to compare each swap "
           "with; nothing is called anomalous here.", "",
           "| pool | date | rel diff | abs diff USD | swaps that size | of them, within "
           f"{MIDNIGHT_MINUTES} min of a midnight |", "|---|---|---|---|---|---|"]  # fmt: skip
    found = []
    for r in sorted(result.over_relative, key=lambda r: (r["pool_address"], r["date"])):
        rows = _rows(client, database, "13_evidence_single_swap.sql", {
            **{k: v for k, v in parameters.items() if k.startswith("stable_")},
            "pool": r["pool_address"], "day": r["date"], "target_usd": abs(r["abs_diff_usd"]),
            "tolerance": SINGLE_SWAP_TOLERANCE, "minutes": MIDNIGHT_MINUTES})  # fmt: skip
        near = [x for x in rows if x["where_in_day"]]
        out.append(f"| {result.labels.get(r['pool_address'], '')} | {r['date']} | {_pct(r['rel_diff'])} | "
                   f"{_usd(r['abs_diff_usd'])} | {len(rows)} | {len(near)} |")  # fmt: skip
        found += [(r, x) for x in rows]
    out += ["", "The swaps counted above:", "",
            "| pool | date | swap time (UTC) | swap USD | swap / abs diff - 1 | where in the day | "
            "tick | day median tick | liquidity | day median liquidity | swaps that day | "
            "swap / day USD |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r, x in found:
        share = f"{100 * x['swap_usd'] / x['day_usd']:.1f}%" if x["day_usd"] else ""
        out.append(f"| {result.labels.get(r['pool_address'], '')} | {r['date']} | {x['swap_time']} | "
                   f"{x['swap_usd']:,.2f} | {_pct(x['swap_over_target_minus_1'])} | "
                   f"{x['where_in_day']} | {x['swap_tick']} | {x['day_median_tick']} | "
                   f"{x['swap_liquidity']:.4g} | {x['day_median_liquidity']:.4g} | "
                   f"{x['day_swaps']:,} | {share} |")  # fmt: skip
    if not found:
        out.append("| none | | | | | | | | | | | |")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.reconcile")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="relative difference beyond which a pool-day of B is listed (0.01 = 1%%)",
    )  # noqa: E501
    parser.add_argument(
        "--abs-threshold",
        type=float,
        default=DEFAULT_ABS_THRESHOLD,
        help="USD difference a pool-day must ALSO exceed to be flagged; those beyond the "
        "relative threshold only are listed apart",
    )
    parser.add_argument(
        "--include-incomplete-days",
        action="store_true",
        help="also compare days partial on our side and external candles that were still open "
        "when downloaded (default: list them apart with the reason)",
    )
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
    result = run(
        client,
        database,
        args.threshold,
        abs_threshold=args.abs_threshold,
        complete_days_only=not args.include_incomplete_days,
    )

    write_csv(result, args.out / "reconciliation.csv")
    (args.out / "reconciliation.md").write_text(render(result, database), encoding="utf-8")
    if args.evidence:
        (args.out / "reconciliation_evidence.md").write_text(
            render_evidence(client, database, result), encoding="utf-8")  # fmt: skip

    print(
        f"A internal : {'exact, 0 differences' if result.internal_ok else f'FAILED: {len(result.internal)} pool-day(s) differ'}"
    )  # noqa: E501
    print(f"B external : {len(result.both)} pool-days on both sides, {len(result.compared)} compared, "
          f"{len(result.over_threshold)} beyond {100 * args.threshold:g}% and "
          f"{args.abs_threshold:,.0f} USD, {len(result.below_absolute)} beyond {100 * args.threshold:g}% only, "
          f"{len(result.excluded)} excluded, {len(result.one_sided)} on one side only")  # fmt: skip
    print(f"reports    : {args.out}")
    if not result.internal_ok:
        return 1
    if args.fail_on_external and (result.over_threshold or result.one_sided):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
