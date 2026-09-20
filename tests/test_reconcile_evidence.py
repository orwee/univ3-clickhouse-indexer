"""Round three of the evidence: displaced swaps, round trips in a block, hourly candles.

The swaps are planted by hand in a throw-away database, so every expected number is known.
"""

import datetime
import json

import pytest

from univ3_indexer import clickhouse as ch
from univ3_indexer import external, loader, reconcile
from univ3_indexer.pools import load_pools

from .test_external import FakeResponse, FakeSession, client
from .test_reconcile import pool_day, synthetic

UTC = datetime.UTC
POOL = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"  # USDC/WETH 0.05%: token0 is USDC, 6 decimals
DAY = datetime.date(2026, 9, 1)
NORMAL_TICK, PUSHED_TICK = 198_000, 190_000
SANDWICHER, VICTIM, OTHERS = b"\x01" * 20, b"\x02" * 20, b"\x03" * 20


def swap(n, usdc, end_tick, exec_tick, who, tx, minute=0, block=None):
    """One raw_swaps row. `usdc` > 0: the pool receives USDC. The WETH leg is what the price
    at `exec_tick` gives, so a swap executed at the going price is worth the same either way."""
    weth = int(abs(usdc) * 1e6 * 1.0001**exec_tick)
    when = datetime.datetime.combine(DAY, datetime.time(12, minute), tzinfo=UTC)
    return [POOL, block or 1000 + n, when, bytes([tx]) * 32, n, who, who, int(usdc * 1e6),
            -weth if usdc > 0 else weth, 2**96, 10**18, end_tick]  # fmt: skip


def planted():
    before = [swap(i, 1_000, NORMAL_TICK, NORMAL_TICK, OTHERS, 10 + i) for i in range(30)]
    push = swap(
        30, 1_000_000, PUSHED_TICK, (NORMAL_TICK + PUSHED_TICK) // 2, SANDWICHER, 100, 1, 5000
    )
    victim = swap(31, 2_000, PUSHED_TICK, PUSHED_TICK, VICTIM, 101, 1, 5000)
    back = swap(
        32, -1_000_500, NORMAL_TICK, (NORMAL_TICK + PUSHED_TICK) // 2, SANDWICHER, 102, 1, 5000
    )
    after = [swap(40 + i, 1_000, NORMAL_TICK, NORMAL_TICK, OTHERS, 150 + i, 2) for i in range(30)]
    return before + [push, victim, back] + after


@pytest.fixture
def database(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database)
    clickhouse.insert(ch.qualified(temp_database), planted(), column_names=loader.COLUMNS)
    return temp_database


def parameters():
    return reconcile.stable_leg_parameters(load_pools(), reconcile.stablecoin_symbols())


# --- displaced swaps --------------------------------------------------------------------------


def test_the_push_the_victim_and_the_way_back_are_displaced_and_nothing_else(clickhouse, database):
    ((key, row),) = reconcile.displaced_by_pool_day(clickhouse, database, parameters()).items()
    assert key == (POOL, DAY) and row["swaps"] == 63
    index = reconcile.DISPLACEMENT_SENSITIVITY.index(reconcile.DISPLACEMENT_TICKS)
    assert row["displaced_swaps"][index] == 3
    assert row["displaced_usd"][index] == pytest.approx(1_000_000 + 2_000 + 1_000_500)
    assert row["volume_usd"] == pytest.approx(60 * 1_000 + 2_002_500)
    beyond_all = row["displaced_swaps"][-1]
    assert beyond_all == 3, "8,000 ticks away is beyond every threshold reported"


def test_a_swap_at_the_going_price_is_worth_the_same_either_way_and_a_displaced_one_is_not(
    clickhouse, database
):
    ((_, row),) = reconcile.displaced_by_pool_day(clickhouse, database, parameters()).items()
    normal_and_displaced = row["volume_usd_at_reference"]
    # 60 normal swaps: equal. The three displaced ones, executed ~4,000 to 8,000 ticks below the
    # reference, moved less WETH per USDC than the going price: worth less at the reference.
    assert normal_and_displaced < row["volume_usd"]
    expected = 60 * 1_000 + (1_000_000 + 1_000_500) * 1.0001**-4000 + 2_000 * 1.0001**-8000
    assert normal_and_displaced == pytest.approx(expected, rel=1e-6)


def test_the_distribution_is_what_the_threshold_is_read_from(clickhouse, database):
    (row,) = reconcile._rows(clickhouse, database, "15_evidence_displacement_distribution.sql",
                             {"thresholds": [100, 10_000]})  # fmt: skip
    assert row["swaps"] == 63 and row["beyond"] == [3, 0] and row["largest"] == 8_000
    assert row["quantiles"][0] == 0, "the median swap sits on the reference"


