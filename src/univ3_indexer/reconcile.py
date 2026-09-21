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
import re
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
DISPLACEMENT_TICKS = 100  # "displaced" = more than this many ticks from the reference (1%)
DISPLACEMENT_SENSITIVITY = [25, 50, 100, 200, 500, 1000]
MIDNIGHT_MINUTES = 10
SHIFTS = range(-12, 13)
AUTHORSHIP = (
    "Drafted with AI assistance from the measurements in this repo and checked by an "
    "independent review pass. Design decisions were proposed with AI assistance, tested by "
    "measurement and approved by Roberto."
)
FINDINGS = config.REPO_ROOT / "docs" / "RECONCILIATION_FINDINGS.md"


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


def draft_findings() -> list[str]:
    """The findings are written once, in docs/RECONCILIATION_FINDINGS.md. Here only their
    titles and states, so that the two cannot drift apart. The rest of this report stays
    numbers only."""
    titles = re.findall(r"^### (\d+\. .+)$", FINDINGS.read_text(encoding="utf-8"), re.MULTILINE)
    return [f"**{AUTHORSHIP}**", "",
            "The text, with each figure and the section of this report behind it, is "
            "`docs/RECONCILIATION_FINDINGS.md`. Titles and states only:", "",
            *[f"- {t}" for t in titles]]  # fmt: skip


def render_evidence(client, database: str, result: Result, pools=None) -> str:
    pools = pools if pools is not None else load_pools()
    parameters = {**stable_leg_parameters(pools, stablecoin_symbols()), "source": external.SOURCE}
    days = sorted({r["date"] for r in result.both})
    first_full, last_full = days[1], days[-2]
    labels = result.labels
    out = [
        "# Reconciliation evidence", "",
        "Numbers only, from section 1 on: what was measured, not why, and not what is "
        "acceptable. The one exception is the list right below, which interprets and says so.", "",
        "## Findings", "", *draft_findings(), "",
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
    by_key = displaced_by_pool_day(client, database, parameters)
    out += _evidence_displaced(client, database, result, by_key)
    out += _evidence_round_trips(client, database, result, parameters)
    hourly = _hourly_by_pool_day(client, database, result, parameters)
    out += _evidence_hourly(result, hourly)
    out += _evidence_source_has_more(result, pools, by_key, hourly)
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


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx or not syy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sxx * syy) ** 0.5


def displaced_by_pool_day(client, database: str, parameters: dict) -> dict:
    stable = {k: v for k, v in parameters.items() if k.startswith("stable_")}
    rows = _rows(client, database, "14_evidence_displaced_swaps.sql",
                 {**stable, "thresholds": DISPLACEMENT_SENSITIVITY})  # fmt: skip
    return {(r["pool_address"], r["day"]): r for r in rows}


def what_if(result: Result, adjusted: dict) -> dict:
    """Both directions, so that the test can fail: how many compared pool-days beyond the
    relative threshold come inside it with `adjusted` in place of our volume, and how many
    that are inside today would leave it."""
    out = {"fixed_positive": 0, "fixed_negative": 0, "broken": 0, "positive": 0, "negative": 0,
           "inside": 0}  # fmt: skip
    for r in result.compared:
        key = (r["pool_address"], r["date"])
        if key not in adjusted or not r["external_volume_usd"]:
            continue
        new_rel = (adjusted[key] - r["external_volume_usd"]) / r["external_volume_usd"]
        if abs(r["rel_diff"]) > result.threshold:
            sign = "positive" if r["rel_diff"] > 0 else "negative"
            out[sign] += 1
            out[f"fixed_{sign}"] += abs(new_rel) <= result.threshold
        else:
            out["inside"] += 1
            out["broken"] += abs(new_rel) > result.threshold
    return out


