"""Reconciliation must DETECT: a planted difference in A, one in B, and a missing day."""

import csv
import datetime

import pytest

from univ3_indexer import clickhouse as ch
from univ3_indexer import external, loader, mv, reconcile
from univ3_indexer.pools import Pool, load_pools

from .test_loader import make_landing

FETCHED = datetime.datetime(2026, 9, 20, 0, 0, tzinfo=datetime.UTC)

# The fixture holds two days, both partial on our side, and a few thousand USD. The detection
# tests below were written before the "complete days only" and "absolute threshold" rules
# existed; they keep checking exactly what they checked, by switching both rules off. The two
# rules have their own tests at the end of this file.
EVERY_DAY = {"complete_days_only": False, "abs_threshold": 0.0}
CLI_EVERY_DAY = ["--include-incomplete-days", "--abs-threshold", "0"]


@pytest.fixture
def world(clickhouse, temp_database, tmp_path):
    """Raw swaps loaded THROUGH the materialized view, plus an external table that agrees
    with us exactly: the case that must reconcile."""
    ch.apply_ddl(clickhouse, temp_database)
    mv.create(clickhouse, temp_database)
    make_landing(tmp_path / "landing")
    loader.load(clickhouse, temp_database, tmp_path / "landing", "full")
    ch.apply_ddl(clickhouse, temp_database, external.DDL)
    ours = reconcile.run(clickhouse, temp_database).external
    assert ours and all(r["presence"] == "only_ours" for r in ours)
    rows = [
        external.DailyVolume(r["pool_address"], r["date"], 0, r["our_volume_usd"], 1.0)
        for r in ours
    ]
    external.store(clickhouse, temp_database, rows, FETCHED)
    return temp_database


def revise(clickhouse, database, row, factor):
    newer = external.DailyVolume(
        row["pool_address"], row["date"], 0, row["our_volume_usd"] * factor, 1.0
    )
    external.store(clickhouse, database, [newer], FETCHED + datetime.timedelta(hours=1))


# --- the case that reconciles --------------------------------------------------------------


def test_matching_sources_reconcile_on_both_sides(clickhouse, world, tmp_path):
    result = reconcile.run(clickhouse, world, **EVERY_DAY)
    assert result.internal == [] and result.internal_ok
    assert len(result.both) == len(result.external) > 0
    assert result.over_threshold == [] and result.one_sided == []
    assert all(r["rel_diff"] == 0 for r in result.both)
    assert (
        reconcile.main(["--database", world, "--out", str(tmp_path), "--evidence", *CLI_EVERY_DAY])
        == 0
    )
    report = (tmp_path / "reconciliation.md").read_text()
    assert "exact, 0 differences" in report and "**0 beyond both thresholds**" in report
    rows = list(csv.DictReader((tmp_path / "reconciliation.csv").open()))
    assert len(rows) == len(result.external) and {r["over_threshold"] for r in rows} == {"0"}
    evidence = (tmp_path / "reconciliation_evidence.md").read_text()
    # "PENDING — Roberto writes it" until 2026-09-20; Roberto then asked for a marked draft.
    assert f"## Findings\n\n**{reconcile.AUTHORSHIP}**\n" in evidence
    assert "- 1. " in evidence and "- 10. " in evidence, "titles and states of the ten findings"


# --- A: a planted internal difference ---------------------------------------------------------


def test_a_planted_internal_difference_is_detected_and_fails_the_command(
    clickhouse, world, tmp_path
):
    pool, day = clickhouse.query(
        f"SELECT pool_address, block_date FROM {ch.qualified(world, mv.READ_VIEW)} LIMIT 1"
    ).result_rows[0]
    clickhouse.command(  # as if a backfill had counted one swap twice
        f"INSERT INTO {ch.qualified(world, mv.TARGET)} VALUES ('{pool}', '{day}', 1, 5, 7)"
    )
    result = reconcile.run(clickhouse, world)
    assert len(result.internal) == 1
    bad = result.internal[0]
    assert (bad["pool_address"], bad["block_date"], bad["problem"]) == (pool, day, "differs")
    assert bad["view_swaps"] == bad["recomputed_swaps"] + 1
    assert bad["view_amount0"] == bad["recomputed_amount0"] + 5
    assert reconcile.main(["--database", world, "--out", str(tmp_path)]) == 1
    assert "FAILED, 1 pool-day(s) differ" in (tmp_path / "reconciliation.md").read_text()


