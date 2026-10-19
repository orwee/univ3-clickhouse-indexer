"""The template cases of golden set v2: ten families, ten cases each, harder than v1's.

Golden set v1 (`golden_templates.py`) is easy for the agent: about 97% right, so no change to
the agent can be measured on it. v2 is made harder in the ways the data allows, and not by
trickery: partial days, pool-days without a row (where the right answer is 0 and a refusal is
wrong), the units of the fee, a pool whose first token is not the one a question names first,
gross against net volume, and questions that need a join or two sums.

The shape is the one of v1: `draw(seed)` needs no server, reads the committed fixture files,
and returns cases WITHOUT answers: a question and the query that answers it. The answers are
computed later, by running each query on the fixture in a throw-away database. No answer is
written here. The helpers (`Facts`, `lit`, `said`, the range draws) are v1's, imported, so that
the two sets read the fixture in the same way.

What the draws respect, and tests/test_golden_v2.py checks:
- the ranges of `ranges-edges` are the only ones that name the partial days, and the cases of
  `partial-day` and `absent-poolday` are the only ones that ask about one day on purpose;
  every other family stays on complete days;
- a question whose answer is a pool is only drawn where the maximum is not tied;
- a tolerance with an absolute bound is only given where that bound is at most a tenth of a
  percent of the value (the amounts of the small wstETH pools are a few dollars).
"""

from __future__ import annotations

import datetime
import random
from decimal import Decimal
from pathlib import Path

from evalkit import fixture, golden
from evalkit.golden import Spec

_v1 = golden.load_module(Path(__file__).with_name("golden_templates.py"))

DAILY = _v1.DAILY
ROUND_TRIPS = _v1.ROUND_TRIPS
FIRST_DAY = datetime.date(2026, 8, 9)  # the first and the last day of the data: partial
LAST_DAY = datetime.date(2026, 9, 25)
FIRST_COMPLETE_DAY = _v1.FIRST_COMPLETE_DAY
LAST_COMPLETE_DAY = _v1.LAST_COMPLETE_DAY
CASES_PER_FAMILY = 10
DEFAULT_SEED = 20261019
lit, said, long_date = _v1.lit, _v1.said, _v1.long_date
_between, _pair_filter, _in_list = _v1._between, _v1._pair_filter, _v1._in_list  # noqa: SLF001

STABLE = _v1.STABLE
ZERO = Decimal(0)


class Facts(_v1.Facts):
    """v1's facts, and the columns v2 needs to tell a small amount from a large one."""

    def __init__(self):
        super().__init__()
        self.cols = {}
        for table in (DAILY, ROUND_TRIPS):
            data = fixture.read_table(table)
            column = data.columns.index
            for row in data.rows:
                key = (row[column("pool_label")], datetime.date.fromisoformat(row[column("block_date")]))  # fmt: skip
                entry = self.cols.setdefault(key, {})
                for field in data.columns:
                    if field in ("pool_address", "block_date", "pool_label"):
                        continue
                    value = row[column(field)]
                    entry[field] = None if value is None else Decimal(value)

    def total(self, labels, start, end, field) -> Decimal:
        """Sum of one column over the pool-days that exist; a day with no row adds 0."""
        value = ZERO
        for label in labels:
            day = start
            while day <= end:
                entry = self.cols.get((label, day))
                if entry is not None and entry.get(field) is not None:
                    value += entry[field]
                day += datetime.timedelta(days=1)
        return value

    def edge_days(self, label: str) -> list[datetime.date]:
        return [day for day in (FIRST_DAY, LAST_DAY) if self.has(label, day)]

    def absent(self) -> list[tuple[str, datetime.date]]:
        days = [FIRST_DAY + datetime.timedelta(days=k) for k in range((LAST_DAY - FIRST_DAY).days + 1)]  # fmt: skip
        return [(label, day) for label in self.labels for day in days if not self.has(label, day)]