# --- round trips ------------------------------------------------------------------------------


def test_the_round_trip_is_found_with_the_victim_between_its_legs(clickhouse, database):
    (pair,) = reconcile._rows(clickhouse, database, "16_evidence_round_trips.sql",
                              {**parameters(), "pool": POOL, "day": DAY})  # fmt: skip
    assert (pair["first_log_index"], pair["second_log_index"]) == (30, 32)
    assert not pair["same_transaction"] and pair["sender_is_recipient"]
    assert pair["sender_address"] == "0x" + "01" * 20
    assert pair["swaps_of_others_between"] == 1
    assert (pair["first_usd"], pair["second_usd"]) == (1_000_000, 1_000_500)
    assert pair["net_stable_paid_to_pool"] == pytest.approx(-500)
    assert (pair["first_tick_before"], pair["first_tick_after"], pair["second_tick_after"]) == (
        NORMAL_TICK, PUSHED_TICK, NORMAL_TICK)  # fmt: skip


def test_two_swaps_in_the_same_direction_are_not_a_round_trip(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database)
    rows = [swap(1, 500, NORMAL_TICK, NORMAL_TICK, SANDWICHER, 1, block=7),
            swap(2, 500, NORMAL_TICK, NORMAL_TICK, SANDWICHER, 2, block=7)]  # fmt: skip
    clickhouse.insert(ch.qualified(temp_database), rows, column_names=loader.COLUMNS)
    assert reconcile._rows(clickhouse, temp_database, "16_evidence_round_trips.sql",
                           {**parameters(), "pool": POOL, "day": DAY}) == []  # fmt: skip


# --- the what-if can fail in both directions ------------------------------------------------------


def test_what_if_counts_what_it_fixes_and_what_it_breaks():
    too_high = pool_day("2026-09-01", 103_000_000, 100_000_000)  # +3%
    too_low = pool_day("2026-09-02", 97_000_000, 100_000_000)  # -3%
    fine = pool_day("2026-09-03", 100_100_000, 100_000_000)  # +0.1%
    result = synthetic([too_high, too_low, fine])
    key = lambda r: (r["pool_address"], r["date"])  # noqa: E731
    lower_everything = {key(r): r["our_volume_usd"] - 3_000_000 for r in (too_high, too_low, fine)}
    assert reconcile.what_if(result, lower_everything) == {
        "positive": 1, "fixed_positive": 1, "negative": 1, "fixed_negative": 0,
        "inside": 1, "broken": 1}  # fmt: skip
    nothing = {key(r): r["our_volume_usd"] for r in (too_high, too_low, fine)}
    outcome = reconcile.what_if(result, nothing)
    assert (outcome["fixed_positive"], outcome["fixed_negative"], outcome["broken"]) == (0, 0, 0)


def test_pearson():
    assert reconcile._pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert reconcile._pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert reconcile._pearson([1, 2, 3], [5, 5, 5]) is None, "no variance, no correlation"
    assert reconcile._pearson([1, 2], [1, 2]) is None, "two points always line up"


# --- hourly candles -----------------------------------------------------------------------------

HOUR = 1_788_264_000  # 2026-09-01 12:00:00 UTC
assert HOUR % 3600 == 0


def hourly_body(*candles):
    return json.dumps({"data": {"attributes": {"ohlcv_list": [list(c) for c in candles]}}})


def test_hourly_candles_are_parsed_oldest_first_and_a_repeat_is_kept_once():
    body = hourly_body(
        (HOUR + 3600, 1, 1, 1, 1, 20.0), (HOUR, 1, 1, 1, 1, 10.0), (HOUR, 2, 2, 2, 2, 10.0)
    )
    rows = external.parse_hourly(POOL, body)
    assert [v for _, v in rows] == [10.0, 20.0]
    assert rows[0][0] == datetime.datetime.fromtimestamp(HOUR, UTC)


@pytest.mark.parametrize("body", [
    hourly_body((HOUR, 1, 1, 1, 1, 10.0), (HOUR, 1, 1, 1, 1, 11.0)),  # two different candles
    hourly_body((HOUR + 60, 1, 1, 1, 1, 10.0)),  # not on the hour
    hourly_body((HOUR, 1, 1)), "{}", "nope"])  # fmt: skip
def test_hourly_responses_that_cannot_be_trusted_are_refused(body):
    with pytest.raises(external.ExternalSourceError):
        external.parse_hourly(POOL, body)


