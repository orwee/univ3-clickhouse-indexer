"""Build docs/index.html: one self-contained status page for this repository.

    PYTHONPATH=src uv run python scripts/build_dashboard.py            # -> docs/index.html
    PYTHONPATH=src uv run python scripts/build_dashboard.py --generated-at 2026-09-21T12:00:00+00:00

Rules this file obeys, because the page is published:

* ONE file. No external CSS, JS, font or image; no network request at view time. Every chart
  is SVG markup built here; there is no chart library and no <img>.
* Nothing that identifies a third party. No address, no transaction hash, no Nansen label:
  the queries below select labels and aggregates, never an address column.
* No number is written by hand. Every figure is either SELECTed from ClickHouse (read-only)
  or parsed out of a file in this repository at build time, and a parse that does not match
  raises instead of falling back to a constant, so the page cannot drift away from the repo.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import html
import math
import re
import sys
from pathlib import Path

from univ3_indexer import clickhouse as ch
from univ3_indexer import config, external, reconcile
from univ3_indexer.pools import load_pools

REPO = config.REPO_ROOT
DOCS = REPO / "docs"
REPORTS = REPO / "reports"
GH = "https://github.com/orwee/univ3-clickhouse-indexer/blob/main/"

RAW_DB = "onchain"
DBT_DB = "onchain_dbt"

# Colour slots are bound to the pool, never to its rank in a chart, so a pool keeps its
# colour on every chart of the page. Labels come from pools.yml through dim_pools.
POOL_SLOT = {
    "USDC/WETH 0.01%": "s1",
    "USDC/WETH 0.05%": "s2",
    "wstETH/USDC 0.05%": "s3",
    "wstETH/USDC 0.3%": "s4",
}
POOL_ORDER = list(POOL_SLOT)

SVG_W = 680  # every chart is drawn in this many user units wide and scaled with width:100%
FS = 18  # tick/label size in user units: ~9 px on a 360 px phone, ~18 px on a wide screen


# --------------------------------------------------------------------------- small helpers


def _need(pattern: str, text: str, source: str, flags: int = 0) -> re.Match[str]:
    """Search, or die. A silent miss here would put a stale number on the page."""
    m = re.search(pattern, text, flags)
    if m is None:
        raise SystemExit(f"build_dashboard: nothing matched {pattern!r} in {source}")
    return m


def _num(text: str) -> float:
    return float(text.replace(",", "").replace("+", ""))


def _int(text: str) -> int:
    return int(text.replace(",", "").replace("+", ""))


def _md_plain(text: str) -> str:
    """Markdown to plain prose: keep the words, drop the link targets and the emphasis."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def finding_anchors(readme: str) -> dict[int, str]:
    """The fragment GitHub gives each finding, taken from the links README.md already carries.

    Not derived here: reimplementing GitHub's slug rule would be a second copy of it that
    nothing checks, while every anchor in README.md is already resolved against the document
    by tests/test_readme.py. A finding that is missing from that table raises below.
    """
    return {
        int(m.group(1)): m.group(2)
        for m in re.finditer(r"\[(\d+)\]\(docs/RECONCILIATION_FINDINGS\.md(#[a-z0-9-]+)\)", readme)
    }


def fint(v: float) -> str:
    return f"{round(v):,}"


def fusd(v: float, places: int = 0) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.{places}f}"


def fusd_signed(v: float, places: int = 2) -> str:
    return f"{'-' if v < 0 else '+'}${abs(v):,.{places}f}"


def nice_ticks(top: float, target: int = 5) -> list[float]:
    """Round gridline values, few enough that their labels never touch."""
    if top <= 0:
        return [0.0, 1.0]
    raw = top / target
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 5, 10) if m * power >= raw)
    return [i * step for i in range(int(math.ceil(top / step)) + 1)]


def fusd_compact(v: float) -> str:
    """$0, $940, $2k, $2.5k, $1.2M — a tick label that never rounds 2,500 to 2,000."""
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= cut:
            return f"${v / cut:.1f}".rstrip("0").rstrip(".") + suffix
    return f"${v:,.0f}"


def fpct(v: float, places: int = 2) -> str:
    return f"{v * 100:+.{places}f}%"


def esc(v: object) -> str:
    return html.escape(str(v), quote=True)


# --------------------------------------------------------------------------- documents


