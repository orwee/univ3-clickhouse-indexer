"""The template cases of the golden set: twelve families, ten cases each.

Everything here is about this warehouse: its tables, its columns, its pools. The generic
part (the shape of a case, running the queries, the split, the file) is `evalkit.golden`.

`draw(seed)` needs no server. It reads the committed fixture files to know which pools and
which days exist, draws parameters with a fixed seed, and returns cases WITHOUT answers:
a question and the query that answers it. The answers are computed later, by running each
query on the fixture loaded into a throw-away database. No answer is written here.

What the draws respect, and tests/test_golden.py checks:
- only complete days. The first and the last day of the data are partial;
- never a pool on a day it has no row for;
- a question whose answer is a pool or a day is only drawn when the maximum is not tied.
"""

from __future__ import annotations

import datetime
import random
from decimal import Decimal

from evalkit import fixture
from evalkit.golden import Spec

# The first and the last day of the data hold only part of a day (the landing window starts
# and ends mid-day). docs/evidence/2026-09-25/reconciliation.csv marks them `partial_day`;
# a test compares these two constants with that file.
FIRST_COMPLETE_DAY = datetime.date(2026, 8, 10)
LAST_COMPLETE_DAY = datetime.date(2026, 9, 24)
# The symbols that count as a US dollar, as in dbt/dbt_project.yml (stablecoin_symbols).
STABLE = ("USDC", "USDT", "DAI")
CASES_PER_FAMILY = 10
DAILY = "fct_pool_daily"
ROUND_TRIPS = "fct_pool_daily_round_trips"


class Facts:
    """Which pools and which pool-days exist, read from the fixture files."""

    def __init__(self):
        pools = fixture.read_table("dim_pools")
        self.pools = {
            row[pools.columns.index("pool_label")]: {
                "token0": row[pools.columns.index("token0")],
                "token1": row[pools.columns.index("token1")],
            }
            for row in pools.rows
        }
        daily = fixture.read_table(DAILY)
        column = daily.columns.index
        self.rows = {
            (row[column("pool_label")], datetime.date.fromisoformat(row[column("block_date")])): {
                "swaps": int(row[column("swaps")]),
                "volume_usd": Decimal(row[column("volume_usd")]),
            }
            for row in daily.rows
        }
        self.labels = sorted(self.pools)
        self.complete_days = [
            FIRST_COMPLETE_DAY + datetime.timedelta(days=i)
            for i in range((LAST_COMPLETE_DAY - FIRST_COMPLETE_DAY).days + 1)
        ]

    def has(self, label: str, day: datetime.date) -> bool:
        return (label, day) in self.rows

    def days_of(self, label: str) -> list[datetime.date]:
        return [day for day in self.complete_days if self.has(label, day)]

    def pair_of(self, label: str) -> tuple[str, str]:
        return self.pools[label]["token0"], self.pools[label]["token1"]

    def labels_of_pair(self, pair: tuple[str, str]) -> list[str]:
        return [label for label in self.labels if self.pair_of(label) == pair]


def lit(text: str) -> str:
    """A text as an SQL string literal. Labels and symbols hold no quote; this checks it."""
    if "'" in text or "\\" in text:
        raise ValueError(f"cannot be written as a literal: {text!r}")
    return f"'{text}'"


def long_date(day: datetime.date) -> str:
    return f"{day.day} {day:%B} {day.year}"


def said(day: datetime.date, i: int) -> str:
    """The day as the question writes it: ISO in some wordings, in words in others."""
    return day.isoformat() if i % 2 == 0 else long_date(day)


def _in_list(labels: list[str]) -> str:
    return ", ".join(lit(label) for label in labels)


def _pair_filter(pair: tuple[str, str]) -> str:
    return (
        f"pool_address IN (SELECT pool_address FROM dim_pools "
        f"WHERE token0 = {lit(pair[0])} AND token1 = {lit(pair[1])})"
    )


# --- the twelve families ------------------------------------------------------------------
# Each takes the facts, a random generator and the index of the case within the family, and
# returns (params, question, answer_type, unit, tolerance, reference_sql, unique_sql).