def test_a_day_missing_from_the_view_is_detected(clickhouse, world):
    pool, day = clickhouse.query(
        f"SELECT pool_address, block_date FROM {ch.qualified(world, mv.READ_VIEW)} LIMIT 1"
    ).result_rows[0]
    clickhouse.command(
        f"ALTER TABLE {ch.qualified(world, mv.TARGET)} DELETE WHERE pool_address = '{pool}' "
        f"AND block_date = '{day}'",
        settings={"mutations_sync": 2},
    )
    (bad,) = reconcile.run(clickhouse, world).internal
    assert bad["problem"] == "only in recomputation"


# --- B: a planted external difference ---------------------------------------------------------


def test_b_planted_external_difference_is_listed_with_both_values(clickhouse, world, tmp_path):
    victim = reconcile.run(clickhouse, world).both[0]
    revise(clickhouse, world, victim, 1.05)  # the source now says 5% more than us
    result = reconcile.run(clickhouse, world, **EVERY_DAY)
    (over,) = result.over_threshold
    assert (over["pool_address"], over["date"]) == (victim["pool_address"], victim["date"])
    assert over["external_volume_usd"] == pytest.approx(victim["our_volume_usd"] * 1.05)
    assert over["rel_diff"] == pytest.approx(1 / 1.05 - 1)
    assert over["abs_diff_usd"] == pytest.approx(-0.05 * victim["our_volume_usd"])
    assert result.internal_ok, "B never contaminates A"

    assert reconcile.main(["--database", world, "--out", str(tmp_path), *CLI_EVERY_DAY]) == 0
    assert (
        reconcile.main(
            ["--database", world, "--out", str(tmp_path), "--fail-on-external", *CLI_EVERY_DAY]
        )
        == 2
    )
    assert "**1 beyond both thresholds**" in (tmp_path / "reconciliation.md").read_text()


def test_the_threshold_is_a_visible_parameter(clickhouse, world):
    victim = reconcile.run(clickhouse, world).both[0]
    revise(clickhouse, world, victim, 1.05)
    assert len(reconcile.run(clickhouse, world, threshold=0.01, **EVERY_DAY).over_threshold) == 1
    assert len(reconcile.run(clickhouse, world, threshold=0.10, **EVERY_DAY).over_threshold) == 0
    assert reconcile.DEFAULT_THRESHOLD == 0.01


# --- B: days present on one side only ----------------------------------------------------------


def test_a_day_the_external_source_lacks_is_listed_apart(clickhouse, world):
    victim = reconcile.run(clickhouse, world).both[0]
    clickhouse.command(
        f"ALTER TABLE {ch.qualified(world, external.TABLE)} DELETE WHERE "
        f"pool_address = '{victim['pool_address']}' AND date = '{victim['date']}'",
        settings={"mutations_sync": 2},
    )
    result = reconcile.run(clickhouse, world)
    (missing,) = result.one_sided
    assert missing["presence"] == "only_ours" and missing["date"] == victim["date"]
    assert missing["rel_diff"] is None and missing not in result.over_threshold


def test_a_day_we_lack_is_listed_apart(clickhouse, world):
    before = reconcile.run(clickhouse, world)
    pools_by_days = {}
    for r in before.both:
        pools_by_days.setdefault(r["pool_address"], []).append(r)
    victim = next(rows[0] for rows in pools_by_days.values())
    clickhouse.command(
        f"ALTER TABLE {ch.qualified(world)} DELETE WHERE pool_address = '{victim['pool_address']}' "
        f"AND toDate(block_timestamp, 'UTC') = '{victim['date']}'",
        settings={"mutations_sync": 2},
    )
    mv.rebuild(clickhouse, world)
    result = reconcile.run(clickhouse, world)
    lacking = [r for r in result.one_sided if r["presence"] == "only_external"]
    if victim["date"] in {r["date"] for r in result.both} | {r["date"] for r in lacking}:
        assert [(r["pool_address"], r["date"]) for r in lacking] == [
            (victim["pool_address"], victim["date"])
        ]
    assert result.internal_ok


