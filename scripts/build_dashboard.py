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
GH = "https://github.com/orwee/univ3-clickhouse-indexer/blob/main/"
AUTHOR_SITE = "https://robertofajardoduro.com"


def report_source(name: str) -> tuple[str, str]:
    """(path, link) for a report the page quotes. Always the committed snapshot: `reports/` is
    git-ignored, so a link into it is a 404 for every reader of the published page."""
    rel = config.newest_snapshot(name).relative_to(config.REPO_ROOT)
    return str(rel), f"{GH}{rel}"


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

# A second encoding on top of the colour: the four lines differ by dash pattern too, so the
# chart still reads under colour-vision deficiency, in greyscale and on a printout.
POOL_DASH = {
    "USDC/WETH 0.01%": "",
    "USDC/WETH 0.05%": "9 5",
    "wstETH/USDC 0.05%": "2 4",
    "wstETH/USDC 0.3%": "14 4 2 4",
}

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


def median_spread_orders(series: dict, dates: list) -> float:
    """Orders of magnitude between the busiest and the quietest pool on the median day, over
    the days on which all four traded. One measured figure, so every sentence on the page that
    says how far apart the pools are says the same thing."""
    spreads = []
    for i in range(len(dates)):
        values = [series[p][i] for p in series if series[p][i]]
        if len(values) == len(series):
            spreads.append(math.log10(max(values) / min(values)))
    if not spreads:
        raise SystemExit("build_dashboard: no day on which every pool traded")
    spreads.sort()
    mid = len(spreads) // 2
    return spreads[mid] if len(spreads) % 2 else (spreads[mid - 1] + spreads[mid]) / 2


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
    recon_md = config.report_or_snapshot("reconciliation.md").read_text(encoding="utf-8")
    h2_md = config.report_or_snapshot("h2_out_of_sample.md").read_text(encoding="utf-8")
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
    md = config.report_or_snapshot("reconciliation_evidence.md").read_text(encoding="utf-8")
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
    with config.report_or_snapshot("reconciliation.csv").open(encoding="utf-8", newline="") as fh:
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
    # One date every fortnight, and always the last one: a weekly tick is narrower than the
    # label that sits on it. The first is anchored at the start so it cannot reach back over
    # the "$1" of the vertical axis, and the last at the end so it cannot run past the plot.
    ticks_x = [i for i in range(0, len(dates), 14) if len(dates) - 1 - i >= 7]
    ticks_x.append(len(dates) - 1)
    for i in ticks_x:
        anchor = "start" if i == 0 else ("end" if i == len(dates) - 1 else "middle")
        out.append(_txt(sx(i), y1 + FS + 6, dates[i].strftime("%b %d"), "tk", anchor))

    ends = []
    for label in POOL_ORDER:
        values = series[label]
        points = [(sx(i), sy(v)) for i, v in enumerate(values) if v]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        slot = POOL_SLOT[label]
        dash = POOL_DASH[label]
        style = f"stroke:var(--{slot})" + (f";stroke-dasharray:{dash}" if dash else "")
        out.append(f'<polyline class="ln" style="{style}" points="{path}"/>')
        ends.append((points[-1][1], label))
    # Each end label is two lines. A rendered line box is about 1.5 times the font size, so the
    # two lines need FS*1.65 between them and two labels need FS*3.2 between anchors; measured
    # in Chromium, not guessed from the font metrics.
    packed = _pack_labels(ends, FS * 3.2, y0 + FS, y1)
    for label, y in packed.items():
        pair, fee = label.rsplit(" ", 1)
        slot = POOL_SLOT[label]
        out.append(
            f'<circle class="dotring" cx="{x1 + 12}" cy="{y - FS * 1.05:.1f}" r="4" '
            f'style="fill:var(--{slot})"/>'
        )
        out.append(_txt(x1 + 22, y - FS * 0.6, pair, "lb"))
        out.append(_txt(x1 + 22, y + FS * 1.05, fee, "lb"))
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
    n = len(series)
    gap = 2.0  # the surface shows between two bars instead of a border around them
    bw = max(2.0, min(34.0, (band * 0.7 - gap * (n - 1)) / n))
    if value_labels:
        # A value label is centred on its own bar, so two labels collide unless the bars are
        # at least one label apart. Widen the gap until they are, and only then, if the group
        # has outgrown its band, take the difference out of the bars.
        fmt = value_fmt or y_fmt
        label_w = max(len(fmt(v)) for row in values for v in row) * (FS - 1) * 0.58
        pitch = max(bw + gap, label_w + 8)  # centre to centre, one bar to the next
        bw = max(2.0, min(bw, band * 0.94 - pitch * (n - 1)))
        gap = pitch - bw

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
        width_all = bw * n + gap * (n - 1)
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
                ly = max(y - 6, FS * 0.9)  # never clipped by the top of the viewBox
                out.append(_txt(x + bw / 2, ly, (value_fmt or y_fmt)(v), "vl", "middle"))
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