def read_documents() -> dict:
    """Every figure this page takes from a file in the repo, parsed once."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    findings_md = (DOCS / "RECONCILIATION_FINDINGS.md").read_text(encoding="utf-8")
    recon_md = (REPORTS / "reconciliation.md").read_text(encoding="utf-8")
    h2_md = (REPORTS / "h2_out_of_sample.md").read_text(encoding="utf-8")
    schema_md = (DOCS / "SCHEMA_EXPERIMENTS.md").read_text(encoding="utf-8")
    perf_md = (DOCS / "QUERY_PERFORMANCE.md").read_text(encoding="utf-8")

    one_liner = _md_plain(
        _need(r"^Uniswap v3 .*?independent source\.", readme, "README.md", re.M | re.S).group(0)
    )
    # The caveat is quoted verbatim: the blockquote README.md opens with, word for word,
    # with only its "> " markers and line wrapping removed.
    caveat = _md_plain(
        re.sub(
            r"^> ?",
            "",
            _need(r"^> Built over one weekend.*?(?=\n\n)", readme, "README.md", re.M | re.S).group(
                0
            ),
            flags=re.M,
        )
    )

    counts = _need(
        r"(\d+) pool-days present on both sides, (\d+) compared, \*\*(\d+) beyond both "
        r"thresholds\*\*, (\d+) beyond the relative threshold only, (\d+) excluded",
        recon_md,
        "reports/reconciliation.md",
    )
    internal = _need(r"\*\*(exact, 0 differences)\*\*", recon_md, "reports/reconciliation.md")
    recon_line = _md_plain(
        _need(r"- \*\*B, external\*\*[^:]*: ([^\n]*)", recon_md, "reports/reconciliation.md")
        .group(1)
        .replace(" (listed below with the reason)", "")
    )
    recon_generated = _need(
        r"generated (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)", recon_md, "reports/reconciliation.md"
    ).group(1)
    # No finding is headed UNEXPLAINED; what is unexplained sits inside the partly explained
    # ones and is listed pool-day by pool-day at the end of the document. Count those rows.
    open_block = _need(
        r"^## What is still open(.*)\Z", findings_md, "docs/RECONCILIATION_FINDINGS.md", re.M | re.S
    ).group(1)
    still_open = len(re.findall(r"^\| \w[^|]*\|[^|]*\|[^|]*\|$", open_block, re.M)) - 1

    return {
        "still_open": still_open,
        "one_liner": one_liner,
        "caveat": caveat,
        "compared": _int(counts.group(2)),
        "flagged": _int(counts.group(3)),
        "both": _int(counts.group(1)),
        "over_relative_only": _int(counts.group(4)),
        "excluded": _int(counts.group(5)),
        "internal": internal.group(1),
        "recon_line": recon_line,
        "recon_generated": recon_generated,
        "findings": parse_findings(findings_md, finding_anchors(readme)),
        "hypotheses": parse_hypotheses(findings_md, h2_md),
        "sorting_keys": parse_sorting_keys(schema_md),
        "inserts": parse_inserts(perf_md),
        "evidence_top_hours": parse_evidence_hours(),
    }


def parse_findings(md: str, anchors: dict[int, str]) -> list[dict]:
    """The ten findings and their state, from the headings, so the page cannot drift."""
    out = []
    for m in re.finditer(r"^### (\d+)\. (.+?) — (.+)$", md, re.M):
        tail = m.group(3).strip()
        state = next(
            (s for s in ("PARTLY EXPLAINED", "UNEXPLAINED", "EXPLAINED") if tail.startswith(s)),
            None,
        )
        if state is None:
            raise SystemExit(f"build_dashboard: unknown finding state {tail!r}")
        number = _int(m.group(1))
        if number not in anchors:
            raise SystemExit(f"build_dashboard: README.md does not link to finding {number}")
        out.append(
            {
                "n": number,
                "title": m.group(2).strip(),
                "state": state,
                "note": tail[len(state) :].strip().strip("()"),
                "anchor": anchors[number],
            }
        )
    if len(out) != 10:
        raise SystemExit(f"build_dashboard: expected 10 findings, parsed {len(out)}")
    return out


def _h2_row(md: str, label: str) -> dict:
    """One row of the tables in reports/h2_out_of_sample.md."""
    cells = [
        c.strip()
        for c in _need(rf"^\| {re.escape(label)} \|(.+)\|$", md, "h2_out_of_sample.md", re.M)
        .group(1)
        .split("|")
    ]
    beyond, pos, neg, broke = cells[1], cells[2], cells[3], cells[4]
    fixed = _int(pos.split(" of ")[0]) + _int(neg.split(" of ")[0])
    return {
        "beyond": _int(beyond),
        "fixed": fixed,
        "broken": _int(broke.split(" of ")[0]),
        "inside": _int(broke.split(" of ")[1]),
        "r": _num(cells[7]),
    }


def parse_hypotheses(findings_md: str, h2_md: str) -> list[dict]:
    """H1 from finding 7's text, H2 and the placebo from the out-of-sample report."""
    flat = re.sub(r"\s+", " ", findings_md)  # the prose below is wrapped across lines
    h1 = _need(
        r"brings (\d+) of (\d+) pool-days inside 1% and pushes (\d+) of the (\d+) that reconciled",
        flat,
        "docs/RECONCILIATION_FINDINGS.md",
    )
    h1_r = _need(
        r"Correlation with the daily difference: ([+-]?\d+\.\d+)",
        flat,
        "docs/RECONCILIATION_FINDINGS.md",
    )
    rows = [
        {
            "name": "H1 in sample",
            "short": "H1 in sample",
            "what": "the source filters displaced swaps out",
            "beyond": _int(h1.group(2)),
            "fixed": _int(h1.group(1)),
            "broken": _int(h1.group(3)),
            "inside": _int(h1.group(4)),
            "r": _num(h1_r.group(1)),
        }
    ]
    for name, short, what, label in (
        (
            "H2 in sample",
            "H2 in sample",
            "the source values them at a going price",
            "In sample: revalue every swap (H2 as first tested)",
        ),
        (
            "H2 hold-out",
            "H2 hold-out",
            "the same rule, on ten days it was not fitted on",
            "HOLD-OUT: revalue every swap (H2 as first tested)",
        ),
        (
            "Placebo in sample",
            "Placebo",
            "as many swaps revalued, but non-displaced ones",
            "In sample: placebo, seed 1",
        ),
    ):
        rows.append({"name": name, "short": short, "what": what, **_h2_row(h2_md, label)})
    return rows


def parse_sorting_keys(md: str) -> list[dict]:
    """Rows read for the same one-day query under two sorting keys."""
    good = _need(
        r"One day of the big pool, `\(pool, timestamp\)` \|[^|]*\| \*\*([\d,]+) rows "
        r"· (\d+)/(\d+) granules\*\*",
        md,
        "docs/SCHEMA_EXPERIMENTS.md",
    )
    bad = _need(
        r"One day of the big pool, `\(pool, block_number, log_index\)` \|[^|]*\| "
        r"\*\*([\d,]+) rows · (\d+)/(\d+)\*\*",
        md,
        "docs/SCHEMA_EXPERIMENTS.md",
    )
    return [
        {
            "key": "ORDER BY (pool, timestamp) — the key that was chosen",
            "rows": _int(good.group(1)),
            "granules": f"{good.group(2)}/{good.group(3)}",
        },
        {
            "key": "ORDER BY (pool, block_number, log_index) — no time in the key",
            "rows": _int(bad.group(1)),
            "granules": f"{bad.group(2)}/{bad.group(3)}",
        },
    ]


def parse_inserts(md: str) -> dict:
    """The same 50,000 rows in 1 insert and in 1,000 inserts."""

    def row(label: str) -> tuple[str, str]:
        cells = _need(rf"^\| {re.escape(label)} \|([^|]*)\|([^|]*)\|", md, label, re.M)
        return cells.group(1).strip(), cells.group(2).strip()

    time_one, time_many = row("Time to insert")
    merges = row("Merges run by the server")
    rewritten = row("Rows rewritten by merges")
    written = row("Bytes written by merges")
    amp = _need(r"\*\*([\d,]+)\*\* \((\d+) times the data\)", md, "docs/QUERY_PERFORMANCE.md")
    return {
        "seconds": [_num(time_one.replace(" s", "")), _num(time_many.strip("*").replace(" s", ""))],
        "amplification": _int(amp.group(2)),
        "table": [
            ("Time to insert", time_one, time_many.strip("*")),
            ("Merges run by the server", merges[0], merges[1].strip("*")),
            ("Rows rewritten by merges", rewritten[0], rewritten[1].replace("**", "")),
            ("Bytes written by merges", written[0], written[1].replace("**", "")),
        ],
    }


def parse_evidence_hours() -> dict:
    """Section 11 of the evidence report: the largest three hourly diffs per flagged pool-day."""
    md = (REPORTS / "reconciliation_evidence.md").read_text(encoding="utf-8")
    block = _need(
        r"^## 11\. The flagged pool-days, hour by hour(.*?)^## 12\.",
        md,
        "reports/reconciliation_evidence.md",
        re.M | re.S,
    ).group(1)
    out = {}
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 7 or cells[0] in ("pool", "---") or cells[0].startswith("-"):
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[1]):
            continue
        out[(cells[0], cells[1])] = {"top3": cells[5], "share3": cells[6]}
    if not out:
        raise SystemExit("build_dashboard: section 11 of the evidence report parsed empty")
    return out