# --- which leg is the dollar --------------------------------------------------------------------


def test_the_stablecoin_list_comes_from_the_dbt_project_and_picks_the_right_leg():
    stables = reconcile.stablecoin_symbols()
    assert stables == ["USDC", "USDT", "DAI"]
    parameters = reconcile.stable_leg_parameters(load_pools(), stables)
    by_pool = dict(zip(parameters["stable_pools"], zip(parameters["stable_is_token0"],
                                                       parameters["stable_decimals"], strict=True),
                       strict=True))  # fmt: skip
    for pool in load_pools():
        expected = (1, pool.decimals0) if pool.token0 == "USDC" else (0, pool.decimals1)
        assert by_pool[str(pool.key)] == expected


def test_a_pool_without_a_stablecoin_gets_no_usd_volume():
    exotic = Pool("0x" + "ab" * 20, "WBTC", "WETH", 8, 18, 3000, "WBTC/WETH 0.3%")
    parameters = reconcile.stable_leg_parameters([exotic], ["USDC", "USDT", "DAI"])
    assert parameters == {"stable_pools": [], "stable_is_token0": [], "stable_decimals": []}


# --- the two rules of what gets compared and what gets flagged (synthetic, no server) ---------

POOL = "0x" + "11" * 20
DOWNLOADED = datetime.datetime(2026, 9, 20, 14, 31, tzinfo=datetime.UTC)


def pool_day(date, ours, theirs, partial=False, fetched=DOWNLOADED):
    return {"pool_address": POOL, "date": datetime.date.fromisoformat(date), "presence": "both",
            "partial_day": partial, "our_swaps": 10, "our_volume_usd": ours,
            "external_volume_usd": theirs, "external_fetched_at": fetched,
            "abs_diff_usd": ours - theirs, "rel_diff": (ours - theirs) / theirs}  # fmt: skip


def synthetic(rows, **kwargs):
    return reconcile.Result(external=rows, labels={POOL: "SYN/USD 0.05%"}, **kwargs)


def test_defaults_of_the_two_rules_are_visible():
    assert reconcile.DEFAULT_THRESHOLD == 0.01 and reconcile.DEFAULT_ABS_THRESHOLD == 1000.0
    result = synthetic([])
    assert result.complete_days_only is True and result.abs_threshold == 1000.0


def test_a_day_partial_on_our_side_is_excluded_with_its_reason_and_still_listed():
    partial = pool_day("2026-08-20", 74_000_000, 114_000_000, partial=True)  # -35%
    whole = pool_day("2026-08-21", 100_000_000, 100_000_100)
    result = synthetic([partial, whole])
    assert result.compared == [whole] and result.excluded == [partial]
    assert result.exclusion(partial) == [reconcile.PARTIAL]
    assert result.over_threshold == [], "a partial day is never flagged, however far off it is"
    report = reconcile.render(result, "synthetic")
    assert "2026-08-20" in report and reconcile.PARTIAL in report, "excluded, not hidden"


def test_a_candle_downloaded_while_its_day_was_open_is_excluded():
    # The real case: 2026-09-19 downloaded at 23:12 UTC of that same day.
    same_day = datetime.datetime(2026, 9, 19, 23, 12, tzinfo=datetime.UTC)
    open_candle = pool_day("2026-09-19", 50_144_724, 51_240_581, fetched=same_day)  # -2.14%
    closed = pool_day("2026-09-19", 50_144_724, 51_240_581, fetched=DOWNLOADED)
    day_of_download = pool_day("2026-09-20", 26_000_000, 27_000_000, fetched=DOWNLOADED)
    assert synthetic([open_candle]).exclusion(open_candle) == [reconcile.OPEN_CANDLE]
    assert synthetic([closed]).exclusion(closed) == []
    assert synthetic([closed]).over_threshold == [closed], "closed and complete: it is compared"
    assert synthetic([day_of_download]).exclusion(day_of_download) == [reconcile.OPEN_CANDLE]