def volume_day(f: Facts, rng: random.Random, i: int):
    label = rng.choice(f.labels)
    day = rng.choice(f.days_of(label))
    wording = [
        "What was the dollar volume of the {label} pool on {day}? Answer in US dollars.",
        "How many US dollars were traded in the {label} pool on {day} (UTC day)?",
        "Give the total volume, in USD, of {label} for {day}.",
    ][i % 3]
    sql = (
        f"SELECT volume_usd FROM {DAILY} "
        f"WHERE pool_label = {lit(label)} AND block_date = {lit(day.isoformat())}"
    )
    return {"label": label, "day": day}, wording.format(label=label, day=said(day, i)), "number", "USD", "sum", sql, None  # fmt: skip


def swaps_day(f: Facts, rng: random.Random, i: int):
    label = rng.choice(f.labels)
    day = rng.choice(f.days_of(label))
    wording = [
        "How many swaps did the {label} pool have on {day}? Answer with the number of swaps.",
        "Count the swaps in {label} on {day} (UTC day).",
        "What was the number of swaps in the {label} pool on {day}?",
    ][i % 3]
    sql = (
        f"SELECT swaps FROM {DAILY} "
        f"WHERE pool_label = {lit(label)} AND block_date = {lit(day.isoformat())}"
    )
    return {"label": label, "day": day}, wording.format(label=label, day=said(day, i)), "number", "swaps", "count", sql, None  # fmt: skip


def token_volume_day(f: Facts, rng: random.Random, i: int):
    label = rng.choice(f.labels)
    day = rng.choice(f.days_of(label))
    token = rng.choice(f.pair_of(label))
    wording = [
        "How much {token} was traded in the {label} pool on {day}? Answer in {token}, not in dollars.",
        "What was the volume of {token}, in units of {token}, in {label} on {day}?",
    ][i % 2]  # fmt: skip
    sql = (
        f"SELECT if(p.token0 = {lit(token)}, d.volume_token0, d.volume_token1) AS volume "
        f"FROM {DAILY} AS d INNER JOIN dim_pools AS p ON p.pool_address = d.pool_address "
        f"WHERE d.pool_label = {lit(label)} AND d.block_date = {lit(day.isoformat())}"
    )
    question = wording.format(token=token, label=label, day=said(day, i))
    return {"label": label, "day": day, "token": token}, question, "number", token, "sum", sql, None  # fmt: skip


def volume_all_day(f: Facts, rng: random.Random, i: int):
    day = rng.choice(f.complete_days)
    wording = [
        "What was the total dollar volume of all pools together on {day}? Answer in US dollars.",
        "Across every pool in the data, how many USD were traded on {day}?",
        "Give the combined volume in US dollars of all the pools on {day} (UTC day).",
    ][i % 3]
    sql = f"SELECT sum(volume_usd) FROM {DAILY} WHERE block_date = {lit(day.isoformat())}"
    return {"day": day}, wording.format(day=said(day, i)), "number", "USD", "sum", sql, None


def _range(f: Facts, rng: random.Random, label: str | None, shortest: int, longest: int):
    """A range of complete days; with a label, one in which the pool has a row every day."""
    while True:
        start = rng.choice(f.complete_days)
        end = start + datetime.timedelta(days=rng.randint(shortest, longest) - 1)
        if end > LAST_COMPLETE_DAY:
            continue
        days = [start + datetime.timedelta(days=k) for k in range((end - start).days + 1)]
        if label is None or all(f.has(label, day) for day in days):
            return start, end


def _between(start: datetime.date, end: datetime.date, column: str = "block_date") -> str:
    return f"{column} BETWEEN {lit(start.isoformat())} AND {lit(end.isoformat())}"


def volume_range(f: Facts, rng: random.Random, i: int):
    label = rng.choice(f.labels)
    start, end = _range(f, rng, label, 2, 21)
    wording = [
        "What was the dollar volume of the {label} pool from {a} to {b}, both days included? Answer in US dollars.",
        "How many USD were traded in {label} between {a} and {b} inclusive?",
        "Add up the volume in US dollars of the {label} pool for every day from {a} through {b}.",
    ][i % 3]  # fmt: skip
    sql = f"SELECT sum(volume_usd) FROM {DAILY} WHERE pool_label = {lit(label)} AND {_between(start, end)}"  # fmt: skip
    question = wording.format(label=label, a=said(start, i), b=said(end, i))
    return {"label": label, "start": start, "end": end}, question, "number", "USD", "sum", sql, None  # fmt: skip