def _evidence_displaced(client, database: str, result: Result, by_key: dict) -> list[str]:
    labels = result.labels
    index = DISPLACEMENT_SENSITIVITY.index(DISPLACEMENT_TICKS)
    out = ["", "## 9. Swaps executed away from the pool's own recent price", "",
           "Two readings of the same suspicion are put to the test, neither taken as true: (H1) "
           "the external source leaves such swaps out and this pipeline counts every log; (H2) "
           "the source counts them but values them at a going price, while this pipeline values "
           "every swap by its stablecoin leg.", "",
           "**Definition.** Reference tick = median tick of the pool over the 21 consecutive "
           "swaps centred on the swap. Displacement = the larger of |tick before the swap - "
           "reference| and |tick after it - reference|. A swap is *displaced* beyond N when its "
           f"displacement is more than N ticks (1 tick = 0.01% in price). N = {DISPLACEMENT_TICKS} "
           "here, and the table says why.", "",
           "| Pool | Swaps | p50 | p90 | p99 | p99.9 | p99.99 | max | "
           + " | ".join(f">{n}" for n in DISPLACEMENT_SENSITIVITY) + " |",
           "|---|---|---|---|---|---|---|---|" + "---|" * len(DISPLACEMENT_SENSITIVITY)]  # fmt: skip
    for r in _rows(client, database, "15_evidence_displacement_distribution.sql",
                   {"thresholds": DISPLACEMENT_SENSITIVITY}):  # fmt: skip
        out.append(f"| {labels.get(r['pool_address'], r['pool_address'])} | {r['swaps']:,} | "
                   + " | ".join(f"{q:,}" for q in r["quantiles"]) + f" | {r['largest']:,} | "
                   + " | ".join(f"{n:,}" for n in r["beyond"]) + " |")  # fmt: skip
    out += ["", f"Why {DISPLACEMENT_TICKS}: the deepest pool trades the same asset at the same "
            "time as its sibling and hardly ever goes beyond it, so beyond it a swap is about that "
            "pool's liquidity at that moment and not about the market. In the two quiet pools 21 "
            "swaps span hours, real price drift enters the displacement, and the definition "
            "separates less; their figures below are given with that caveat.", ""]  # fmt: skip

    compared = [r for r in result.compared if (r["pool_address"], r["date"]) in by_key]
    out += [f"### The {len(result.over_threshold)} flagged pool-days", "",
            f"Displaced = beyond {DISPLACEMENT_TICKS} ticks. *Without them* is H1; *valued at the "
            "reference* is H2 (every swap of the day, the non-stable leg at the reference tick).", "",
            "| pool | date | rel diff | abs diff USD | displaced swaps | displaced USD | "
            "rel diff without them (H1) | rel diff valued at the reference (H2) |",
            "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in sorted(result.over_threshold, key=lambda r: (r["pool_address"], r["date"])):
        d = by_key.get((r["pool_address"], r["date"]))
        if d is None:
            continue
        ext = r["external_volume_usd"]
        h1 = (d["volume_usd"] - d["displaced_usd"][index] - ext) / ext
        h2 = (d["volume_usd_at_reference"] - ext) / ext
        out.append(f"| {labels.get(r['pool_address'], '')} | {r['date']} | {_pct(r['rel_diff'])} | "
                   f"{_usd(r['abs_diff_usd'])} | {d['displaced_swaps'][index]} | "
                   f"{_usd(d['displaced_usd'][index])} | {_pct(h1)} | {_pct(h2)} |")  # fmt: skip

    diffs = [r["abs_diff_usd"] for r in compared]
    displaced = [by_key[(r["pool_address"], r["date"])]["displaced_usd"][index] for r in compared]
    revalued = [by_key[(r["pool_address"], r["date"])]["volume_usd"]
                - by_key[(r["pool_address"], r["date"])]["volume_usd_at_reference"] for r in compared]  # fmt: skip
    fmt = lambda v: "n/a" if v is None else f"{v:+.3f}"  # noqa: E731
    out += ["", f"### All {len(compared)} compared pool-days", "",
            "Pearson correlation of the daily difference (ours - external, USD) with:", "",
            f"- the USD of displaced swaps (H1): {fmt(_pearson(diffs, displaced))}",
            f"- ours minus ours valued at the reference (H2): {fmt(_pearson(diffs, revalued))}", "",
            "Per pool (the two liquid pools dominate any correlation in USD):", "",
            "| Pool | Pool-days | r with displaced USD (H1) | r with the revaluation (H2) |",
            "|---|---|---|---|"]  # fmt: skip
    for address, label in labels.items():
        rows = [i for i, r in enumerate(compared) if r["pool_address"] == address]
        out.append(f"| {label} | {len(rows)} | {fmt(_pearson([diffs[i] for i in rows], [displaced[i] for i in rows]))} | "
                   f"{fmt(_pearson([diffs[i] for i in rows], [revalued[i] for i in rows]))} |")  # fmt: skip

    out += ["", "### Would it make the days reconcile? Both directions", "",
            f"Pool-days beyond {100 * result.threshold:g}% today that come inside it, and pool-days "
            "inside it today that would leave it. A hypothesis that fixes days by breaking as "
            "many explains nothing.", "",
            "| Adjustment | Positive days beyond, fixed | Negative days beyond, fixed | "
            "Days inside today, broken |", "|---|---|---|---|"]  # fmt: skip
    for i, n in enumerate(DISPLACEMENT_SENSITIVITY):
        w = what_if(result, {k: d["volume_usd"] - d["displaced_usd"][i] for k, d in by_key.items()})
        out.append(f"| H1: leave out swaps displaced beyond {n} ticks | {w['fixed_positive']} of "
                   f"{w['positive']} | {w['fixed_negative']} of {w['negative']} | {w['broken']} of {w['inside']} |")  # fmt: skip
    w = what_if(result, {k: d["volume_usd_at_reference"] for k, d in by_key.items()})
    out.append(f"| H2: value every swap at the reference tick | {w['fixed_positive']} of {w['positive']} | "
               f"{w['fixed_negative']} of {w['negative']} | {w['broken']} of {w['inside']} |")  # fmt: skip
    return out


def _evidence_round_trips(client, database: str, result: Result, parameters: dict) -> list[str]:
    stable = {k: v for k, v in parameters.items() if k.startswith("stable_")}
    out = ["", "## 10. Round trips inside one block", "",
           "For each flagged pool-day: pairs of swaps of the same pool, in the same block, by the "
           "same sender, in opposite directions, the second undoing at least 90% of the first. "
           "Up to 10 per pool-day, largest first. Addresses and block numbers are public chain "
           "data.", "",
           "| pool | date | time (UTC) | block | log indexes | same tx | sender | sender = recipient | "
           "first USD | second USD | net stable paid to pool | tick before > between > after | "
           "liquidity before > between > after | swaps of others between |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    totals = []
    for r in sorted(result.over_threshold, key=lambda r: (r["pool_address"], r["date"])):
        pairs = _rows(client, database, "16_evidence_round_trips.sql",
                      {**stable, "pool": r["pool_address"], "day": r["date"]})  # fmt: skip
        totals.append((r, len(pairs), sum(p["first_usd"] + p["second_usd"] for p in pairs)))
        for p in pairs[:4]:
            out.append(
                f"| {result.labels.get(r['pool_address'], '')} | {r['date']} | {p['block_time'][11:]} | "
                f"{p['block_number']} | {p['first_log_index']}, {p['second_log_index']} | "
                f"{'yes' if p['same_transaction'] else 'no'} | {p['sender_address'][:10]}… | "
                f"{'yes' if p['sender_is_recipient'] else 'no'} | {p['first_usd']:,.0f} | "
                f"{p['second_usd']:,.0f} | {p['net_stable_paid_to_pool']:+,.0f} | "
                f"{p['first_tick_before']} > {p['first_tick_after']} > {p['second_tick_after']} | "
                f"{p['liquidity_before']:.3g} > {p['liquidity_between']:.3g} > {p['liquidity_after']:.3g} | "
                f"{p['swaps_of_others_between']} |")  # fmt: skip
    out += ["", "| pool | date | abs diff USD | round trips found (max 10) | their USD, both legs |",
            "|---|---|---|---|---|"]  # fmt: skip
    out += [f"| {result.labels.get(r['pool_address'], '')} | {r['date']} | {_usd(r['abs_diff_usd'])} | "
            f"{n} | {_usd(usd)} |" for r, n, usd in totals]  # fmt: skip
    return out


def _hourly_by_pool_day(client, database: str, result: Result, parameters: dict) -> dict | None:
    """Hour-by-hour rows of each flagged pool-day; None when the hourly table is not there."""
    exists = client.command(
        "SELECT count() FROM system.tables WHERE database = {db:String} AND name = {t:String}",
        parameters={"db": database, "t": external.HOURLY_TABLE},
    )
    if not exists:
        return None
    stable = {k: v for k, v in parameters.items() if k.startswith("stable_")}
    return {
        (r["pool_address"], r["date"]): _rows(
            client, database, "17_evidence_hourly.sql",
            {**stable, "pool": r["pool_address"], "day": r["date"], "source": external.SOURCE},
        )
        for r in result.over_threshold
    }  # fmt: skip


def _evidence_hourly(result: Result, hourly: dict | None) -> list[str]:
    out = ["", "## 11. The flagged pool-days, hour by hour", "",
           "Ours against the external HOURLY candles (`make fetch-external-hourly`; the source "
           "serves the last 1,000 hours). For each flagged pool-day: how the day's difference is "
           "spread over its hours. Hours the source omits count as 0 on its side.", ""]  # fmt: skip
    if hourly is None:
        return out + ["The hourly table does not exist in this database: section skipped."]
    out += ["| pool | date | day diff USD (daily candle) | sum of hourly diffs | hours beyond 1% | "
            "largest three hourly diffs (hour: USD) | share of the day diff in those three |",
            "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in sorted(result.over_threshold, key=lambda r: (r["pool_address"], r["date"])):
        hours = hourly[(r["pool_address"], r["date"])]
        label = result.labels.get(r["pool_address"], "")
        if not any(h["external_usd"] for h in hours):
            out.append(
                f"| {label} | {r['date']} | {_usd(r['abs_diff_usd'])} | no hourly candles | | | |"
            )
            continue
        total = sum(h["diff_usd"] for h in hours)
        beyond = sum(1 for h in hours if h["external_usd"]
                     and abs(h["diff_usd"]) / h["external_usd"] > result.threshold)  # fmt: skip
        top = sorted(hours, key=lambda h: -abs(h["diff_usd"]))[:3]
        share = sum(h["diff_usd"] for h in top) / total if total else None
        out.append(f"| {label} | {r['date']} | {_usd(r['abs_diff_usd'])} | {_usd(total)} | "
                   f"{beyond} of {len(hours)} | "
                   + ", ".join(f"{h['hour_of_day']:02d}h: {h['diff_usd']:+,.0f}" for h in top)
                   + f" | {_pct(share) if share is not None else ''} |")  # fmt: skip
    return out


def _evidence_source_has_more(
    result: Result, pools, by_key: dict, hourly: dict | None
) -> list[str]:
    """The flagged days on which the source reports MORE than the chain: leaving swaps out can
    only lower our figure, so H1 cannot account for them whatever the threshold."""
    index = DISPLACEMENT_SENSITIVITY.index(DISPLACEMENT_TICKS)
    siblings: dict[str, list[str]] = {}
    for pool in pools:
        same = [str(q.key) for q in pools if (q.token0, q.token1) == (pool.token0, pool.token1)]
        siblings[str(pool.key)] = [k for k in same if k != str(pool.key)]
    rel = {(r["pool_address"], r["date"]): r["rel_diff"] for r in result.compared}
    out = ["", "## 12. Flagged days on which the source has MORE than the chain", "",
           "Leaving swaps out (H1) can only lower our figure, so it cannot account for these. What "
           "can be measured is put side by side; whatever a row does not account for stays "
           "unexplained.", "",
           "| pool | date | rel diff | abs diff USD | displaced swaps | displaced USD | rel diff "
           "valued at the reference (H2) | largest hourly diff | sibling pool, same day |",
           "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    rows = [r for r in result.over_threshold if r["abs_diff_usd"] < 0]
    for r in sorted(rows, key=lambda r: (r["pool_address"], r["date"])):
        key = (r["pool_address"], r["date"])
        d = by_key.get(key)
        h2 = (
            _pct(
                (d["volume_usd_at_reference"] - r["external_volume_usd"]) / r["external_volume_usd"]
            )
            if d
            else ""
        )
        hour = ""
        if hourly and any(h["external_usd"] for h in hourly.get(key, [])):
            top = max(hourly[key], key=lambda h: abs(h["diff_usd"]))
            hour = f"{top['hour_of_day']:02d}h: {top['diff_usd']:+,.0f}"
        sibling = ", ".join(_pct(rel[(s, r["date"])]) for s in siblings[r["pool_address"]]
                            if (s, r["date"]) in rel)  # fmt: skip
        out.append(f"| {result.labels.get(r['pool_address'], '')} | {r['date']} | {_pct(r['rel_diff'])} | "
                   f"{_usd(r['abs_diff_usd'])} | {d['displaced_swaps'][index] if d else ''} | "
                   f"{_usd(d['displaced_usd'][index]) if d else ''} | {h2} | {hour} | {sibling} |")  # fmt: skip
    if not rows:
        out.append("| none | | | | | | | | |")
    return out


if __name__ == "__main__":
    sys.exit(main())