def test_both_reasons_are_given_when_both_apply():
    row = pool_day("2026-09-20", 1.0, 2.0, partial=True)
    assert synthetic([row]).exclusion(row) == [reconcile.PARTIAL, reconcile.OPEN_CANDLE]


def test_a_naive_download_time_is_read_as_utc():
    row = pool_day("2026-09-19", 1.0, 2.0, fetched=datetime.datetime(2026, 9, 19, 23, 12))
    assert synthetic([row]).exclusion(row) == [reconcile.OPEN_CANDLE]


def test_switching_the_rule_off_compares_every_day():
    partial = pool_day("2026-08-20", 74_000_000, 114_000_000, partial=True)
    result = synthetic([partial], complete_days_only=False)
    assert result.excluded == [] and result.over_threshold == [partial]


def test_flagged_means_beyond_the_relative_and_the_absolute_threshold():
    small = pool_day("2026-09-03", 11_069, 13_448)  # -17.69%, -2,379 USD: beyond both
    tiny = pool_day("2026-08-31", 123, 132)  # -6.75%, -9 USD: relative only
    big_but_close = pool_day("2026-09-01", 100_000_000, 100_500_000)  # -0.5%, -500,000 USD
    edge = pool_day("2026-09-02", 49_000, 50_000)  # -2%, exactly 1,000 USD: not beyond
    result = synthetic([small, tiny, big_but_close, edge])
    assert result.over_threshold == [small]
    assert result.below_absolute == [tiny, edge]
    assert big_but_close not in result.over_relative, "the absolute threshold alone flags nothing"
    report = reconcile.render(result, "synthetic")
    below = report.split("below the absolute threshold")[1].split("## B: pool-days excluded")[0]
    assert "2026-08-31" in below and "2026-09-02" in below and "2026-09-03" not in below


def test_the_absolute_threshold_is_a_visible_parameter():
    tiny = pool_day("2026-08-31", 123, 132)
    assert synthetic([tiny], abs_threshold=5.0).over_threshold == [tiny]
    assert synthetic([tiny], abs_threshold=0.0).below_absolute == []


def test_the_csv_says_which_rule_applied_to_each_pool_day(tmp_path):
    rows = [
        pool_day("2026-08-20", 74.0, 114.0, partial=True),
        pool_day("2026-09-03", 11_069, 13_448),
        pool_day("2026-08-31", 123, 132),
    ]
    reconcile.write_csv(synthetic(rows), tmp_path / "r.csv")
    out = {r["date"]: r for r in csv.DictReader((tmp_path / "r.csv").open())}
    assert out["2026-08-20"]["excluded_reason"] == reconcile.PARTIAL
    assert (out["2026-08-20"]["over_threshold"], out["2026-08-20"]["over_relative_only"]) == (
        "0",
        "0",
    )
    assert (out["2026-09-03"]["over_threshold"], out["2026-09-03"]["over_relative_only"]) == (
        "1",
        "0",
    )
    assert (out["2026-08-31"]["over_threshold"], out["2026-08-31"]["over_relative_only"]) == (
        "0",
        "1",
    )


def test_with_the_default_rules_the_two_day_fixture_has_nothing_to_compare(
    clickhouse, world, tmp_path
):
    victim = reconcile.run(clickhouse, world).both[0]
    revise(clickhouse, world, victim, 1.05)
    result = reconcile.run(clickhouse, world)
    assert result.compared == [] and len(result.excluded) == len(result.both) > 0
    assert (
        reconcile.main(
            ["--database", world, "--out", str(tmp_path), "--evidence", "--fail-on-external"]
        )
        == 0
    )
    report = (tmp_path / "reconciliation.md").read_text()
    assert reconcile.PARTIAL in report and str(victim["date"]) in report