def swaps_all_range(f: Facts, rng: random.Random, i: int):
    start, end = _range(f, rng, None, 2, 21)
    wording = [
        "How many swaps were there in all pools together from {a} to {b}, both days included?",
        "Count every swap in the data between {a} and {b} inclusive, across all pools.",
    ][i % 2]
    sql = f"SELECT sum(swaps) FROM {DAILY} WHERE {_between(start, end)}"
    question = wording.format(a=said(start, i), b=said(end, i))
    return {"start": start, "end": end}, question, "number", "swaps", "count", sql, None


def vwap_day(f: Facts, rng: random.Random, i: int):
    label = rng.choice(f.labels)
    day = rng.choice(f.days_of(label))
    token0, token1 = f.pair_of(label)
    stable, other = (token0, token1) if token0 in STABLE else (token1, token0)
    wording = [
        "What was the volume-weighted average price of {other} in the {label} pool on {day}, in {stable} per {other}?",
        "Give the volume-weighted average price of {other}, in {stable}, for {label} on {day}: the {stable} volume divided by the {other} volume.",
    ][i % 2]  # fmt: skip
    sql = (
        f"SELECT if(p.token0 IN ({_in_list(list(STABLE))}), "
        "d.volume_token0 / d.volume_token1, d.volume_token1 / d.volume_token0) AS vwap "
        f"FROM {DAILY} AS d INNER JOIN dim_pools AS p ON p.pool_address = d.pool_address "
        f"WHERE d.pool_label = {lit(label)} AND d.block_date = {lit(day.isoformat())}"
    )
    question = wording.format(other=other, stable=stable, label=label, day=said(day, i))
    return {"label": label, "day": day}, question, "number", f"{stable} per {other}", "ratio", sql, None  # fmt: skip