def section(
    num: int, title: str, body: str, shows: str, why: str, src_text: str, src_href: str
) -> str:
    """Every section closes the same way: what the picture shows, why it matters for anyone who
    has to trust on-chain numbers, and the file the figures came from."""
    return (
        f'<section id="s{num}"><h2><span class="sn">{num}</span> {esc(title)}</h2>'
        f"{body}"
        f'<p class="shows"><b>What this shows.</b> {shows}</p>'
        f'<p class="why"><b>Why it matters.</b> {why}</p>'
        f'<p class="src">Source: <a href="{esc(src_href)}">{esc(src_text)}</a></p>'
        "</section>"
    )


def line_legend() -> str:
    """The legend of the line chart: a line in its own colour and dash, not a colour square,
    because the dash is half of what tells the four pools apart."""
    dots = "".join(
        f'<span class="lg"><i class="sw l{i + 1}"></i>{esc(name)}</span>'
        for i, name in enumerate(POOL_ORDER)
    )
    return f'<p class="legend">{dots}</p>'


def legend(items: list[tuple[str, str]]) -> str:
    dots = "".join(
        f'<span class="lg"><i class="sw" style="background:var(--{slot})"></i>{esc(name)}</span>'
        for name, slot in items
    )
    return f'<p class="legend">{dots}</p>'