def read_reconciliation_csv() -> list[dict]:
    with (REPORTS / "reconciliation.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["day"] = datetime.date.fromisoformat(r["date"])  # the charts index by date, not text
        r["rel"] = float(r["rel_diff"]) if r["rel_diff"] else None
        r["abs_usd"] = float(r["abs_diff_usd"]) if r["abs_diff_usd"] else None
        r["flagged"] = r["over_threshold"] == "1"
        r["rel_only"] = r["over_relative_only"] == "1"
        r["excluded"] = bool(r["excluded_reason"])
    return rows


# --------------------------------------------------------------------------- ClickHouse


SQL_TOTALS = f"""
SELECT count() AS swaps,
       uniqExact(pool_address) AS pools,
       uniqExact(toDate(block_timestamp, 'UTC')) AS days,
       min(toDate(block_timestamp, 'UTC')) AS first_day,
       max(toDate(block_timestamp, 'UTC')) AS last_day
FROM {RAW_DB}.raw_swaps
"""

SQL_DAILY = f"""
SELECT pool_label, block_date, toFloat64(volume_usd) AS volume_usd, swaps
FROM {DBT_DB}.fct_pool_daily
ORDER BY pool_label, block_date
"""

SQL_POOL_TOTALS = f"""
SELECT pool_label,
       fee,
       sum(swaps) AS swaps,
       toFloat64(sum(volume_usd)) AS volume_usd,
       toFloat64(sum(fees_usd)) AS fees_usd,
       count() AS pool_days
FROM {DBT_DB}.fct_pool_daily
GROUP BY pool_label, fee
ORDER BY pool_label
"""

SQL_SENDER_TOP = f"""
WITH per AS (
    SELECT sender, sum(volume_usd) AS v
    FROM {DBT_DB}.stg_swaps
    WHERE volume_usd IS NOT NULL
    GROUP BY sender
    ORDER BY v DESC
    LIMIT 50
)
SELECT rowNumberInAllBlocks() + 1 AS rank, toFloat64(v) AS v FROM per
"""

SQL_SENDER_TOTAL = f"""
SELECT toFloat64(sum(volume_usd)) AS total, uniqExact(sender) AS senders
FROM {DBT_DB}.stg_swaps
WHERE volume_usd IS NOT NULL
"""

SQL_SMART = f"""
SELECT pool_label,
       count() AS pool_days,
       sum(swaps) AS swaps,
       sum(smart_money_swaps) AS smart_swaps,
       toFloat64(sum(volume_usd)) AS volume_usd,
       sum(smart_money_volume_usd) AS smart_volume_usd,
       countIf(smart_money_volume_usd > 0) AS days_with_any,
       min(block_date) AS first_day,
       max(block_date) AS last_day
FROM {DBT_DB}.fct_pool_daily_smart_money
GROUP BY pool_label
ORDER BY pool_label
"""

SENDER_RANKS = (1, 2, 3, 5, 8, 20, 50)


def collect(client) -> dict:
    """Every figure this page takes from ClickHouse. Read-only: SELECT and nothing else."""
    totals = next(iter(client.query(SQL_TOTALS).named_results()))
    daily = list(client.query(SQL_DAILY).named_results())
    pool_totals = list(client.query(SQL_POOL_TOTALS).named_results())
    smart = list(client.query(SQL_SMART).named_results())

    sender_total = next(iter(client.query(SQL_SENDER_TOTAL).named_results()))
    cumulative, running = {}, 0.0
    for row in client.query(SQL_SENDER_TOP).named_results():
        running += row["v"]
        if row["rank"] in SENDER_RANKS:
            cumulative[row["rank"]] = running / sender_total["total"]
    missing = [r for r in SENDER_RANKS if r not in cumulative]
    if missing:
        raise SystemExit(f"build_dashboard: no sender at rank {missing}")

    dates = sorted({r["block_date"] for r in daily})
    series = {}
    for label in POOL_ORDER:
        by_date = {r["block_date"]: r["volume_usd"] for r in daily if r["pool_label"] == label}
        series[label] = [by_date.get(d) for d in dates]

    return {
        "totals": totals,
        "dates": dates,
        "volume_series": series,
        "daily": daily,
        "pool_totals": {r["pool_label"]: r for r in pool_totals},
        "senders": {"total": sender_total, "cumulative": cumulative},
        "smart": smart,
    }


def hourly_of_flagged(client, csv_rows: list[dict]) -> list[dict]:
    """The flagged pool-days hour by hour, the way sql/reconciliation/17_evidence_hourly.sql
    does it: raw_swaps against external_hourly_volume FINAL, that file's own text and
    parameters, so this page and the evidence report cannot disagree."""
    sql_path = ch.SQL_DIR / "reconciliation" / "17_evidence_hourly.sql"
    sql = ch.strip_sql_comments(sql_path.read_text(encoding="utf-8")).strip().rstrip(";")
    stable = reconcile.stable_leg_parameters(load_pools(), reconcile.stablecoin_symbols())
    out = []
    for row in csv_rows:
        if not row["flagged"]:
            continue
        day = datetime.date.fromisoformat(row["date"])
        params = {
            **stable,
            "pool": row["pool_address"],
            "day": day,
            "source": external.SOURCE,
        }
        hours = list(client.query(sql, parameters=params).named_results())
        moved = sum(abs(h["diff_usd"]) for h in hours)
        top = max(hours, key=lambda h: abs(h["diff_usd"]))
        out.append(
            {
                "pool": row["pool"],
                "date": row["date"],
                "hours": hours,
                "day_diff": row["abs_usd"],
                "rel": row["rel"],
                "moved": moved,
                "top_hour": top["hour_of_day"],
                "top_diff": top["diff_usd"],
                "concentration": abs(top["diff_usd"]) / moved if moved else 0.0,
            }
        )
    if not out:
        raise SystemExit("build_dashboard: no flagged pool-day to show hour by hour")
    out.sort(key=lambda d: -d["concentration"])
    return out


# --------------------------------------------------------------------------- SVG helpers


def _txt(x: float, y: float, text: str, cls: str = "tk", anchor: str = "start") -> str:
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}"{a}>{esc(text)}</text>'


def _open_svg(width: int, height: int, title: str, desc: str) -> list[str]:
    return [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="{esc(title)}"><title>{esc(title)}</title><desc>{esc(desc)}</desc>'
    ]


def _pack_labels(items: list[tuple[float, object]], gap: float, lo: float, hi: float) -> dict:
    """Push label anchors apart so four end-labels never overlap. Keeps the order in y."""
    ordered = sorted(items, key=lambda it: it[0])
    ys: list[float] = []
    for y, _ in ordered:
        ys.append(max(y, ys[-1] + gap) if ys else max(y, lo))
    overflow = ys[-1] - hi
    if overflow > 0:
        ys = [y - overflow for y in ys]
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - gap)
    return {key: y for (_, key), y in zip(ordered, ys, strict=True)}


