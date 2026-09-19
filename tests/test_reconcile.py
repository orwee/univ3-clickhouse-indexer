"""Reconciliation must DETECT: a planted difference in A, one in B, and a missing day."""

import csv
import datetime

import pytest

from univ3_indexer import clickhouse as ch
from univ3_indexer import external, loader, mv, reconcile
from univ3_indexer.pools import Pool, load_pools

from .test_loader import make_landing

FETCHED = datetime.datetime(2026, 9, 20, 0, 0, tzinfo=datetime.UTC)


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
    result = reconcile.run(clickhouse, world)
    assert result.internal == [] and result.internal_ok
    assert len(result.both) == len(result.external) > 0
    assert result.over_threshold == [] and result.one_sided == []
    assert all(r["rel_diff"] == 0 for r in result.both)
    assert reconcile.main(["--database", world, "--out", str(tmp_path), "--evidence"]) == 0
    report = (tmp_path / "reconciliation.md").read_text()
    assert "exact, 0 differences" in report and "**0 beyond the threshold**" in report
    rows = list(csv.DictReader((tmp_path / "reconciliation.csv").open()))
    assert len(rows) == len(result.external) and {r["over_threshold"] for r in rows} == {"0"}
    evidence = (tmp_path / "reconciliation_evidence.md").read_text()
    assert "## Hallazgos\n\nPENDIENTE — lo escribe Roberto\n" in evidence


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
    result = reconcile.run(clickhouse, world)
    (over,) = result.over_threshold
    assert (over["pool_address"], over["date"]) == (victim["pool_address"], victim["date"])
    assert over["external_volume_usd"] == pytest.approx(victim["our_volume_usd"] * 1.05)
    assert over["rel_diff"] == pytest.approx(1 / 1.05 - 1)
    assert over["abs_diff_usd"] == pytest.approx(-0.05 * victim["our_volume_usd"])
    assert result.internal_ok, "B never contaminates A"

    assert reconcile.main(["--database", world, "--out", str(tmp_path)]) == 0
    assert reconcile.main(["--database", world, "--out", str(tmp_path), "--fail-on-external"]) == 2
    assert "**1 beyond the threshold**" in (tmp_path / "reconciliation.md").read_text()


def test_the_threshold_is_a_visible_parameter(clickhouse, world):
    victim = reconcile.run(clickhouse, world).both[0]
    revise(clickhouse, world, victim, 1.05)
    assert len(reconcile.run(clickhouse, world, threshold=0.01).over_threshold) == 1
    assert len(reconcile.run(clickhouse, world, threshold=0.10).over_threshold) == 0
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