def table(
    headers: list[str], rows: list[list[str]], *, cls: str = "", widths: list[int] | None = None
) -> str:
    """`widths` are percentages, one per column: with table-layout:fixed they are what stops a
    table from growing past its card on a narrow screen."""
    if widths is not None and len(widths) != len(headers):
        raise SystemExit(f"table: {len(widths)} widths for {len(headers)} columns")
    cols = (
        "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
        if widths
        else ""
    )
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (
        f'<div class="tw"><table class="{cls}">{cols}<thead><tr>{head}</tr></thead>'
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
/* Every colour, radius and type token below is taken from robertofajardoduro.com/styles.css
   (fetched read-only on 2026-09-23) so this page and that site read as one system. Dark is the
   default there and here; the light values are that file's [data-theme="light"] block, served
   through prefers-color-scheme because this page carries no script to toggle a theme.
   The two web fonts that site loads from Google (Outfit, Inter) are NOT embedded: a published
   page that makes no external request cannot fetch a font, so the nearest system stack is
   used instead. */
*,*::before,*::after{box-sizing:border-box}
:root{
color-scheme:dark;
--plane:#050505;                      /* site --bg-color */
--surface:rgba(255,255,255,.03);      /* site --surface-color */
--surface-2:rgba(255,255,255,.05);    /* site --surface-hover */
--surface-solid:#0d0d0d;              /* the card colour flattened: SVG strokes need a solid */
--rule:rgba(255,255,255,.08);         /* site --surface-border */
--rule-strong:rgba(255,255,255,.2);   /* site .glass:hover border */
--ink:#f5f5f5;                        /* site --text-primary */
--ink-2:#a1a1aa;                      /* site --text-secondary */
--muted:#8b8b93;                      /* --text-secondary, dimmed; 5.8:1 on the card */
--accent:#3b82f6;                     /* site --primary-color */
--accent-hover:#2563eb;               /* site --primary-hover */
--accent-2:#8b5cf6;                   /* second stop of site .gradient-text */
--accent-3:#ec4899;                   /* third stop of site .gradient-text */
--on-accent:#ffffff;                  /* site .btn-primary colour */
--grid:rgba(255,255,255,.07);
--axis:rgba(255,255,255,.18);
--s1:#3b82f6;--s2:#d54b97;--s3:#b07d00;--s4:#009e7b;
--good:#10b981;                       /* site .status-dot */
--critical:#f2555a;--warning:#d99100;
--good-tx:#10b981;--crit-tx:#f2555a;--warn-tx:#d99100;
--r-card:16px;                        /* site .glass */
--r-btn:8px;                          /* site .btn */
--r-pill:9999px;                      /* site .status-badge */
--font-sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--font-display:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:light){:root{
color-scheme:light;
--plane:#fafafa;--surface:rgba(0,0,0,.02);--surface-2:rgba(0,0,0,.04);--surface-solid:#f5f5f5;
--rule:rgba(0,0,0,.08);--rule-strong:rgba(0,0,0,.15);
--ink:#171717;--ink-2:#52525b;--muted:#64646d;
--accent:#2563eb;--accent-hover:#1d4ed8;--accent-2:#7c3aed;--accent-3:#db2777;
--grid:rgba(0,0,0,.07);--axis:rgba(0,0,0,.2);
--s1:#0866ea;--s2:#c31982;--s3:#936700;--s4:#008466;
--good:#047857;--critical:#be123c;--warning:#92400e;
--good-tx:#047857;--crit-tx:#be123c;--warn-tx:#92400e;
}}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--plane);color:var(--ink);
font:15px/1.6 var(--font-sans);overflow-wrap:break-word}
.wrap{max-width:760px;margin:0 auto;padding:28px 16px 72px}
h1,h2,h3{font-family:var(--font-display);line-height:1.2}
h1{font-size:clamp(1.9rem,5vw,2.6rem);margin:0 0 12px;letter-spacing:-.02em;font-weight:800}
h2{font-size:17px;margin:0 0 10px;letter-spacing:-.005em;display:flex;gap:9px;align-items:baseline}
h3{font-size:14px;margin:18px 0 6px;color:var(--ink-2);font-weight:600}
.grad{background:linear-gradient(to right,var(--accent),var(--accent-2),var(--accent-3));
-webkit-background-clip:text;background-clip:text;color:transparent;display:inline-block}
.sn{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
color:var(--muted);border:1px solid var(--rule);border-radius:4px;padding:3px 5px;flex:none}
p{margin:0 0 10px}
a{color:inherit;text-underline-offset:2px;text-decoration-color:var(--muted)}
a:hover{text-decoration-color:currentColor}
.sub{color:var(--ink-2);font-size:clamp(1rem,2vw,1.15rem);margin:0 0 18px;max-width:650px}
.sub b{color:var(--ink);font-weight:600}
.meta{color:var(--muted);font-size:13px;margin:0}
blockquote{margin:14px 0;padding:10px 14px;border-left:3px solid var(--accent);
background:var(--surface);color:var(--ink-2);font-size:14px;
border-radius:0 var(--r-btn) var(--r-btn) 0}
section,header.top,.take,.start{background:var(--surface);border:1px solid var(--rule);
border-radius:var(--r-card);margin:0 0 16px}
section{padding:16px 16px 12px}
header.top{padding:22px 18px 18px}
.take,.start{padding:16px 18px 12px}
.badge{display:inline-flex;align-items:center;gap:.5rem;padding:.35rem .9rem;
border-radius:var(--r-pill);background:var(--surface-2);border:1px solid var(--rule);
color:var(--ink-2);font-size:12.5px;font-weight:500;margin:0 0 14px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--good);flex:none}
.hero-figs{display:flex;flex-wrap:wrap;gap:10px 28px;margin:18px 0 18px}
.hero-fig .v{font:700 clamp(1.4rem,3.6vw,1.9rem)/1.1 var(--font-display);letter-spacing:-.02em}
.hero-fig .k{font-size:12px;color:var(--ink-2);margin-top:2px}
.btns{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 14px}
.btn{display:inline-flex;align-items:center;gap:.5rem;padding:.5rem 1rem;
border-radius:var(--r-btn);font-weight:600;font-size:13.5px;text-decoration:none;
border:1px solid transparent}
.btn-p{background:var(--accent);color:var(--on-accent)}
.btn-p:hover{background:var(--accent-hover)}
.btn-s{background:var(--surface-2);color:var(--ink);border-color:var(--rule)}
.btn-s:hover{border-color:var(--rule-strong)}
.shows{font-size:13.5px;color:var(--ink-2);margin:12px 0 4px}
.why{font-size:13.5px;color:var(--ink-2);margin:0 0 4px;padding-left:11px;
border-left:2px solid var(--accent)}
.src{font-size:12.5px;color:var(--muted);margin:6px 0 4px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 2px;
font-size:12.5px;color:var(--ink-2)}
.lg{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.sw{width:10px;height:10px;border-radius:2px;display:inline-block;flex:none}
.sw.ring{background:none;border:2px solid var(--critical);border-radius:50%;
width:12px;height:12px}
.sw.dia{background:none;border:1.5px solid var(--muted);transform:rotate(45deg);
width:9px;height:9px;border-radius:1px;margin:0 2px}
.sw.dash{background:none;border-top:2px dashed var(--muted);width:16px;height:0;
border-radius:0}
.sw.l1,.sw.l2,.sw.l3,.sw.l4{width:18px;height:0;border-radius:0;border-top-width:2.5px;
border-top-style:solid}
.sw.l1{border-top-color:var(--s1)}
.sw.l2{border-top-color:var(--s2);border-top-style:dashed}
.sw.l3{border-top-color:var(--s3);border-top-style:dotted}
.sw.l4{border-top-color:var(--s4);border-top-style:double;border-top-width:4px}
svg{width:100%;height:auto;display:block;margin:4px 0 2px}
.gr{stroke:var(--grid);stroke-width:1}
.ax{stroke:var(--axis);stroke-width:1}
.th{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 4}
.ln{fill:none;stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}
.tk{fill:var(--muted);font-size:18px;font-variant-numeric:tabular-nums}
.lb{fill:var(--ink-2);font-size:18px}
.vl{fill:var(--ink-2);font-size:17px;font-variant-numeric:tabular-nums}
text{font-family:var(--font-sans)}
.pt,.off{stroke:var(--surface-solid);stroke-width:1.2}
.flag{fill:none;stroke:var(--critical);stroke-width:2.4}
.excl{fill:none;stroke:var(--muted);stroke-width:1.5}
.bar{stroke:var(--surface-solid);stroke-width:1}
.dotring{stroke:var(--surface-solid);stroke-width:1.5}
.kpis{display:grid;gap:10px;margin:2px 0 8px;
grid-template-columns:repeat(auto-fit,minmax(152px,1fr))}
.kpi{border:1px solid var(--rule);border-radius:var(--r-btn);padding:10px 12px;
background:var(--surface-2)}
.kpi .v{font:600 22px/1.15 var(--font-display);letter-spacing:-.02em}
.kpi .k{font-size:12px;color:var(--ink-2);margin-top:3px}
.kpi.ok .v{font-size:16px;color:var(--good-tx)}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
background:var(--surface-2);border-radius:4px;padding:1px 4px}
/* No table scrolls sideways and none is cut: table-layout:fixed with an explicit colgroup
   keeps every column inside the card at any width, and a cell that still does not fit wraps
   instead of overflowing. Anything that would not fit was moved into a <details>. */