def test_the_hourly_request_goes_to_the_hour_timeframe_of_a_pool_of_pools_yml():
    session = FakeSession(FakeResponse(200, hourly_body()))
    client(session)[0].ohlcv_raw(POOL, "hour")
    assert session.calls[0]["url"].endswith(f"/pools/{POOL}/ohlcv/hour")
    with pytest.raises(ValueError, match="timeframe"):
        client(FakeSession())[0].ohlcv_raw(POOL, "minute")


def test_the_hourly_comparison_places_the_difference_in_its_hour(clickhouse, database):
    ch.apply_ddl(clickhouse, database, external.HOURLY_DDL)
    noon = datetime.datetime.combine(DAY, datetime.time(12), tzinfo=UTC)
    fetched = datetime.datetime(2026, 9, 3, tzinfo=UTC)
    clickhouse.insert(ch.qualified(database, external.HOURLY_TABLE),
                      [[external.SOURCE, POOL, noon, 2_000_000.0, fetched],
                       [external.SOURCE, POOL, noon + datetime.timedelta(hours=1), 50.0, fetched]],
                      column_names=external.HOURLY_COLUMNS)  # fmt: skip
    asked = {**parameters(), "pool": POOL, "day": DAY, "source": external.SOURCE}
    hours = reconcile._rows(clickhouse, database, "17_evidence_hourly.sql", asked)
    by_hour = {h["hour_of_day"]: h for h in hours}
    assert by_hour[12]["our_usd"] == pytest.approx(2_062_500)
    assert by_hour[12]["diff_usd"] == pytest.approx(62_500)
    assert by_hour[13]["our_swaps"] == 0 and by_hour[13]["diff_usd"] == pytest.approx(-50)


def test_without_the_hourly_table_the_section_says_so(clickhouse, database):
    result = synthetic([])
    assert reconcile._hourly_by_pool_day(clickhouse, database, result, parameters()) is None
    assert "section skipped" in "\n".join(reconcile._evidence_hourly(result, None))


# --- H2 out of sample: the placebo query, on the planted swaps -------------------------------


def test_the_placebo_revalues_as_many_swaps_as_are_displaced_but_other_ones(clickhouse, database):
    from univ3_indexer import h2_check

    ((key, row),) = h2_check.adjustments(clickhouse, database, parameters(), seed=1).items()
    assert key == (POOL, DAY)
    assert (row["displaced_swaps"], row["placebo_swaps"]) == (3, 3)
    # The three displaced swaps are worth less at the reference; sixty normal ones are worth the
    # same either way, so revaluing three of THEM changes nothing.
    expected = (1_000_000 + 1_000_500) * (1.0001**-4000 - 1) + 2_000 * (1.0001**-8000 - 1)
    assert row["delta_displaced"] == pytest.approx(expected, rel=1e-6)
    assert row["delta_placebo"] == pytest.approx(0, abs=1e-6)
    assert row["delta_all"] == pytest.approx(row["delta_displaced"], rel=1e-9)


def test_the_placebo_is_reproducible_for_a_seed_and_differs_between_seeds(
    clickhouse, temp_database
):
    from univ3_indexer import h2_check

    ch.apply_ddl(clickhouse, temp_database)
    rows = planted()
    # make the normal swaps differ in how far they were executed from the reference, so that
    # WHICH ones the placebo picks shows in the sum
    for i, row in enumerate(rows):
        if row[5] == OTHERS:
            row[8] = int(row[8] * (1 + i / 1000))  # the WETH leg
    clickhouse.insert(ch.qualified(temp_database), rows, column_names=loader.COLUMNS)

    def placebo(seed):
        rows = h2_check.adjustments(clickhouse, temp_database, parameters(), seed=seed)
        return rows[(POOL, DAY)]["delta_placebo"]

    picks = [placebo(seed) for seed in (1, 1, 2, 3, 4)]
    assert picks[0] == picks[1], "same seed, same swaps"
    assert len(set(picks)) > 1, "another seed, other swaps"


def test_the_protocol_constants_are_the_preregistered_ones():
    import datetime as dt

    from univ3_indexer import h2_check

    assert h2_check.HOLD_OUT == (dt.date(2026, 8, 10), dt.date(2026, 8, 19))
    assert h2_check.IN_SAMPLE == (dt.date(2026, 8, 21), dt.date(2026, 9, 19))
    assert h2_check.PLACEBO_SEEDS == list(range(1, 21))
    assert reconcile.DISPLACEMENT_TICKS == 100
    assert (reconcile.DEFAULT_THRESHOLD, reconcile.DEFAULT_ABS_THRESHOLD) == (0.01, 1000.0)