def top_pool_day(f: Facts, rng: random.Random, i: int):
    metric = ("swaps", "volume_usd")[i % 2]
    pairs = sorted({f.pair_of(label) for label in f.labels})
    while True:
        day = rng.choice(f.complete_days)
        pair = rng.choice([None, *pairs])  # None: all pools
        labels = f.labels if pair is None else f.labels_of_pair(pair)
        if not all(f.has(label, day) for label in labels):
            continue
        values = sorted((f.rows[(label, day)][metric] for label in labels), reverse=True)
        if values[0] != values[1]:  # a tied maximum has no single answer
            break
    scope = "true" if pair is None else _pair_filter(pair)
    where = f"block_date = {lit(day.isoformat())} AND {scope}".replace(" AND true", "")
    what = {"swaps": "the most swaps", "volume_usd": "the highest dollar volume"}[metric]
    among = "Of all the pools" if pair is None else f"Of the {pair[0]}/{pair[1]} pools"
    wording = [
        "{among}, which one had {what} on {day}? Answer with the pool's label.",
        "{among}, name the pool with {what} on {day}.",
    ][(i // 2) % 2]
    sql = f"SELECT pool_label FROM {DAILY} WHERE {where} ORDER BY {metric} DESC LIMIT 1"
    unique = (
        f"SELECT count() FROM {DAILY} WHERE {where} "
        f"AND {metric} = (SELECT max({metric}) FROM {DAILY} WHERE {where})"
    )
    question = wording.format(among=among, what=what, day=said(day, i))
    return {"day": day, "labels": labels, "metric": metric}, question, "label", None, None, sql, unique  # fmt: skip


def peak_day_range(f: Facts, rng: random.Random, i: int):
    while True:
        label = rng.choice(f.labels)
        start, end = _range(f, rng, label, 5, 21)
        days = [start + datetime.timedelta(days=k) for k in range((end - start).days + 1)]
        values = sorted((f.rows[(label, day)]["volume_usd"] for day in days), reverse=True)
        if values[0] != values[1]:
            break
    where = f"pool_label = {lit(label)} AND {_between(start, end)}"
    wording = [
        "On which day from {a} to {b}, both included, did the {label} pool have its highest dollar volume? Answer with the date.",
        "Between {a} and {b} inclusive, which UTC day was the biggest for {label} by volume in US dollars?",
    ][i % 2]  # fmt: skip
    sql = f"SELECT block_date FROM {DAILY} WHERE {where} ORDER BY volume_usd DESC LIMIT 1"
    unique = (
        f"SELECT count() FROM {DAILY} WHERE {where} "
        f"AND volume_usd = (SELECT max(volume_usd) FROM {DAILY} WHERE {where})"
    )
    question = wording.format(label=label, a=said(start, i), b=said(end, i))
    return {"label": label, "start": start, "end": end}, question, "date", None, None, sql, unique  # fmt: skip


def volume_change(f: Facts, rng: random.Random, i: int):
    label = rng.choice(f.labels)
    first, second = sorted(rng.sample(f.days_of(label), 2))
    a, b = lit(first.isoformat()), lit(second.isoformat())
    later, earlier = f"sumIf(volume_usd, block_date = {b})", f"sumIf(volume_usd, block_date = {a})"
    where = f"pool_label = {lit(label)} AND block_date IN ({a}, {b})"
    if i % 2 == 0:
        wording = [
            "By how many US dollars did the daily volume of the {label} pool change from {a} to {b}? Give the absolute change in USD, negative if it fell.",
            "What is the volume of {label} on {b} minus its volume on {a}, in US dollars?",
        ][(i // 2) % 2]  # fmt: skip
        sql, unit, tolerance = f"SELECT {later} - {earlier} AS change FROM {DAILY} WHERE {where}", "USD", "sum"  # fmt: skip
    else:
        wording = [
            "By what percentage did the daily dollar volume of the {label} pool change from {a} to {b}? Answer in percent, negative if it fell.",
            "Relative to {a}, how much higher or lower was the dollar volume of {label} on {b}? Give the change in percent of the earlier day.",
        ][(i // 2) % 2]  # fmt: skip
        sql = f"SELECT 100 * ({later} - {earlier}) / {earlier} AS change FROM {DAILY} WHERE {where}"
        unit, tolerance = "percent", "ratio"
    question = wording.format(label=label, a=said(first, i), b=said(second, i))
    return {"label": label, "days": [first, second]}, question, "number", unit, tolerance, sql, None  # fmt: skip


def fees(f: Facts, rng: random.Random, i: int):
    label = rng.choice(f.labels)
    if i % 2 == 0:
        day = rng.choice(f.days_of(label))
        wording = [
            "What were the estimated fees, in US dollars, of the {label} pool on {day}?",
            "How many USD in fees did swaps in {label} pay on {day}, as estimated from volume and fee tier?",
        ][(i // 2) % 2]  # fmt: skip
        sql = f"SELECT fees_usd FROM {DAILY} WHERE pool_label = {lit(label)} AND block_date = {lit(day.isoformat())}"  # fmt: skip
        return {"label": label, "day": day}, wording.format(label=label, day=said(day, i)), "number", "USD", "sum", sql, None  # fmt: skip
    start, end = _range(f, rng, label, 2, 21)
    wording = [
        "What were the estimated fees, in US dollars, of the {label} pool from {a} to {b}, both days included?",
        "Add up the estimated fees in USD of {label} between {a} and {b} inclusive.",
    ][(i // 2) % 2]  # fmt: skip
    sql = f"SELECT sum(fees_usd) FROM {DAILY} WHERE pool_label = {lit(label)} AND {_between(start, end)}"  # fmt: skip
    question = wording.format(label=label, a=said(start, i), b=said(end, i))
    return {"label": label, "start": start, "end": end}, question, "number", "USD", "sum", sql, None  # fmt: skip


def share(f: Facts, rng: random.Random, i: int):
    variant = ("tier", "round_trip", "net", "tier", "round_trip", "net", "tier", "round_trip", "net", "tier")[i]  # fmt: skip
    while True:
        label = rng.choice(f.labels)
        day = rng.choice(f.days_of(label))
        pair = f.pair_of(label)
        if variant != "tier" or all(f.has(other, day) for other in f.labels_of_pair(pair)):
            break
    params = {"label": label, "day": day, "variant": variant}
    day_sql, here = lit(day.isoformat()), said(day, i)
    if variant == "tier":
        question = (
            f"On {here}, what share of the dollar volume of the {pair[0]}/{pair[1]} pair went "
            f"through the {label} pool? Answer in percent of the pair's volume across its fee tiers."
        )
        sql = (
            f"SELECT 100 * sumIf(volume_usd, pool_label = {lit(label)}) / sum(volume_usd) AS share "
            f"FROM {DAILY} WHERE block_date = {day_sql} AND {_pair_filter(pair)}"
        )
        params["labels"] = f.labels_of_pair(pair)
        return params, question, "number", "percent", "ratio", sql, None
    where = f"pool_label = {lit(label)} AND block_date = {day_sql}"
    if variant == "round_trip":
        question = (
            f"What share of the dollar volume of the {label} pool on {here} was round trips? "
            "Answer in percent of that day's volume."
        )
        sql = f"SELECT 100 * round_trip_volume_usd / volume_usd AS share FROM {ROUND_TRIPS} WHERE {where}"  # fmt: skip
        return params, question, "number", "percent", "ratio", sql, None
    question = (
        f"What was the dollar volume of the {label} pool on {here} excluding round trips? "
        "Answer in US dollars."
    )
    sql = f"SELECT net_volume_usd FROM {ROUND_TRIPS} WHERE {where}"
    return params, question, "number", "USD", "sum", sql, None


FAMILIES = {
    "volume-day": (
        volume_day,
        "The simplest lookup: one row, one column. A model that fails here fails at reading the schema.",
    ),  # fmt: skip
    "swaps-day": (
        swaps_day,
        "A count, exact. Catches a model that answers with volume, or that counts rows of the daily table.",
    ),  # fmt: skip
    "token-volume-day": (
        token_volume_day,
        "Which volume column holds which token depends on the pool: token0 is not the same token in every pool. Catches a model that picks a column by position.",
    ),  # fmt: skip
    "volume-all-day": (
        volume_all_day,
        "An aggregate over pools. Catches a model that returns one pool, or reads rows and adds them itself.",
    ),  # fmt: skip
    "volume-range": (
        volume_range,
        "An aggregate over days with both ends included. Catches an off-by-one on the range.",
    ),  # fmt: skip
    "swaps-all-range": (
        swaps_all_range,
        "A count over days and pools. Catches count() of rows in place of sum(swaps).",
    ),  # fmt: skip
    "vwap-day": (
        vwap_day,
        "A ratio of two columns, and which is the numerator depends on the pool. Catches an inverted price and an average of prices that is not weighted.",
    ),  # fmt: skip
    "top-pool-day": (
        top_pool_day,
        "The answer is a label. Drawn only where the maximum is not tied, so there is one right pool.",
    ),  # fmt: skip
    "peak-day-range": (
        peak_day_range,
        "The answer is a date. Drawn only where the maximum is not tied, so there is one right day.",
    ),  # fmt: skip
    "volume-change": (
        volume_change,
        "Two values and arithmetic on them, in SQL. The question says whether the change is absolute or in percent; catches the other one, and a sign error.",
    ),  # fmt: skip
    "fees": (
        fees,
        "The fee is stored in hundredths of a basis point; the mart already has the dollar estimate. Catches a model that recomputes it with the wrong unit.",
    ),  # fmt: skip
    "share": (
        share,
        "A part over a whole, in percent, or the whole without a part. Catches a wrong denominator and gross taken for net.",
    ),  # fmt: skip
}


def draw(seed: int) -> list[Spec]:
    """All template cases, without answers. The same seed gives the same cases."""
    facts = Facts()
    specs = []
    for family, (make, notes) in FAMILIES.items():
        rng = random.Random(f"{seed}:{family}")  # noqa: S311 - a reproducible draw, not security
        seen: set[str] = set()
        while len(seen) < CASES_PER_FAMILY:
            i = len(seen)
            params, question, answer_type, unit, tolerance, sql, unique = make(facts, rng, i)
            if sql in seen:
                continue  # the same parameters again: draw another
            seen.add(sql)
            specs.append(
                Spec(
                    id=f"t-{family}-{i + 1:03d}",
                    question=question,
                    kind="template",
                    family=family,
                    answer_type=answer_type,
                    unit=unit,
                    reference_sql=sql,
                    notes=notes,
                    tolerance=tolerance,
                    unique_sql=unique,
                    params=params,
                )
            )
    return specs