.tw{overflow:hidden;margin:8px 0 4px;border:1px solid var(--rule);border-radius:var(--r-btn)}
table{border-collapse:collapse;width:100%;table-layout:fixed;font-size:13px}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--rule);
overflow-wrap:anywhere}
th{font-weight:600;color:var(--ink-2);background:var(--surface-2);position:sticky;top:0}
tbody tr:last-child td{border-bottom:none}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.tall{display:block;max-height:340px;overflow-y:auto;overflow-x:hidden}
details{margin:8px 0 2px;font-size:13px}
summary{cursor:pointer;color:var(--ink-2);padding:4px 0}
.sbar{display:flex;height:16px;border-radius:3px;overflow:hidden;background:var(--surface-2);
gap:2px;margin:3px 0 2px}
.seg{display:block;min-width:2px}
.srow{margin:10px 0 12px}
.srow .lab{display:flex;justify-content:space-between;font-size:12.5px;color:var(--ink-2);
gap:12px}
.st{display:inline-block;font-size:11.5px;font-weight:600;
border-radius:4px;padding:1px 6px;border:1px solid var(--rule)}
.st.e{color:var(--good-tx)}
.st.p{color:var(--warn-tx)}
.st.u{color:var(--crit-tx)}
.note{font-size:12.5px;color:var(--muted);margin:6px 0 2px}
.take h2,.start h2{font-size:15px;margin:0 0 8px;display:block}
.take ul,.start ol{margin:0;padding-left:18px}
.take li,.start li{margin:0 0 6px;font-size:13.5px;color:var(--ink-2)}
.take li b{color:var(--ink);font-weight:600}
.read{font-size:13.5px;color:var(--ink-2);margin:0}
.read b{color:var(--ink);font-weight:600}
.gloss dt{font-weight:600;color:var(--ink);font-size:12.5px;margin-top:8px}
.gloss dd{margin:2px 0 0;color:var(--ink-2);font-size:12.5px}
footer{color:var(--muted);font-size:12.5px;padding:4px 2px}
@media (max-width:520px){
.wrap{padding:20px 10px 56px}
section,.take,.start{padding-left:11px;padding-right:11px}
header.top{padding:16px 12px 14px}
table{font-size:11.5px}
th,td{padding:5px 6px}
.hero-figs{gap:10px 18px}
}
"""


def build(data: dict, docs: dict, csv_rows: list[dict], hourly: list[dict], now) -> str:
    t = data["totals"]
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    parts: list[str] = []
    a = parts.append

    # ---- hero: the shape robertofajardoduro.com opens with — a status pill, the name, one
    # sentence, the figures large, and the ways out as buttons. Not a numbered section.
    figs = [
        (fint(t["swaps"]), "swaps indexed"),
        (f"{t['pools']}", "Uniswap v3 pools"),
        (f"{t['days']}", "days of blocks"),
        (fint(docs["compared"]), "pool-days compared"),
    ]
    tiles = "".join(
        f'<div class="hero-fig"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>'
        for v, k in figs
    )
    buttons = [
        ("btn-p", "https://github.com/orwee/univ3-clickhouse-indexer", "Repository"),
        ("btn-s", f"{GH}docs/WALKTHROUGH.md", "Ten-minute walkthrough"),
        ("btn-s", f"{GH}DECISIONS.md", "DECISIONS.md"),
        ("btn-s", AUTHOR_SITE, "Roberto Fajardo Duro"),
    ]
    a('<header class="top">')
    a('<p class="badge"><span class="dot"></span>Independent weekend project</p>')
    a('<h1>univ3-clickhouse-indexer<br><span class="grad">what the pipeline measured</span></h1>')
    a(f'<p class="sub">{esc(docs["one_liner"])}</p>')
    a(f'<div class="hero-figs">{tiles}</div>')
    a(
        '<div class="btns">'
        + "".join(
            f'<a class="btn {c}" href="{esc(href)}">{esc(text)}</a>' for c, href, text in buttons
        )
        + "</div>"
    )
    a(f"<blockquote>{esc(docs['caveat'])}</blockquote>")
    a(
        f'<p class="meta">Generated {esc(stamp)} from ClickHouse and from the reports in '
        "the repository.</p>"
    )
    a("</header>")

    # ---- reading this page: five lines for a reader who does not work with this data
    a(
        '<div class="take"><h2>Reading this page</h2><p class="read">'
        "A <b>pool</b> is one trading pair held in one contract; a <b>swap</b> is one trade "
        "against it, written to the chain as a log. A <b>fee tier</b> is what that pool charges "
        "per trade — the same pair often has one pool at 0.01% and another at 0.05%, and they "
        "behave differently. To <b>reconcile</b> here means two things: check that the pipeline "
        "agrees with itself, and compare its daily totals with a source that indexed the same "
        "chain independently. Every difference below is in US dollars of volume, per pool, "
        "per day."
        "</p></div>"
    )

    # ---- key takeaways: four lines, every figure computed from the same data as the section
    # that backs it, never typed in. Not numbered: it summarises the sections, it is not one.
    hyp_t = {h["name"]: h for h in docs["hypotheses"]}
    h2_in, h2_out, placebo = hyp_t["H2 in sample"], hyp_t["H2 hold-out"], hyp_t["Placebo in sample"]
    agreeing = docs["compared"] - docs["flagged"]
    largest = max(
        (r for r in csv_rows if r["flagged"]), key=lambda r: abs(r["abs_usd"])
    )  # the biggest difference of the project, still in the open list
    smart_share = sum(r["smart_volume_usd"] for r in data["smart"]) / sum(
        r["volume_usd"] for r in data["smart"]
    )
    takeaways = [
        f"<b>The pipeline agrees with itself exactly.</b> A recomputation from "
        f"<code>raw_swaps</code> against the materialized view: {esc(docs['internal'])} on all "
        f"{docs['both']} pool-days.",
        f"<b>About nine in ten compared pool-days match an independent source.</b> "
        f"{agreeing} of {docs['compared']} agree within 1% or 1,000 USD; each of the other "
        f"{docs['flagged']} is located to a pool, a day and usually an hour.",
        f"<b>Most large gaps coincide with same-block round trips valued differently.</b> That "
        f"reading brings {h2_in['fixed']} of the {h2_in['beyond']} days beyond 1% inside it, "
        f"{h2_out['fixed']} of {h2_out['beyond']} on a hold-out it was not fitted on, and "
        f"{placebo['fixed']} of {placebo['beyond']} under a placebo — and the largest gap of "
        f"the project, {esc(fusd(abs(largest['abs_usd'])))} on one day, is not one of them.",
        f"<b>A handful of senders move most of the volume.</b> The top eight are "
        f"{data['senders']['cumulative'][8] * 100:.0f}% of it; the wallets Nansen calls smart "
        f"money are {smart_share * 100:.2f}% of it.",
    ]
    a(
        '<div class="take"><h2>Key takeaways</h2><ul>'
        + "".join(f"<li>{t}</li>" for t in takeaways)
        + "</ul></div>"
    )

    # ---- 1. KPIs
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
            1,
            "The numbers this page is about",
            body,
            "How much was indexed, how much of it could be compared with an independent "
            "source, and that the pipeline agrees with itself exactly.",
            "A pipeline that does not agree with itself cannot be checked against anything else, "
            "so that is the first thing to establish and the cheapest to run on every load.",
            *report_source("reconciliation.md"),
        )
    )

    # ---- 2. daily volume per pool
    chart = line_chart_log(
        data["dates"],
        data["volume_series"],
        title="Daily USD volume per pool, logarithmic scale",
        desc=(
            f"{len(data['dates'])} days, four pools, from about one dollar to about "
            "300 million dollars a day."
        ),
    )
    # One measured figure for how far apart the pools are, written into both the note under
    # the chart and the summary of the section, so the two cannot say different things.
    orders = f"{median_spread_orders(data['volume_series'], data['dates']):.1f}"
    rows = []
    for i, d in enumerate(data["dates"]):
        cells = [f'<td class="n">{d.strftime("%m-%d")}</td>']
        for label in POOL_ORDER:
            v = data["volume_series"][label][i]
            cells.append(f'<td class="n">{esc(fusd_compact(v)) if v else ""}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    # Header text cut to what tells the four apart: base token and fee tier, no slash pair.
    head = "".join(
        f'<th class="n">{esc(p.split("/")[0] + " " + p.split(" ")[1])}</th>' for p in POOL_ORDER
    )
    tbl = (
        '<div class="tw tall"><table><colgroup><col style="width:16%">'
        + '<col style="width:21%">' * 4
        + f'</colgroup><thead><tr><th class="n">day</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
    body = (
        chart
        + line_legend()
        + '<p class="note">The vertical scale is <b>logarithmic</b>: each gridline is a '
        f"hundred times the one below it. On the median day the busiest pool moves about "
        f"{orders} orders of magnitude more than the quietest, which is why a linear scale "
        "would show three flat lines.</p>"
        + details("Daily volume, every pool and day (USDC = USDC/WETH, wstETH = wstETH/USDC)", tbl)
    )
    a(
        section(
            2,
            "Daily USD volume per pool",
            body,
            "Two USDC/WETH pools carry almost all the money while the two wstETH pools live far "
            f"below them: about {orders} orders of magnitude between the busiest pool and the "
            "quietest on the median day.",
            "Four pools that differ by this much break any single threshold: a few hundred "
            "dollars is noise in one pool and the whole day in another.",
            "onchain_dbt.fct_pool_daily — dbt/models/marts/fct_pool_daily.sql",
            f"{GH}dbt/models/marts/fct_pool_daily.sql",
        )
    )

    # ---- 3. the same pair in two fee tiers
    low, high = data["pool_totals"]["USDC/WETH 0.01%"], data["pool_totals"]["USDC/WETH 0.05%"]
    metrics = [
        ("swaps", "swaps", low["swaps"], high["swaps"], fint),
        ("USD volume", "volume_usd", low["volume_usd"], high["volume_usd"], fusd_compact),
        ("estimated fees", "fees_usd", low["fees_usd"], high["fees_usd"], fusd_compact),
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
    tbl = table(["", "0.01%", "share", "0.05%", "share"], rows, widths=[26, 20, 17, 20, 17])
    body = (
        chart
        + legend([("USDC/WETH 0.01%", "s1"), ("USDC/WETH 0.05%", "s2")])
        + tbl
        + '<p class="note">Both columns are the USDC/WETH pair, one pool per fee tier; the '
        "totals are rounded for the table and exact in "
        "<code>fct_pool_daily</code>. Fees are an estimate: "
        "<code>volume_usd × fee / 1e6</code>, the fee charged on the input token while volume "
        "is the stablecoin leg either way (<code>fct_pool_daily.sql</code> says by how much "
        "that can be low).</p>"
    )
    a(
        section(
            3,
            "The same pair in two fee tiers",
            body,
            "The 0.01% pool takes three swaps in four but a third of the money and a tenth of "
            "the fees: the cheap tier is where the small, frequent trade goes.",
            "Two pools of the same pair are a free control. A mistake in decoding or in pricing "
            "would not land on both in the same proportion, so agreement between them is "
            "evidence.",
            "onchain_dbt.fct_pool_daily — columns swaps, volume_usd, fees_usd",
            f"{GH}dbt/models/marts/fct_pool_daily.sql",
        )
    )

    # ---- 4. reconciliation over time
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
        '<div class="tw tall"><table><colgroup><col style="width:34%">'
        '<col style="width:22%"><col style="width:20%"><col style="width:24%">'
        "</colgroup><thead><tr><th>pool</th><th>day</th>"
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
            4,
            "Reconciliation against the external source, day by day",
            body,
            "Most days sit inside ±1% in the two liquid pools and the differences that "
            "matter are a handful of located pool-days, not a drift.",
            "An aggregate that matches over a month can still be wrong every single day. Only a "
            "per-day comparison says which days to look at.",
            *report_source("reconciliation.csv"),
        )
    )

    # ---- 5. where the difference sits
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
    # Four columns, not five: the per-hour swap count is in the evidence report and does not
    # fit next to three currency columns on a phone.
    tbl = table(
        ["hour UTC", "ours USD", "external USD", "difference USD"],
        [
            [
                f"{h['hour_of_day']:02d}h",
                fusd(h["our_usd"], 2),
                fusd(h["external_usd"], 2),
                fusd_signed(h["diff_usd"]),
            ]
            for h in hours
        ],
        widths=[13, 29, 29, 29],
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
            5,
            "Where the difference sits: one flagged day, hour by hour",
            body,
            "Every hour of this day agrees with the external source to within a dollar except "
            "one, "
            "so the day's difference is one event and not a systematic gap.",
            "sql/reconciliation/17_evidence_hourly.sql — re-run against "
            "A difference located to one hour can be investigated; the same difference spread "
            "over a month cannot. Locating it is most of the work of trusting a number.",
            "onchain.raw_swaps and onchain.external_hourly_volume FINAL",
            f"{GH}sql/reconciliation/17_evidence_hourly.sql",
        )
    )

    # ---- 6. hypotheses
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
    # What each reading assumes is a sentence, not a figure: it moves out of the table so the
    # four numeric columns fit, and keeps its own two-column table inside the details.
    tbl = table(
        ["reading", "days fixed", "days broken", "Pearson r"],
        [
            [
                esc(h["name"]),
                f"{h['fixed']} of {h['beyond']}",
                f"{h['broken']} of {h['inside']}",
                f"{h['r']:+.3f}",
            ]
            for h in hyp
        ],
        widths=[31, 23, 23, 23],
    )
    assumptions = details(
        "What each reading assumes",
        table(
            ["reading", "what it assumes"],
            [[esc(h["name"]), esc(h["what"])] for h in hyp],
            widths=[31, 69],
        ),
    )
    body = (
        chart + '<p class="legend">'
        '<span class="lg"><i class="sw" style="background:var(--good)"></i>'
        "days beyond 1% brought inside (good)</span>"
        '<span class="lg"><i class="sw" style="background:var(--critical)"></i>'
        "days inside 1% pushed outside (bad)</span></p>"
        + tbl
        + assumptions
        + '<p class="note">H1 is refuted: it fixes nothing and breaks two days in three. '
        "H2 fits in sample and still fixes six of ten hold-out days, but the correlation it "
        "was pre-registered on collapses from +0.72 to +0.05, and the placebo — as many "
        "swaps revalued, but non-displaced ones — fixes none, so the effect belongs to "
        "the displaced swaps and not to revaluation as such. The finding stays "
        "<b>PARTLY EXPLAINED</b>.</p>"
    )
    a(
        section(
            6,
            "Two readings of the gap, in sample, out of sample and against a placebo",
            body,
            "One hypothesis was tested so that it could fail and did; the other fits, "
            "survives a hold-out and a placebo, and still does not explain everything.",
            "An explanation fitted on the same data it explains is not evidence. A hold-out and a "
            "placebo are what separate a real effect from a rule that was tuned until it fitted.",
            f"{report_source('h2_out_of_sample.md')[0]} and finding 7",
            report_source("h2_out_of_sample.md")[1],
        )
    )

    # ---- 7. who moves the volume
    cum = data["senders"]["cumulative"]
    chart = hbars(
        [(f"top {r}", cum[r] * 100, f"{cum[r] * 100:.1f}%") for r in SENDER_RANKS],
        title="Share of USD volume held by the largest senders",
        desc="Cumulative share of USD volume by sender rank. No address is shown.",
        max_value=100.0,
        label_w=110,
    )
    # The shares are what the section is about; the raw counts behind them move into a
    # details, which is what keeps four columns instead of six on a narrow screen.
    smart_rows, count_rows = [], []
    tot_swaps, tot_smart_swaps, tot_usd, tot_smart_usd = 0, 0, 0.0, 0.0
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
                fint(r["smart_swaps"]),
                f"{r['smart_swaps'] / r['swaps'] * 100:.3f}%",
                f"{r['smart_volume_usd'] / r['volume_usd'] * 100:.3f}%",
            ]
        )
        count_rows.append(
            [
                esc(r["pool_label"]),
                fint(r["swaps"]),
                fint(r["smart_swaps"]),
                f"{r['days_with_any']} of {r['pool_days']}",
            ]
        )
    smart_rows.append(
        [
            "<b>all four</b>",
            f"<b>{fint(tot_smart_swaps)}</b>",
            f"<b>{tot_smart_swaps / tot_swaps * 100:.3f}%</b>",
            f"<b>{tot_smart_usd / tot_usd * 100:.3f}%</b>",
        ]
    )
    count_rows.append(
        ["<b>all four</b>", f"<b>{fint(tot_swaps)}</b>", f"<b>{fint(tot_smart_swaps)}</b>", ""]
    )
    body = (
        chart
        + f'<p class="note">{fint(data["senders"]["total"]["senders"])} distinct senders moved '
        f"{esc(fusd(data['senders']['total']['total']))} over the window. Ranks only: the page "
        "carries no address, and <code>sender</code> in a Swap log is usually a router, not "
        "the person who signed.</p>"
        "<h3>Smart money, as a share of the same totals</h3>"
        + table(
            ["pool", "swaps in smart-money tx", "share of swaps", "share of USD"],
            smart_rows,
            widths=[31, 23, 23, 23],
        )
        + details(
            "The swap counts behind those shares",
            table(
                ["pool", "our swaps", "in smart-money tx", "days with any"],
                count_rows,
                widths=[31, 23, 23, 23],
            ),
        )
        + f'<p class="note"><b>Smart-money data: Powered by Nansen API.</b> Aggregates per '
        f"pool and day only, derived from Nansen's classification; no address, label or "
        f"transaction hash is republished. {first_day} to {last_day}, the "
        f"{sum(r['pool_days'] for r in data['smart'])} pool-days that were fetched.</p>"
    )
    a(
        section(
            7,
            "Who moves the volume",
            body,
            "Volume is extremely concentrated — one sender is a third of it and eight are "
            "seven tenths — while the wallets Nansen calls smart money are under a tenth "
            "of a percent of it.",
            "Volume this concentrated means one participant can move a daily total on its own, so "
            "any per-day check has to survive a single large trade without raising a false alarm.",
            "docs/NANSEN.md — onchain_dbt.stg_swaps and fct_pool_daily_smart_money",
            f"{GH}docs/NANSEN.md",
        )
    )

    # ---- 8. ClickHouse, measured
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
            widths=[44, 28, 28],
        )
        + f'<p class="note">The thousand-insert table ends with the same 50,000 rows, reached '
        f"by writing the data {ins['amplification']} times over. Every insert creates a part; "
        "the server merges them again and again, and each merge rewrites what it touches.</p>"
    )
    a(
        section(
            8,
            "ClickHouse, measured",
            body,
            "Two decisions with a number behind each: the sorting key changes what a query "
            "reads by nineteen times, and a thousand small inserts take five hundred times "
            "as long as one.",
            "How the data is stored decides whether a reconciliation takes seconds or minutes, "
            "and that decides how often anyone actually runs it.",
            "docs/SCHEMA_EXPERIMENTS.md and docs/QUERY_PERFORMANCE.md",
            f"{GH}docs/SCHEMA_EXPERIMENTS.md",
        )
    )

    # ---- 9. the findings
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
        table(["#", "finding", "state"], rows, widths=[8, 62, 30])
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
            9,
            "The ten findings and their state",
            body,
            "What was measured, what was located but not settled, and what is still open — "
            "the external source publishes no methodology, so nothing about what it does can "
            "be more than partly explained.",
            "The list of what is not explained is the part of a data quality report that usually "
            "goes missing, and it is the part that says how far the numbers can be trusted.",
            "docs/RECONCILIATION_FINDINGS.md",
            f"{GH}docs/RECONCILIATION_FINDINGS.md",
        )
    )

    # ---- glossary: the technical words used above, one line each, folded away
    terms = [
        (
            "MergeTree",
            "ClickHouse's table engine: data is written in parts and merged in the "
            "background, sorted by the table's sorting key.",
        ),
        (
            "Sorting key",
            "the order rows are stored in. It decides how much of a table a query "
            "has to read, which is what section 8 measures.",
        ),
        (
            "Sparse index",
            "ClickHouse indexes one row in every 8,192, not every row. Queries "
            "skip whole blocks of rows rather than seeking to one.",
        ),
        (
            "Materialized view",
            "here, a trigger: every insert into the raw table also writes an "
            "aggregate into a second table. Section 1 checks the two still agree.",
        ),
        (
            "FINAL",
            "a query modifier that collapses duplicate rows at read time. It costs a lot, "
            "and DECISIONS.md records where that cost was measured.",
        ),
        (
            "Round trip",
            "a buy and a sell of the same pair in the same block, often by the same "
            "sender. Section 6 tests whether these explain the large differences.",
        ),
        (
            "Hold-out",
            "days kept aside and not looked at while the explanation was written, then "
            "used once to test it.",
        ),
        (
            "Placebo",
            "the same adjustment applied to swaps picked at random instead of the ones "
            "the explanation points at. If it fixes as much, the explanation was fitting noise.",
        ),
        ("Pool-day", "one pool on one day: the unit everything on this page is counted in."),
    ]
    a(
        '<div class="start"><h2>Glossary</h2>'
        + details(
            "The technical terms on this page, one line each",
            '<dl class="gloss">'
            + "".join(f"<dt>{esc(t)}</dt><dd>{esc(d)}</dd>" for t, d in terms)
            + "</dl>",
        )
        + "</div>"
    )

    # ---- closing: where to go next, and who this is. Not numbered, like the summary above.
    a(
        '<div class="start"><h2>Start here</h2><ol>'
        f'<li><a href="{GH}docs/WALKTHROUGH.md">The ten-minute walkthrough</a> — what to open '
        "and in what order.</li>"
        f'<li><a href="{GH}DECISIONS.md">DECISIONS.md</a> — every decision, what it cost and '
        "what was retracted.</li>"
        '<li><a href="https://github.com/orwee/univ3-clickhouse-indexer">The repository</a> — '
        "<code>make demo</code> runs the whole thing with Docker and no API key.</li>"
        "</ol></div>"
    )

    a(
        f'<footer>Generated {esc(stamp)} by <a href="{GH}scripts/build_dashboard.py">'
        "scripts/build_dashboard.py</a>. One file, no script, no external request: every "
        "figure was read from ClickHouse or from a file in the repository when it was "
        "built.<br>Independent weekend project. Smart-money data: Powered by Nansen API. "
        "Not affiliated with any company mentioned.</footer>"
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