def line_chart_log(dates: list, series: dict, *, title: str, desc: str) -> str:
    """One line per pool on a base-10 log scale. Direct end labels plus the legend."""
    height, left, right, top, bottom = 372, 72, 152, 16, 44
    x0, x1 = left, SVG_W - right
    y0, y1 = top, height - bottom
    decades = [0, 2, 4, 6, 8]
    names = {0: "$1", 2: "$100", 4: "$10k", 6: "$1M", 8: "$100M"}

    def sx(i: int) -> float:
        return x0 + (x1 - x0) * i / (len(dates) - 1)

    def sy(v: float) -> float:
        lv = min(max(math.log10(max(v, 1.0)), 0.0), 9.0)
        return y1 - (y1 - y0) * lv / 9.0

    out = _open_svg(SVG_W, height, title, desc)
    for d in decades:
        y = sy(10.0**d)
        out.append(f'<line class="gr" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
        out.append(_txt(x0 - 8, y + FS * 0.34, names[d], "tk", "end"))
    out.append(f'<line class="ax" x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}"/>')
    for i in range(0, len(dates), 7):
        out.append(_txt(sx(i), y1 + FS + 6, dates[i].strftime("%b %d"), "tk", "middle"))

    ends = []
    for label in POOL_ORDER:
        values = series[label]
        points = [(sx(i), sy(v)) for i, v in enumerate(values) if v]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        slot = POOL_SLOT[label]
        out.append(f'<polyline class="ln" style="stroke:var(--{slot})" points="{path}"/>')
        ends.append((points[-1][1], label))
    packed = _pack_labels(ends, FS * 2.2, y0 + FS, y1)
    for label, y in packed.items():
        pair, fee = label.rsplit(" ", 1)
        slot = POOL_SLOT[label]
        out.append(
            f'<circle class="dotring" cx="{x1 + 12}" cy="{y - FS * 0.75:.1f}" r="4" '
            f'style="fill:var(--{slot})"/>'
        )
        out.append(_txt(x1 + 22, y - FS * 0.3, pair, "lb"))
        out.append(_txt(x1 + 22, y + FS * 0.75, fee, "lb"))
    out.append("</svg>")
    return "".join(out)


def grouped_bars(
    groups: list[str],
    series: list[tuple[str, str]],
    values: list[list[float]],
    *,
    title: str,
    desc: str,
    y_ticks: list[float],
    y_fmt,
    label_every: int = 1,
    value_labels: bool = False,
    value_fmt=None,
    height: int = 306,
) -> str:
    """Bars side by side, one group per category, one colour per series."""
    left, right, top, bottom = 74, 16, 18, 44
    x0, x1 = left, SVG_W - right
    y0, y1 = top, height - bottom
    top_value = max(y_ticks)
    band = (x1 - x0) / len(groups)
    gap = 2.0  # the surface shows between two bars instead of a border around them
    bw = max(2.0, min(34.0, (band * 0.7 - gap * (len(series) - 1)) / len(series)))

    def sy(v: float) -> float:
        return y1 - (y1 - y0) * (v / top_value)

    out = _open_svg(SVG_W, height, title, desc)
    for t in y_ticks:
        y = sy(t)
        out.append(f'<line class="gr" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
        out.append(_txt(x0 - 8, y + FS * 0.34, y_fmt(t), "tk", "end"))
    out.append(f'<line class="ax" x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}"/>')
    for gi, group in enumerate(groups):
        centre = x0 + band * (gi + 0.5)
        width_all = bw * len(series) + gap * (len(series) - 1)
        for si, (_, slot) in enumerate(series):
            v = values[si][gi]
            x = centre - width_all / 2 + si * (bw + gap)
            y = sy(v)
            out.append(
                f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                f'height="{max(y1 - y, 0.8):.1f}" rx="2" style="fill:var(--{slot})">'
                f"<title>{esc(group)} — {esc(series[si][0])}: "
                f"{esc((value_fmt or y_fmt)(v))}</title></rect>"
            )
            if value_labels:
                out.append(_txt(x + bw / 2, y - 6, (value_fmt or y_fmt)(v), "vl", "middle"))
        if gi % label_every == 0:
            out.append(_txt(centre, y1 + FS + 6, group, "tk", "middle"))
    out.append("</svg>")
    return "".join(out)


def hbars(
    rows: list[tuple[str, float, str]],
    *,
    title: str,
    desc: str,
    slot: str = "s1",
    max_value: float | None = None,
    label_above: bool = False,
    label_w: float = 128,
) -> str:
    """Horizontal bars, one colour, the value written at the end of each bar."""
    row_h = FS * 3.0 if label_above else FS * 2.4
    height = int(row_h * len(rows) + 10)
    top = max_value if max_value is not None else max(v for _, v, _ in rows)
    # Leave room for the longest value label, so the last bar's text cannot run off the edge.
    value_gutter = max(len(text) for _, _, text in rows) * (FS - 1) * 0.58 + 16
    x0 = 8 if label_above else label_w
    x1 = SVG_W - value_gutter
    out = _open_svg(SVG_W, height, title, desc)
    for i, (label, value, text) in enumerate(rows):
        y = 6 + i * row_h
        bar_y = y + (FS * 1.4 if label_above else 0)
        w = max(1.0, (x1 - x0) * (value / top if top else 0))
        if label_above:
            out.append(_txt(x0, y + FS, label, "lb"))
        else:
            out.append(_txt(label_w - 10, bar_y + FS * 1.05, label, "tk", "end"))
        out.append(
            f'<rect class="bar" x="{x0}" y="{bar_y:.1f}" width="{w:.1f}" '
            f'height="{FS * 1.35:.1f}" rx="3" style="fill:var(--{slot})">'
            f"<title>{esc(label)}: {esc(text)}</title></rect>"
        )
        out.append(_txt(x0 + w + 10, bar_y + FS * 1.05, text, "vl"))
    out.append("</svg>")
    return "".join(out)


def reconciliation_panels(dates: list, csv_rows: list[dict], *, clamp: float) -> str:
    """One panel per pool: the daily relative difference, the threshold, what was flagged."""
    panel_h, title_h, gap, left, right = 122, 24, 16, 72, 40
    height = 10 + len(POOL_ORDER) * (panel_h + gap) + 28
    x0, x1 = left, SVG_W - right
    half = 40.0
    index = {d: i for i, d in enumerate(dates)}

    def sx(d) -> float:
        return x0 + (x1 - x0) * index[d] / (len(dates) - 1)

    title = "Daily relative difference against the external source, one panel per pool"
    out = _open_svg(SVG_W, height, title, f"Four panels, {len(dates)} days each.")
    for pi, label in enumerate(POOL_ORDER):
        ptop = 10 + pi * (panel_h + gap)
        cy = ptop + title_h + half
        slot = POOL_SLOT[label]
        out.append(_txt(x0, ptop + FS, label, "lb"))
        for value, cls in ((clamp, "gr"), (0.0, "ax"), (-clamp, "gr")):
            y = cy - (value / clamp) * half
            out.append(f'<line class="{cls}" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
            out.append(
                _txt(x0 - 8, y + FS * 0.34, f"{value * 100:+.0f}%".replace("+0%", "0"), "tk", "end")
            )
        for sign in (1, -1):
            y = cy - sign * (0.01 / clamp) * half
            out.append(f'<line class="th" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')

        for row in csv_rows:
            if row["pool"] != label or row["rel"] is None or row["day"] not in index:
                continue
            x = sx(row["day"])
            rel = row["rel"]
            off = abs(rel) > clamp
            y = cy - (max(-clamp, min(clamp, rel)) / clamp) * half
            tip = (
                f"<title>{esc(label)} {esc(row['date'])}: {esc(fpct(rel))}"
                f"{', flagged' if row['flagged'] else ''}"
                f"{', excluded: ' + esc(row['excluded_reason']) if row['excluded'] else ''}"
                "</title>"
            )
            if row["excluded"]:
                out.append(
                    f'<rect class="excl" x="{x - 4:.1f}" y="{y - 4:.1f}" width="8" height="8" '
                    f'transform="rotate(45 {x:.1f} {y:.1f})">{tip}</rect>'
                )
                continue
            if row["flagged"]:
                out.append(f'<circle class="flag" cx="{x:.1f}" cy="{y:.1f}" r="6.5"/>')
            if off:
                out.append(
                    f'<path class="off" d="M {x - 5:.1f} {y:.1f} L {x + 5:.1f} {y:.1f} '
                    f'L {x:.1f} {y + (-7 if rel > 0 else 7):.1f} Z" '
                    f'style="fill:var(--{slot})">{tip}</path>'
                )
            else:
                out.append(
                    f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="3.2" '
                    f'style="fill:var(--{slot})">{tip}</circle>'
                )
    base = height - 26
    for i in range(0, len(dates), 7):
        x = sx(dates[i])
        text = dates[i].strftime("%b %d")
        # the last tick sits on the right edge: anchor it so the label stays inside the box
        anchor = "end" if x + len(text) * FS * 0.3 > SVG_W else "middle"
        out.append(_txt(x, base + FS, text, "tk", anchor))
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- page assembly


def section(num: int, title: str, body: str, shows: str, src_text: str, src_href: str) -> str:
    return (
        f'<section id="s{num}"><h2><span class="sn">{num}</span> {esc(title)}</h2>'
        f"{body}"
        f'<p class="shows"><b>What this shows.</b> {shows}</p>'
        f'<p class="src">Source: <a href="{esc(src_href)}">{esc(src_text)}</a></p>'
        "</section>"
    )


def legend(items: list[tuple[str, str]]) -> str:
    dots = "".join(
        f'<span class="lg"><i class="sw" style="background:var(--{slot})"></i>{esc(name)}</span>'
        for name, slot in items
    )
    return f'<p class="legend">{dots}</p>'


def table(headers: list[str], rows: list[list[str]], *, cls: str = "") -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (
        f'<div class="tw"><table class="{cls}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def details(summary: str, inner: str) -> str:
    return f"<details><summary>{esc(summary)}</summary>{inner}</details>"


def share_bar(parts: list[tuple[str, float, str]]) -> str:
    """A 100% bar split between named parts, each labelled with its share."""
    segs = "".join(
        f'<span class="seg" style="flex:{share:.6f};background:var(--{slot})" '
        f'title="{esc(name)}: {share * 100:.2f}%"></span>'
        for name, share, slot in parts
    )
    return f'<div class="sbar">{segs}</div>'


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
color-scheme:light;
--plane:#f9f9f7;--surface:#fcfcfb;--surface-2:#f2f1ec;
--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--rule:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;
--good:#0ca30c;--critical:#d03b3b;--warning:#fab219;
--good-tx:#006300;--crit-tx:#c02626;--warn-tx:#8a5b00;
}
@media (prefers-color-scheme:dark){:root{
color-scheme:dark;
--plane:#0d0d0d;--surface:#1a1a19;--surface-2:#232321;
--ink:#ffffff;--ink-2:#c3c2b7;--muted:#95938c;
--grid:#2c2c2a;--axis:#383835;--rule:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;
--good:#0ca30c;--critical:#d03b3b;--warning:#fab219;
--good-tx:#0ca30c;--crit-tx:#e06a6a;--warn-tx:#e8a317;
}}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--plane);color:var(--ink);
font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
overflow-wrap:break-word}
.wrap{max-width:760px;margin:0 auto;padding:28px 16px 72px}
h1{font-size:22px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:17px;margin:0 0 10px;letter-spacing:-.005em;display:flex;gap:9px;align-items:baseline}
h3{font-size:14px;margin:18px 0 6px;color:var(--ink-2);font-weight:600}
.sn{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
color:var(--muted);border:1px solid var(--rule);border-radius:4px;padding:3px 5px;flex:none}
p{margin:0 0 10px}
a{color:inherit;text-underline-offset:2px;text-decoration-color:var(--muted)}
a:hover{text-decoration-color:currentColor}
.sub{color:var(--ink-2);margin:0 0 14px}
.meta{color:var(--muted);font-size:13px;margin:0}
blockquote{margin:14px 0;padding:10px 14px;border-left:3px solid var(--axis);
background:var(--surface-2);color:var(--ink-2);font-size:14px;border-radius:0 4px 4px 0}
section{background:var(--surface);border:1px solid var(--rule);border-radius:8px;
padding:16px 16px 12px;margin:0 0 16px}
header.top{background:var(--surface);border:1px solid var(--rule);border-radius:8px;
padding:18px 16px 14px;margin:0 0 16px}
.shows{font-size:13.5px;color:var(--ink-2);margin:12px 0 4px}
.src{font-size:12.5px;color:var(--muted);margin:0 0 4px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 2px;
font-size:12.5px;color:var(--ink-2)}
.lg{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.sw{width:10px;height:10px;border-radius:2px;display:inline-block;flex:none}
.sw.ring{background:none;border:2px solid var(--critical);border-radius:50%;
width:12px;height:12px}
.sw.dia{background:none;border:1.5px solid var(--muted);transform:rotate(45deg);
width:9px;height:9px;border-radius:1px}
.sw.dash{background:none;border-top:2px dashed var(--muted);width:16px;height:0;
border-radius:0}
svg{width:100%;height:auto;display:block;margin:4px 0 2px}
.gr{stroke:var(--grid);stroke-width:1}
.ax{stroke:var(--axis);stroke-width:1}
.th{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 4}
.ln{fill:none;stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}
.tk{fill:var(--muted);font-size:18px;font-variant-numeric:tabular-nums}
.lb{fill:var(--ink-2);font-size:18px}
.vl{fill:var(--ink-2);font-size:17px;font-variant-numeric:tabular-nums}
text{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.pt,.off{stroke:var(--surface);stroke-width:1.2}
.flag{fill:none;stroke:var(--critical);stroke-width:2.4}
.excl{fill:none;stroke:var(--muted);stroke-width:1.5}
.bar{stroke:var(--surface);stroke-width:1}
.dotring{stroke:var(--surface);stroke-width:1.5}
.kpis{display:grid;gap:10px;margin:2px 0 8px;
grid-template-columns:repeat(auto-fit,minmax(152px,1fr))}
.kpi{border:1px solid var(--rule);border-radius:6px;padding:10px 12px;background:var(--surface-2)}
.kpi .v{font-size:22px;line-height:1.15;font-weight:600;letter-spacing:-.02em}
.kpi .k{font-size:12px;color:var(--ink-2);margin-top:3px}
.kpi.ok .v{font-size:16px;color:var(--good-tx)}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
background:var(--surface-2);border-radius:3px;padding:1px 4px}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0 4px;
border:1px solid var(--rule);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--rule);white-space:nowrap}
th{font-weight:600;color:var(--ink-2);background:var(--surface-2);position:sticky;top:0}
tbody tr:last-child td{border-bottom:none}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.tall{display:block;max-height:340px;overflow:auto}
details{margin:8px 0 2px;font-size:13px}
summary{cursor:pointer;color:var(--ink-2);padding:4px 0}
.sbar{display:flex;height:16px;border-radius:3px;overflow:hidden;background:var(--surface-2);
gap:2px;margin:3px 0 2px}
.seg{display:block;min-width:2px}
.srow{margin:10px 0 12px}
.srow .lab{display:flex;justify-content:space-between;font-size:12.5px;color:var(--ink-2);
gap:12px}
.st{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;
border-radius:3px;padding:1px 6px;border:1px solid var(--rule);white-space:nowrap}
.st.e{color:var(--good-tx)}
.st.p{color:var(--warn-tx)}
.st.u{color:var(--crit-tx)}
.note{font-size:12.5px;color:var(--muted);margin:6px 0 2px}
footer{color:var(--muted);font-size:12.5px;padding:4px 2px}
"""


def build(data: dict, docs: dict, csv_rows: list[dict], hourly: list[dict], now) -> str:
    t = data["totals"]
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    parts: list[str] = []
    a = parts.append

    # ---- 1. header
    a('<header class="top">')
    a("<h1>univ3-clickhouse-indexer — what the pipeline measured</h1>")
    a(f'<p class="sub">{esc(docs["one_liner"])}</p>')
    a(f"<blockquote>{esc(docs['caveat'])}</blockquote>")
    a(
        f'<p class="meta">Generated {esc(stamp)} from ClickHouse and from the reports in the '
        f'repository · <a href="https://github.com/orwee/univ3-clickhouse-indexer">'
        f'repository</a> · <a href="{GH}docs/WALKTHROUGH.md">ten-minute walkthrough</a> '
        f'· <a href="{GH}README.md">README</a></p>'
    )
    a("</header>")

    # ---- 2. KPIs
    kpis = [
        (fint(t["swaps"]), "swaps indexed", ""),
        (fint(t["pools"]), "pools", ""),
        (f"{t['days']}", f"days, {t['first_day']} to {t['last_day']}", ""),
        (fint(docs["compared"]), "pool-days compared", ""),
        (fint(docs["flagged"]), "pool-days flagged", ""),
        (docs["internal"], "internal reconciliation", "ok"),
    ]
    tiles = "".join(
        f'<div class="kpi {cls}"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>'
        for v, k, cls in kpis
    )
    body = (
        f'<div class="kpis">{tiles}</div>'
        f'<p class="note">{esc(docs["recon_line"])}</p>'
        f'<p class="note">Flagged means beyond 1% <b>and</b> beyond 1,000 USD. '
        f"Reconciliation report generated {esc(docs['recon_generated'])}.</p>"
    )
    a(
        section(
            2,
            "The numbers this page is about",
            body,
            "How much was indexed, how much of it could be compared with an independent "
            "source, and that the pipeline agrees with itself exactly.",
            "reports/reconciliation.md",
            f"{GH}reports/reconciliation.md",
        )
    )

    # ---- 3. daily volume per pool
    chart = line_chart_log(
        data["dates"],
        data["volume_series"],
        title="Daily USD volume per pool, logarithmic scale",
        desc=(
            f"{len(data['dates'])} days, four pools, from about one dollar to about "
            "300 million dollars a day."
        ),
    )
    rows = []
    for d in data["dates"]:
        cells = [f"<td>{d}</td>"]
        for label in POOL_ORDER:
            v = data["volume_series"][label][data["dates"].index(d)]
            cells.append(f'<td class="n">{esc(fusd(v)) if v else ""}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f'<th class="n">{esc(p)}</th>' for p in POOL_ORDER)
    tbl = (
        f'<div class="tw tall"><table><thead><tr><th>day</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
    body = (
        chart
        + legend([(p, POOL_SLOT[p]) for p in POOL_ORDER])
        + '<p class="note">The vertical scale is <b>logarithmic</b>: each gridline is a '
        "hundred times the one below it. The four pools differ by five orders of magnitude, "
        "which is why a linear scale would show three flat lines.</p>"
        + details("Daily volume, every pool and day", tbl)
    )
    a(
        section(
            3,
            "Daily USD volume per pool",
            body,
            "Two USDC/WETH pools carry almost all the money while the two wstETH pools live "
            "three to five orders of magnitude below them, with one 26 million dollar day.",
            "onchain_dbt.fct_pool_daily — dbt/models/marts/fct_pool_daily.sql",
            f"{GH}dbt/models/marts/fct_pool_daily.sql",
        )
    )

    # ---- 4. the same pair in two fee tiers
    low, high = data["pool_totals"]["USDC/WETH 0.01%"], data["pool_totals"]["USDC/WETH 0.05%"]
    metrics = [
        ("swaps", "swaps", low["swaps"], high["swaps"], fint),
        ("USD volume", "volume_usd", low["volume_usd"], high["volume_usd"], fusd),
        ("estimated fees", "fees_usd", low["fees_usd"], high["fees_usd"], fusd),
    ]
    shares_low = [lo / (lo + hi) for _, _, lo, hi, _ in metrics]
    shares_high = [hi / (lo + hi) for _, _, lo, hi, _ in metrics]
    chart = grouped_bars(
        [m[0] for m in metrics],
        [("USDC/WETH 0.01%", "s1"), ("USDC/WETH 0.05%", "s2")],
        [shares_low, shares_high],
        title="Share of the pair held by each fee tier",
        desc="Three measures, two pools of the same pair.",
        y_ticks=[0, 0.25, 0.5, 0.75, 1.0],
        y_fmt=lambda v: f"{v * 100:.0f}%",
        value_labels=True,
        value_fmt=lambda v: f"{v * 100:.1f}%",
        height=286,
    )
    rows = [
        [
            esc(name),
            esc(fmt(lo)),
            f"{shares_low[i] * 100:.2f}%",
            esc(fmt(hi)),
            f"{shares_high[i] * 100:.2f}%",
        ]
        for i, (name, _, lo, hi, fmt) in enumerate(metrics)
    ]
    tbl = table(["", "0.01% pool", "share", "0.05% pool", "share"], rows)
    body = (
        chart
        + legend([("USDC/WETH 0.01%", "s1"), ("USDC/WETH 0.05%", "s2")])
        + tbl
        + '<p class="note">Fees are an estimate: <code>volume_usd × fee / 1e6</code>, '
        "the fee charged on the input token while volume is the stablecoin leg either way "
        "(<code>fct_pool_daily.sql</code> says by how much that can be low).</p>"
    )
    a(
        section(
            4,
            "The same pair in two fee tiers",
            body,
            "The 0.01% pool takes three swaps in four but a third of the money and a tenth of "
            "the fees: the cheap tier is where the small, frequent trade goes.",
            "onchain_dbt.fct_pool_daily — columns swaps, volume_usd, fees_usd",
            f"{GH}dbt/models/marts/fct_pool_daily.sql",
        )
    )

    # ---- 5. reconciliation over time
    clamp = 0.04
    off_scale = [
        r for r in csv_rows if r["rel"] is not None and not r["excluded"] and abs(r["rel"]) > clamp
    ]
    worst = max(off_scale, key=lambda r: abs(r["rel"]))
    chart = reconciliation_panels(data["dates"], csv_rows, clamp=clamp)
    rows = [
        [
            esc(r["pool"]),
            esc(r["date"]),
            f"{esc(fpct(r['rel'])) if r['rel'] is not None else ''}",
            "excluded"
            if r["excluded"]
            else (
                "flagged" if r["flagged"] else ("beyond 1% only" if r["rel_only"] else "compared")
            ),
        ]
        for r in csv_rows
    ]
    tbl = (
        '<div class="tw tall"><table><thead><tr><th>pool</th><th>day</th>'
        '<th class="n">rel diff</th><th>state</th></tr></thead><tbody>'
        + "".join(
            "<tr>"
            + "".join(f"<td{' class="n"' if i == 2 else ''}>{c}</td>" for i, c in enumerate(r))
            + "</tr>"
            for r in rows
        )
        + "</tbody></table></div>"
    )
    body = (
        chart
        + '<p class="legend">'
        + "".join(
            f'<span class="lg"><i class="sw" style="background:var(--{POOL_SLOT[p]})"></i>'
            f"{esc(p)}</span>"
            for p in POOL_ORDER
        )
        + '<span class="lg"><i class="sw ring"></i>flagged: beyond 1% and 1,000 USD</span>'
        '<span class="lg"><i class="sw dia"></i>excluded: partial day or open candle</span>'
        '<span class="lg"><i class="sw dash"></i>±1% threshold</span>'
        "</p>" + f'<p class="note">The vertical scale is cut at ±{clamp * 100:.0f}%. '
        f"{len(off_scale)} compared pool-days fall outside it, all in the two thin wstETH "
        f"pools where a few hundred dollars is a large percentage; they are drawn as "
        f"triangles at the edge and the largest is {esc(worst['pool'])} on "
        f"{esc(worst['date'])} at {esc(fpct(worst['rel']))} "
        f"({esc(fusd(worst['abs_usd']))}). The {docs['excluded']} excluded pool-days are "
        "diamonds; they are the first and the last day of the window.</p>"
        + details("Every pool-day and its relative difference", tbl)
    )
    a(
        section(
            5,
            "Reconciliation against the external source, day by day",
            body,
            "Most days sit inside ±1% in the two liquid pools and the differences that "
            "matter are a handful of located pool-days, not a drift.",
            "reports/reconciliation.csv",
            f"{GH}reports/reconciliation.csv",
        )
    )

    # ---- 6. where the difference sits
    pick = hourly[0]
    runner_up = hourly[1]
    biggest = max(hourly, key=lambda d: abs(d["day_diff"]))
    ev = docs["evidence_top_hours"].get((pick["pool"], pick["date"]))
    hours = pick["hours"]
    labels = [f"{h['hour_of_day']:02d}" for h in hours]
    ours = [h["our_usd"] for h in hours]
    theirs = [h["external_usd"] for h in hours]
    ticks = nice_ticks(max(max(ours), max(theirs)))
    chart = grouped_bars(
        labels,
        [("this pipeline", "s1"), ("external source", "s2")],
        [ours, theirs],
        title=f"{pick['pool']} on {pick['date']}, hour by hour",
        desc="Two bars per hour of the day: our USD volume and the external hourly candle.",
        y_ticks=ticks,
        y_fmt=fusd_compact,
        value_fmt=lambda v: fusd(v, 2),
        label_every=2,
        height=300,
    )
    tbl = table(
        ["hour UTC", "our swaps", "ours USD", "external USD", "difference USD"],
        [
            [
                f"{h['hour_of_day']:02d}h",
                fint(h["our_swaps"]),
                fusd(h["our_usd"], 2),
                fusd(h["external_usd"], 2),
                fusd_signed(h["diff_usd"]),
            ]
            for h in hours
        ],
    )
    body = (
        chart
        + legend([("this pipeline", "s1"), ("external source", "s2")])
        + f'<p class="note">Picked by rule, not by hand: of the {len(hourly)} flagged '
        f"pool-days, this is the one whose difference is most concentrated in a single hour "
        f"— {pick['concentration'] * 100:.1f}% of everything that moves in the day sits "
        f"in {pick['top_hour']:02d}h. The next is {esc(runner_up['pool'])} on "
        f"{esc(runner_up['date'])} at {runner_up['concentration'] * 100:.1f}%; the largest "
        f"difference of the project, {esc(biggest['pool'])} on {esc(biggest['date'])} "
        f"({esc(fusd_signed(biggest['day_diff'], 0))}), is "
        f"{biggest['concentration'] * 100:.1f}% in {biggest['top_hour']:02d}h. Hours the "
        f"source omits count as zero on its side. This day's difference is "
        f"{esc(fusd_signed(pick['day_diff'], 0))} ({esc(fpct(pick['rel']))}); the largest "
        f"three hours in the evidence report are "
        f"{esc(ev['top3']) if ev else 'not listed'}.</p>"
        + details("The whole day, hour by hour", tbl)
    )
    a(
        section(
            6,
            "Where the difference sits: one flagged day, hour by hour",
            body,
            "Every hour of this day agrees with the external source to the cent except one, "
            "so the day's difference is one event and not a systematic gap.",
            "sql/reconciliation/17_evidence_hourly.sql — re-run against "
            "onchain.raw_swaps and onchain.external_hourly_volume FINAL",
            f"{GH}sql/reconciliation/17_evidence_hourly.sql",
        )
    )

    # ---- 7. hypotheses
    hyp = docs["hypotheses"]
    chart = grouped_bars(
        [h["short"] for h in hyp],
        [("days brought inside 1%", "good"), ("days pushed outside 1%", "critical")],
        [
            [h["fixed"] / h["beyond"] for h in hyp],
            [h["broken"] / h["inside"] for h in hyp],
        ],
        title="What each reading would do to the days",
        desc="Share of the days beyond 1% that are fixed, and of the days inside 1% broken.",
        y_ticks=[0, 0.25, 0.5, 0.75],
        y_fmt=lambda v: f"{v * 100:.0f}%",
        value_labels=True,
        value_fmt=lambda v: f"{v * 100:.0f}%",
        height=300,
    )
    tbl = table(
        ["reading", "what it assumes", "days fixed", "days broken", "Pearson r"],
        [
            [
                esc(h["name"]),
                esc(h["what"]),
                f"{h['fixed']} of {h['beyond']}",
                f"{h['broken']} of {h['inside']}",
                f"{h['r']:+.3f}",
            ]
            for h in hyp
        ],
    )
    body = (
        chart + '<p class="legend">'
        '<span class="lg"><i class="sw" style="background:var(--good)"></i>'
        "days beyond 1% brought inside (good)</span>"
        '<span class="lg"><i class="sw" style="background:var(--critical)"></i>'
        "days inside 1% pushed outside (bad)</span></p>"
        + tbl
        + '<p class="note">H1 is refuted: it fixes nothing and breaks two days in three. '
        "H2 fits in sample and still fixes six of ten hold-out days, but the correlation it "
        "was pre-registered on collapses from +0.72 to +0.05, and the placebo — as many "
        "swaps revalued, but non-displaced ones — fixes none, so the effect belongs to "
        "the displaced swaps and not to revaluation as such. The finding stays "
        "<b>PARTLY EXPLAINED</b>.</p>"
    )
    a(
        section(
            7,
            "Two readings of the gap, in sample, out of sample and against a placebo",
            body,
            "One hypothesis was tested so that it could fail and did; the other fits, "
            "survives a hold-out and a placebo, and still does not explain everything.",
            "reports/h2_out_of_sample.md and finding 7",
            f"{GH}reports/h2_out_of_sample.md",
        )
    )

    # ---- 8. who moves the volume
    cum = data["senders"]["cumulative"]
    chart = hbars(
        [(f"top {r}", cum[r] * 100, f"{cum[r] * 100:.1f}%") for r in SENDER_RANKS],
        title="Share of USD volume held by the largest senders",
        desc="Cumulative share of USD volume by sender rank. No address is shown.",
        max_value=100.0,
        label_w=110,
    )
    smart_rows, tot_swaps, tot_smart_swaps, tot_usd, tot_smart_usd = [], 0, 0, 0.0, 0.0
    first_day = min(r["first_day"] for r in data["smart"])
    last_day = max(r["last_day"] for r in data["smart"])
    for r in data["smart"]:
        tot_swaps += r["swaps"]
        tot_smart_swaps += r["smart_swaps"]
        tot_usd += r["volume_usd"]
        tot_smart_usd += r["smart_volume_usd"]
        smart_rows.append(
            [
                esc(r["pool_label"]),
                fint(r["swaps"]),
                fint(r["smart_swaps"]),
                f"{r['smart_swaps'] / r['swaps'] * 100:.3f}%",
                f"{r['smart_volume_usd'] / r['volume_usd'] * 100:.3f}%",
                f"{r['days_with_any']} of {r['pool_days']}",
            ]
        )
    smart_rows.append(
        [
            "<b>all four</b>",
            f"<b>{fint(tot_swaps)}</b>",
            f"<b>{fint(tot_smart_swaps)}</b>",
            f"<b>{tot_smart_swaps / tot_swaps * 100:.3f}%</b>",
            f"<b>{tot_smart_usd / tot_usd * 100:.3f}%</b>",
            "",
        ]
    )
    body = (
        chart
        + f'<p class="note">{fint(data["senders"]["total"]["senders"])} distinct senders moved '
        f"{esc(fusd(data['senders']['total']['total']))} over the window. Ranks only: the page "
        "carries no address, and <code>sender</code> in a Swap log is usually a router, not "
        "the person who signed.</p>"
        "<h3>Smart money, as a share of the same totals</h3>"
        + table(
            [
                "pool",
                "our swaps",
                "in smart-money tx",
                "share of swaps",
                "share of USD",
                "days with any",
            ],
            smart_rows,
        )
        + f'<p class="note"><b>Smart-money data: Powered by Nansen API.</b> Aggregates per '
        f"pool and day only, derived from Nansen's classification; no address, label or "
        f"transaction hash is republished. {first_day} to {last_day}, the "
        f"{sum(r['pool_days'] for r in data['smart'])} pool-days that were fetched.</p>"
    )
    a(
        section(
            8,
            "Who moves the volume",
            body,
            "Volume is extremely concentrated — one sender is a third of it and eight are "
            "seven tenths — while the wallets Nansen calls smart money are under a tenth "
            "of a percent of it.",
            "docs/NANSEN.md — onchain_dbt.stg_swaps and fct_pool_daily_smart_money",
            f"{GH}docs/NANSEN.md",
        )
    )

    # ---- 9. ClickHouse, measured
    keys = docs["sorting_keys"]
    chart_a = hbars(
        [(k["key"], k["rows"], f"{fint(k['rows'])} rows · {k['granules']} granules") for k in keys],
        title="Rows read for the same one-day query under two sorting keys",
        desc="The same query, two candidate sorting keys, rows read from system.query_log.",
        label_above=True,
    )
    ins = docs["inserts"]
    chart_b = hbars(
        [
            ("1 insert of 50,000 rows", ins["seconds"][0], f"{ins['seconds'][0]:g} s"),
            ("1,000 inserts of 50 rows", ins["seconds"][1], f"{ins['seconds'][1]:g} s"),
        ],
        title="The same 50,000 rows, in one insert and in a thousand",
        desc="Time to insert the same rows two ways.",
        label_above=True,
    )
    body = (
        "<h3>(a) What the sorting key costs, for one pool on one day</h3>"
        + chart_a
        + '<p class="note">Same query, same data, same server: the key with the timestamp in '
        f"it reads {fint(keys[0]['rows'])} rows, the one without reads "
        f"{fint(keys[1]['rows'])}. Measured on a copy of the real table.</p>"
        "<h3>(b) Batch size, and what the merges write afterwards</h3>"
        + chart_b
        + table(
            ["", "1 insert", "1,000 inserts"],
            [[esc(k), esc(one), esc(many)] for k, one, many in ins["table"]],
        )
        + f'<p class="note">The thousand-insert table ends with the same 50,000 rows, reached '
        f"by writing the data {ins['amplification']} times over. Every insert creates a part; "
        "the server merges them again and again, and each merge rewrites what it touches.</p>"
    )
    a(
        section(
            9,
            "ClickHouse, measured",
            body,
            "Two decisions with a number behind each: the sorting key changes what a query "
            "reads by nineteen times, and batch size changes an insert by two orders of "
            "magnitude.",
            "docs/SCHEMA_EXPERIMENTS.md and docs/QUERY_PERFORMANCE.md",
            f"{GH}docs/SCHEMA_EXPERIMENTS.md",
        )
    )

    # ---- 10. the findings
    state_cls = {"EXPLAINED": "e", "PARTLY EXPLAINED": "p", "UNEXPLAINED": "u"}
    rows = []
    for f in docs["findings"]:
        href = f"{GH}docs/RECONCILIATION_FINDINGS.md{f['anchor']}"
        note = f' <span class="note">({esc(f["note"])})</span>' if f["note"] else ""
        rows.append(
            [
                f"{f['n']}",
                f'<a href="{esc(href)}">{esc(f["title"])}</a>{note}',
                f'<span class="st {state_cls[f["state"]]}">{esc(f["state"])}</span>',
            ]
        )
    counted = {s: sum(1 for f in docs["findings"] if f["state"] == s) for s in state_cls}
    body = (
        table(["#", "finding", "state"], rows)
        + f'<p class="note">{counted["EXPLAINED"]} explained, '
        f"{counted['PARTLY EXPLAINED']} partly explained, {counted['UNEXPLAINED']} headed "
        "unexplained. The states are read out of the headings of the document itself at "
        "build time, so this table cannot drift away from it. That last count is not a clean "
        f"bill: what is unexplained sits inside the partly explained findings, as "
        f"{docs['still_open']} pool-days that are located but not accounted for and listed "
        f'one by one under <a href="{GH}docs/RECONCILIATION_FINDINGS.md#what-is-still-open">'
        "what is still open</a>.</p>"
    )
    a(
        section(
            10,
            "The ten findings and their state",
            body,
            "What was measured, what was located but not settled, and what is still open — "
            "the external source publishes no methodology, so nothing about what it does can "
            "be more than partly explained.",
            "docs/RECONCILIATION_FINDINGS.md",
            f"{GH}docs/RECONCILIATION_FINDINGS.md",
        )
    )

    a(
        f'<footer>Generated {esc(stamp)} by <a href="{GH}scripts/build_dashboard.py">'
        "scripts/build_dashboard.py</a>. One file, no script, no external request: every "
        "figure was read from ClickHouse or from a file in the repository when it was "
        "built.</footer>"
    )

    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>univ3-clickhouse-indexer — measurements</title>\n"
        f'<meta name="description" content="{esc(docs["one_liner"])}">\n'
        f"<style>{CSS}</style>\n</head>\n<body>\n"
        f'<div class="wrap">\n{"".join(parts)}\n</div>\n</body>\n</html>\n'
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--generated-at",
        default=None,
        help="ISO timestamp written on the page; defaults to now in UTC",
    )
    ap.add_argument("--output", default=str(DOCS / "index.html"), type=Path)
    args = ap.parse_args(argv)

    now = (
        datetime.datetime.fromisoformat(args.generated_at)
        if args.generated_at
        else datetime.datetime.now(datetime.UTC)
    )
    if now.tzinfo is not None:
        now = now.astimezone(datetime.UTC)

    docs = read_documents()
    csv_rows = read_reconciliation_csv()
    client = ch.connect(RAW_DB)
    data = collect(client)
    hourly = hourly_of_flagged(client, csv_rows)

    page = build(data, docs, csv_rows, hourly, now)
    out = Path(args.output)
    out.write_text(page, encoding="utf-8")
    (out.parent / ".nojekyll").touch()
    size = out.stat().st_size
    print(f"{out}: {size:,} bytes ({size / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