def money(value: Decimal | None) -> str | dict:
    """The tolerance of an amount in dollars, given what it is about to be.

    v1's `sum` has a cent of absolute bound. That is at most a tenth of a percent only from
    10 dollars up, and two of the four pools trade a few dollars a day: below 10 the bound is
    relative only. An exact zero is exact.
    """
    if value is None or value == 0:
        return "count"
    return "sum" if abs(value) >= 10 else {"abs": "0", "rel": "0.001"}


def _days(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    return [start + datetime.timedelta(days=k) for k in range((end - start).days + 1)]


def _wording(options: list[str], i: int) -> str:
    return options[i % len(options)]


# --- the ten families ---------------------------------------------------------------------
# Each takes the facts, a random generator and the index of the case within the family, and
# returns (params, question, answer_type, unit, tolerance, reference_sql, unique_sql).

METRICS = {
    "swaps": ("swaps", "swaps", "count"),
    "volume_usd": ("dollar volume", "USD", None),
    "fees_usd": ("estimated fees", "USD", None),
}


def partial_day(f: Facts, rng: random.Random, i: int):
    """One metric of one pool on the first or the last day of the data."""
    label = rng.choice([label for label in f.labels if f.edge_days(label)])
    day = rng.choice(f.edge_days(label))
    metric = rng.choice(list(METRICS))
    what, unit, fixed = METRICS[metric]
    wording = {
        "swaps": [
            "How many swaps does the data record for the {label} pool on {day}? Answer with a number.",
            "Count the swaps of {label} on {day}, as far as the data goes.",
        ],
        "volume_usd": [
            "What is the dollar volume of the {label} pool on {day}, according to the data? Answer in US dollars.",
            "How many USD were traded in {label} on {day}, as far as the data goes?",
        ],
        "fees_usd": [
            "What are the estimated fees, in US dollars, of the {label} pool on {day}, according to the data?",
            "How many USD in fees does the data estimate for {label} on {day}?",
        ],
    }[metric]  # fmt: skip
    sql = f"SELECT {metric} FROM {DAILY} WHERE pool_label = {lit(label)} AND block_date = {lit(day.isoformat())}"  # fmt: skip
    value = f.cols[(label, day)][metric]
    question = _wording(wording, i // 3).format(label=label, day=said(day, i))
    return {"label": label, "day": day, "metric": metric}, question, "number", unit, fixed or money(value), sql, None  # fmt: skip


def absent_poolday(f: Facts, rng: random.Random, i: int):
    """A pool on a day it has no row for: nothing happened, and the answer is 0."""
    label, day = rng.choice(f.absent())
    metric = rng.choice(list(METRICS))
    wording = {
        "swaps": [
            "How many swaps did the {label} pool have on {day}?",
            "Count the swaps in {label} on {day}.",
        ],
        "volume_usd": [
            "What was the dollar volume of the {label} pool on {day}? Answer in US dollars.",
            "How many USD were traded in {label} on {day}?",
        ],
        "fees_usd": [
            "What were the estimated fees, in US dollars, of the {label} pool on {day}?",
            "How many USD in fees did {label} earn on {day}, as estimated from its volume?",
        ],
    }[metric]  # fmt: skip
    unit = METRICS[metric][1]
    sql = f"SELECT ifNull(sum({metric}), 0) FROM {DAILY} WHERE pool_label = {lit(label)} AND block_date = {lit(day.isoformat())}"  # fmt: skip
    question = _wording(wording, i // 3).format(label=label, day=said(day, i))
    return {"label": label, "day": day, "metric": metric}, question, "number", unit, "count", sql, None  # fmt: skip


def fee_units(f: Facts, rng: random.Random, i: int):
    """The fee of a pool in the unit the question names: the column is in hundredths of a basis point."""
    label = rng.choice(f.labels)
    unit_name = rng.choice(("hundredths", "bp", "percent", "fraction"))
    where = f"pool_label = {lit(label)}"
    if unit_name == "hundredths":
        wording = [
            "What is the fee of the {label} pool in hundredths of a basis point (the unit Uniswap v3 stores it in)? Answer with the integer.",
            "Uniswap v3 stores a pool's fee in hundredths of a basis point. What is that number for {label}?",
        ]  # fmt: skip
        sql, unit, tolerance = f"SELECT fee FROM dim_pools WHERE {where}", "hundredths of a basis point", "count"  # fmt: skip
    elif unit_name == "bp":
        wording = [
            "What is the fee of the {label} pool in basis points?",
            "Express the fee tier of {label} in basis points (1 basis point is 0.01%).",
        ]  # fmt: skip
        sql, unit, tolerance = f"SELECT fee / 100 FROM dim_pools WHERE {where}", "basis points", "ratio"  # fmt: skip
    elif unit_name == "percent":
        wording = [
            "What percent of the amount traded does a swap in the {label} pool pay as fee? Answer in percent.",
            "Give the fee of {label} as a percentage of the traded amount.",
        ]  # fmt: skip
        sql, unit, tolerance = f"SELECT fee_percent FROM dim_pools WHERE {where}", "percent", "ratio"  # fmt: skip
    else:
        wording = [
            "What fraction of the amount traded is the fee in the {label} pool? Answer as a decimal fraction, for example 0.01 for one percent.",
            "As a decimal fraction of the traded amount (not a percent), what is the fee of {label}?",
        ]  # fmt: skip
        sql, unit, tolerance = f"SELECT fee_fraction FROM dim_pools WHERE {where}", "fraction", "ratio"  # fmt: skip
    question = _wording(wording, i // 4).format(label=label)
    return {"label": label, "unit": unit_name}, question, "number", unit, tolerance, sql, None


def token_direction(f: Facts, rng: random.Random, i: int):
    """Token amounts where token0 is USDC in one family of pools and wstETH in the other."""
    if i % 2 == 0:
        label = rng.choice(f.labels)
        day = rng.choice(f.days_of(label))
        token0, token1 = f.pair_of(label)
        stable, other = (token0, token1) if token0 in STABLE else (token1, token0)
        wording = [
            "On {day}, how many {other} did one {stable} buy in the {label} pool, on average weighted by volume? Answer in {other} per {stable}.",
            "In {label} on {day}, what was the volume-weighted number of {other} per {stable}: the {other} volume divided by the {stable} volume?",
        ]  # fmt: skip
        sql = (
            f"SELECT if(p.token0 IN ({_in_list(list(STABLE))}), "
            "d.volume_token1 / d.volume_token0, d.volume_token0 / d.volume_token1) AS inverse "
            f"FROM {DAILY} AS d INNER JOIN dim_pools AS p ON p.pool_address = d.pool_address "
            f"WHERE d.pool_label = {lit(label)} AND d.block_date = {lit(day.isoformat())}"
        )
        question = _wording(wording, i // 2).format(other=other, stable=stable, label=label, day=said(day, i))  # fmt: skip
        return {"label": label, "day": day}, question, "number", f"{other} per {stable}", "ratio", sql, None  # fmt: skip
    pair = rng.choice(sorted({f.pair_of(label) for label in f.labels}))
    token = rng.choice(pair)
    start, end = _v1._range(f, rng, None, 3, 21)  # noqa: SLF001
    labels = f.labels_of_pair(pair)
    wording = [
        "How much {token} was traded in total in the two {a_}/{b_} pools together from {a} to {b}, both days included? Answer in {token}, not in dollars.",
        "Across both fee tiers of the {a_}/{b_} pair, what was the volume of {token}, in units of {token}, between {a} and {b} inclusive?",
    ]  # fmt: skip
    sql = (
        f"SELECT sum(if(p.token0 = {lit(token)}, d.volume_token0, d.volume_token1)) "
        f"FROM {DAILY} AS d INNER JOIN dim_pools AS p ON p.pool_address = d.pool_address "
        f"WHERE {_pair_filter(pair).replace('pool_address', 'd.pool_address', 1)} AND {_between(start, end, 'd.block_date')}"  # fmt: skip
    )
    question = _wording(wording, i // 2).format(token=token, a_=pair[0], b_=pair[1], a=said(start, i), b=said(end, i))  # fmt: skip
    return {"labels": labels, "start": start, "end": end, "token": token}, question, "number", token, "quantity", sql, None  # fmt: skip


def gross_net(f: Facts, rng: random.Random, i: int):
    """Gross against net volume, round trips and their share, over a range of days."""
    variant = i % 5
    needs = ("net_volume_usd", "round_trip_volume_usd", "round_trips", "round_trip_volume_usd", "round_trip_swaps")[variant]  # fmt: skip
    while True:  # a range in which there is something to count: no answer of 0 by chance
        label = rng.choice(f.labels)
        start, end = _v1._range(f, rng, label, 3, 28)  # noqa: SLF001
        if f.total([label], start, end, needs) > 0:
            break
    a, b = said(start, i), said(end, i)
    where = f"pool_label = {lit(label)} AND {_between(start, end)}"
    params = {"label": label, "start": start, "end": end}
    if variant == 0:
        question = f"What was the net dollar volume of the {label} pool from {a} to {b}, both days included, that is, the volume excluding round trips? Answer in US dollars."  # fmt: skip
        sql, unit = f"SELECT sum(net_volume_usd) FROM {ROUND_TRIPS} WHERE {where}", "USD"
        tolerance = money(f.total([label], start, end, "net_volume_usd"))
    elif variant == 1:
        question = f"How many US dollars of the {label} pool's volume between {a} and {b} inclusive were round trips?"  # fmt: skip
        sql, unit = f"SELECT sum(round_trip_volume_usd) FROM {ROUND_TRIPS} WHERE {where}", "USD"
        tolerance = money(f.total([label], start, end, "round_trip_volume_usd"))
    elif variant == 2:
        question = f"How many round trips did the {label} pool have from {a} to {b}, both days included? Count round trips, not the swaps in them."  # fmt: skip
        sql, unit, tolerance = f"SELECT sum(round_trips) FROM {ROUND_TRIPS} WHERE {where}", "round trips", "count"  # fmt: skip
    elif variant == 3:
        question = f"By how many US dollars does the gross volume of {label} exceed its net volume (volume without round trips) over {a} to {b}, both included?"  # fmt: skip
        sql = f"SELECT sum(volume_usd) - sum(net_volume_usd) FROM {ROUND_TRIPS} WHERE {where}"
        unit = "USD"
        tolerance = money(
            f.total([label], start, end, "volume_usd")
            - f.total([label], start, end, "net_volume_usd")  # fmt: skip
        )
    else:
        question = f"Over {a} to {b}, both days included, what percent of the swaps of the {label} pool were part of a round trip? Answer in percent of the swaps of the whole period."  # fmt: skip
        sql = f"SELECT 100 * sum(round_trip_swaps) / sum(swaps) FROM {ROUND_TRIPS} WHERE {where}"
        unit, tolerance = "percent", "ratio"
    return params, question, "number", unit, tolerance, sql, None


def days_above(f: Facts, rng: random.Random, i: int):
    """On how many days of a range did a pool pass a threshold: a filter, then a count."""
    label = rng.choice(f.labels)
    start, end = _v1._range(f, rng, label, 10, 30)  # noqa: SLF001
    metric = ("volume_usd", "swaps")[i % 2]
    values = sorted(f.rows[(label, day)][metric] for day in _days(start, end))
    median = values[len(values) // 2]
    magnitude = 10 ** max(len(str(int(median))) - 2, 0)
    threshold = (int(median) // magnitude) * magnitude or 1
    while int(threshold) in {int(v) for v in values}:
        threshold += 1
    what = "dollar volume" if metric == "volume_usd" else "swaps"
    unit = "days"
    over = "more than {t:,} US dollars of volume" if metric == "volume_usd" else "more than {t:,} swaps"  # fmt: skip
    wording = [
        "On how many days from {a} to {b}, both included, did the {label} pool have " + over + "?",
        "Count the days between {a} and {b} inclusive on which {label} had " + over + ".",
    ]  # fmt: skip
    sql = f"SELECT countIf({metric} > {threshold}) FROM {DAILY} WHERE pool_label = {lit(label)} AND {_between(start, end)}"  # fmt: skip
    question = _wording(wording, i // 2).format(label=label, a=said(start, i), b=said(end, i), t=threshold)  # fmt: skip
    return {"label": label, "start": start, "end": end, "metric": metric, "what": what}, question, "number", unit, "count", sql, None  # fmt: skip


def pool_ratio(f: Facts, rng: random.Random, i: int):
    """How many times larger one pool is than another over a range: two sums, one division."""
    first, second = rng.sample(f.labels, 2)
    start, end = _v1._range(f, rng, None, 5, 30)  # noqa: SLF001
    metric = ("volume_usd", "swaps")[i % 2]
    what = "dollar volume" if metric == "volume_usd" else "number of swaps"
    wording = [
        "Between {a} and {b}, both included, how many times larger was the {what} of {first} than that of {second}? Answer as a ratio.",
        "Over {a} to {b} inclusive, divide the total {what} of {first} by the total {what} of {second}. What is the ratio?",
    ]  # fmt: skip
    sql = (
        f"SELECT sumIf({metric}, pool_label = {lit(first)}) / sumIf({metric}, pool_label = {lit(second)}) "
        f"FROM {DAILY} WHERE {_between(start, end)}"
    )
    question = _wording(wording, i // 2).format(first=first, second=second, what=what, a=said(start, i), b=said(end, i))  # fmt: skip
    return {"labels": [first, second], "start": start, "end": end, "metric": metric}, question, "number", "ratio", "ratio", sql, None  # fmt: skip


def average(f: Facts, rng: random.Random, i: int):
    """An average: per day, or per swap, where the weighted and the unweighted differ."""
    label = rng.choice(f.labels)
    start, end = _v1._range(f, rng, label, 7, 30)  # noqa: SLF001
    where = f"pool_label = {lit(label)} AND {_between(start, end)}"
    a, b = said(start, i), said(end, i)
    variant = i % 3
    params = {"label": label, "start": start, "end": end, "variant": variant}
    if variant == 0:
        question = f"What was the average daily dollar volume of the {label} pool from {a} to {b}, both days included? Answer in US dollars per day."  # fmt: skip
        sql, unit = f"SELECT sum(volume_usd) / count() FROM {DAILY} WHERE {where}", "USD per day"
        tolerance = money(f.total([label], start, end, "volume_usd") / len(_days(start, end)))
    elif variant == 1:
        question = f"On average, how many swaps per day did the {label} pool have between {a} and {b} inclusive?"  # fmt: skip
        sql, unit, tolerance = f"SELECT sum(swaps) / count() FROM {DAILY} WHERE {where}", "swaps per day", "ratio"  # fmt: skip
    else:
        question = f"What was the average size of a swap in the {label} pool from {a} to {b}, both days included: the total dollar volume of the period divided by its total number of swaps? Answer in US dollars per swap."  # fmt: skip
        sql, unit, tolerance = f"SELECT sum(volume_usd) / sum(swaps) FROM {DAILY} WHERE {where}", "USD per swap", "ratio"  # fmt: skip
    return params, question, "number", unit, tolerance, sql, None


def ranges_edges(f: Facts, rng: random.Random, i: int):
    """Ranges that reach the first or the last day of the data, which hold part of a day."""
    variant = i % 5
    if variant == 0:  # all pools, from a day until the end of the data
        start = rng.choice(_days(datetime.date(2026, 9, 15), datetime.date(2026, 9, 23)))
        end = LAST_DAY
        question = f"How many swaps did all the pools together have from {said(start, i)} until the end of the data (2026-09-25), both ends included?"  # fmt: skip
        sql = f"SELECT sum(swaps) FROM {DAILY} WHERE {_between(start, end)}"
        return {"labels": f.labels, "start": start, "end": end}, question, "number", "swaps", "count", sql, None  # fmt: skip
    if variant == 1:  # all pools, from the start of the data
        end = rng.choice(_days(datetime.date(2026, 8, 12), datetime.date(2026, 8, 25)))
        question = f"What was the combined dollar volume of all the pools from the first day of the data (2026-08-09) to {said(end, i)}, both included? Answer in US dollars."  # fmt: skip
        sql = f"SELECT sum(volume_usd) FROM {DAILY} WHERE {_between(FIRST_DAY, end)}"
        value = f.total(f.labels, FIRST_DAY, end, "volume_usd")
        return {"labels": f.labels, "start": FIRST_DAY, "end": end}, question, "number", "USD", money(value), sql, None  # fmt: skip
    if variant == 2:  # one pool that has the last day
        label = rng.choice([label for label in f.labels if f.has(label, LAST_DAY)])
        start = rng.choice(_days(datetime.date(2026, 9, 10), datetime.date(2026, 9, 23)))
        question = f"What was the dollar volume of the {label} pool from {said(start, i)} through 2026-09-25, the last day of the data? Answer in US dollars."  # fmt: skip
        sql = f"SELECT sum(volume_usd) FROM {DAILY} WHERE pool_label = {lit(label)} AND {_between(start, LAST_DAY)}"  # fmt: skip
        value = f.total([label], start, LAST_DAY, "volume_usd")
        return {"label": label, "start": start, "end": LAST_DAY}, question, "number", "USD", money(value), sql, None  # fmt: skip
    if variant == 3:  # the whole period, one pool
        label = rng.choice(f.labels)
        question = f"What is the total number of swaps of the {label} pool over the whole period the data covers?"  # fmt: skip
        sql = f"SELECT sum(swaps) FROM {DAILY} WHERE pool_label = {lit(label)}"
        return {"label": label, "start": FIRST_DAY, "end": LAST_DAY}, question, "number", "swaps", "count", sql, None  # fmt: skip
    pair = rng.choice(sorted({f.pair_of(label) for label in f.labels}))  # a pair, the whole period
    labels = f.labels_of_pair(pair)
    question = f"What are the total estimated fees, in US dollars, of the two {pair[0]}/{pair[1]} pools together over the whole period the data covers?"  # fmt: skip
    sql = f"SELECT sum(fees_usd) FROM {DAILY} WHERE {_pair_filter(pair)}"
    value = f.total(labels, FIRST_DAY, LAST_DAY, "fees_usd")
    return {"labels": labels, "start": FIRST_DAY, "end": LAST_DAY}, question, "number", "USD", money(value), sql, None  # fmt: skip


def top_range(f: Facts, rng: random.Random, i: int):
    """Which pool had the most of something over a range: a sum per pool, then a maximum."""
    metric, what = (
        ("fees_usd", "estimated fees"),
        ("volume_usd", "dollar volume"),
        ("swaps", "swaps"),
        ("volume_usd / swaps", "the largest average swap, in dollars (total volume over total swaps)"),
    )[i % 4]  # fmt: skip
    pairs = sorted({f.pair_of(label) for label in f.labels})
    while True:
        pair = rng.choice([None, *pairs])
        labels = f.labels if pair is None else f.labels_of_pair(pair)
        start, end = _v1._range(f, rng, None, 4, 30)  # noqa: SLF001
        scope = "" if pair is None else f" AND {_pair_filter(pair)}"
        if metric == "volume_usd / swaps":
            per_pool = "sum(volume_usd) / sum(swaps)"
        else:
            per_pool = f"sum({metric})"
        grouped = f"SELECT pool_label, {per_pool} AS total FROM {DAILY} WHERE {_between(start, end)}{scope} GROUP BY pool_label"  # fmt: skip
        sql = f"SELECT pool_label FROM ({grouped}) ORDER BY total DESC LIMIT 1"
        unique = f"SELECT count() FROM ({grouped}) WHERE total = (SELECT max(total) FROM ({grouped}))"  # fmt: skip
        if metric != "volume_usd / swaps":
            totals = sorted((f.total([label], start, end, metric) for label in labels), reverse=True)  # fmt: skip
            if totals[0] == totals[1]:
                continue
        break
    among = "Of all the pools" if pair is None else f"Of the two {pair[0]}/{pair[1]} pools"
    if metric == "volume_usd / swaps":
        wording = [
            "{among}, which one had the largest average swap, in dollars (total volume over total swaps), from {a} to {b}, both included? Answer with the pool's label.",
            "{among}, name the pool with the highest average dollar size per swap between {a} and {b} inclusive.",
        ]  # fmt: skip
    else:
        wording = [
            "{among}, which pool had the most {what} from {a} to {b}, both days included? Answer with the pool's label.",
            "{among}, name the pool with the highest total {what} between {a} and {b} inclusive.",
        ]  # fmt: skip
    question = _wording(wording, i // 4).format(among=among, what=what, a=said(start, i), b=said(end, i))  # fmt: skip
    return {"labels": labels, "start": start, "end": end, "metric": metric}, question, "label", None, None, sql, unique  # fmt: skip


FAMILIES = {
    "partial-day": (
        partial_day,
        "The first and the last day of the data hold only part of a day, and the question does not say so. The right answer is the figure the data holds for that day, possibly with a caveat; a refusal is wrong, and so is a figure from another day.",
    ),  # fmt: skip
    "absent-poolday": (
        absent_poolday,
        "The pool has no row on that day because it had no swap. The right answer is 0, not a refusal and not a guess. A model that reads 'no row' as 'no data' refuses. Wrong answer: a refusal, or any number other than 0.",
    ),  # fmt: skip
    "fee-units": (
        fee_units,
        "The fee column is in hundredths of a basis point, so 500 is 0.05%, 5 basis points and 0.0005. Catches a unit that is off by a factor of 100 or 10,000.",
    ),  # fmt: skip
    "token-direction": (
        token_direction,
        "token0 is USDC in the USDC/WETH pools and wstETH in the wstETH/USDC pools, so the same word in a question is a different column in each family. Catches a column picked by position, and a price taken upside down.",
    ),  # fmt: skip
    "gross-net": (
        gross_net,
        "Gross volume counts every swap; net volume leaves out the round trips. The question says which. Catches the wrong table, and a share taken over the wrong denominator.",
    ),  # fmt: skip
    "days-above": (
        days_above,
        "A filter on a daily value, then a count of days. Catches a sum in place of a count, and an end of the range left out.",
    ),  # fmt: skip
    "pool-ratio": (
        pool_ratio,
        "Two sums over the same days and a division, in one query or two. Catches a ratio of the wrong order and a ratio of averages taken in place of a ratio of sums.",
    ),  # fmt: skip
    "average": (
        average,
        "An average per day or per swap. The average swap size is total volume over total swaps, which is not the mean of the daily averages. Catches the unweighted mean.",
    ),  # fmt: skip
    "ranges-edges": (
        ranges_edges,
        "A range that reaches the first or the last day of the data, which hold part of a day. The right answer includes them; the data holds what it holds. Catches a model that drops the edge days or refuses because they are partial.",
    ),  # fmt: skip
    "top-range": (
        top_range,
        "A sum per pool, then a maximum over pools. The answer is a label, drawn only where the maximum is not tied. The average-swap variant is a ratio of sums, and the pool with the most volume is rarely the pool with the largest swaps.",
    ),  # fmt: skip
}


def draw(seed: int) -> list[Spec]:
    """All template cases of v2, without answers. The same seed gives the same cases."""
    facts = Facts()
    specs = []
    for family, (make, notes) in FAMILIES.items():
        rng = random.Random(f"{seed}:v2:{family}")  # noqa: S311 - a reproducible draw
        seen: set[str] = set()
        attempts = 0
        while len(seen) < CASES_PER_FAMILY:
            attempts += 1
            if attempts > 2000:
                raise RuntimeError(f"{family}: could not draw {CASES_PER_FAMILY} different cases")
            i = len(seen)
            params, question, answer_type, unit, tolerance, sql, unique = make(facts, rng, i)
            if sql in seen:
                continue  # the same parameters again: draw another
            seen.add(sql)
            specs.append(
                Spec(
                    id=f"v2-t-{family}-{i + 1:03d}",
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
