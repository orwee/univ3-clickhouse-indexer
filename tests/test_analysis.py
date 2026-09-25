"""sql/analysis/: the cross-pool gap and its episodes, and the concentration of round trips.

The swaps are planted by hand in a throw-away database with prices chosen so that every
expected number is known: which pool opened each divergence, which closed it, and how many
blocks it lasted. The pool addresses are obviously fake.
"""

import datetime
import math
import re

import pytest

from univ3_indexer import analysis, loader
from univ3_indexer import clickhouse as ch
from univ3_indexer.pools import Pool, load_pools

LO, HI = "0x" + "ab" * 20, "0x" + "cd" * 20
UTC = datetime.UTC


def sqrt_price(price: float) -> int:
    return int(2**96 * math.sqrt(price))


def swap(pool, block, log_index, price, sender=b"\x01" * 20):
    when = datetime.datetime(2026, 9, 1, 12, tzinfo=UTC) + datetime.timedelta(seconds=12 * block)
    return [pool, block, when, bytes([block % 256, log_index]) * 16, log_index, sender, sender,
            1_000_000, -1_000, sqrt_price(price), 10**18, 0]  # fmt: skip


# hi sets the price; lo follows; lo moves 20 bps away (opens, by lo) and stays away; hi catches
# up two blocks later (closes, by hi); hi then moves 30 bps down (opens, by hi) and lo follows
# in the same block (closes, by lo).
PLANTED = [
    swap(HI, 100, 0, 1.0),
    swap(LO, 100, 1, 1.0),
    swap(LO, 101, 0, 1.002),
    swap(LO, 101, 1, 1.0021),
    swap(HI, 103, 0, 1.002),
    swap(HI, 104, 0, 0.999),
    swap(LO, 104, 5, 0.999),
]


@pytest.fixture
def planted(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database)
    clickhouse.insert(ch.qualified(temp_database), PLANTED, column_names=loader.COLUMNS)
    return temp_database


def params():
    return {"lo": LO, "hi": HI, "fee_bps": 6.0}


def test_the_gap_is_the_log_ratio_of_the_two_prices_in_bps(clickhouse, planted):
    q = analysis.run(clickhouse, "01_cross_pool_gap.sql", params(), database=planted)
    rows = {r["moved"]: r for r in q["rows"]}
    # every swap but the very first (hi at block 100 has no lo before it) gets a gap
    assert rows[""]["swaps"] == len(PLANTED) - 1
    assert rows["lo"]["swaps"] == 4 and rows["hi"]["swaps"] == 2
    largest = 1e4 * math.log(1.0021 / 0.999)  # hi at 0.999 against lo still at 1.0021
    assert rows[""]["abs_gap_max_bps"] == pytest.approx(largest, rel=1e-6)
    assert rows[""]["beyond_combined_fee"] == 3  # lo 1.002, lo 1.0021, hi 0.999


def test_an_episode_opens_with_one_pool_and_closes_with_the_other(clickhouse, planted):
    (row,) = analysis.run(clickhouse, "03_cross_pool_episodes.sql", params(), planted)["rows"]
    assert row["episodes"] == 2
    assert row["still_open_at_the_end"] == 0
    assert row["closed_in_the_same_block"] == 1  # hi moves at 104, lo follows in 104
    assert row["closed_two_or_more_blocks_later"] == 1  # lo moves at 101, hi follows at 103
    assert row["blocks_open_max"] == 2
    assert (row["opened_by_lo"], row["opened_by_hi"]) == (1, 1)
    assert (row["closed_by_lo"], row["closed_by_hi"]) == (1, 1)
    assert row["closed_by_the_other_pool"] == 2 and row["closed_by_the_same_pool"] == 0
    assert (row["opened_by_lo_closed_by_hi"], row["opened_by_hi_closed_by_lo"]) == (1, 1)
    assert row["never_left_one_transaction"] == 0, "every planted swap is its own transaction"


def test_a_divergence_opened_and_closed_inside_one_transaction_is_counted(
    clickhouse, temp_database
):
    ch.apply_ddl(clickhouse, temp_database)
    one_tx = swap(LO, 101, 0, 1.01)[:3] + [b"\x77" * 32] + swap(LO, 101, 0, 1.01)[4:]
    back = swap(HI, 101, 1, 1.01)[:3] + [b"\x77" * 32] + swap(HI, 101, 1, 1.01)[4:]
    rows = [swap(HI, 100, 0, 1.0), swap(LO, 100, 1, 1.0), one_tx, back]
    clickhouse.insert(ch.qualified(temp_database), rows, column_names=loader.COLUMNS)
    (row,) = analysis.run(clickhouse, "03_cross_pool_episodes.sql", params(), temp_database)["rows"]
    assert (row["episodes"], row["never_left_one_transaction"]) == (1, 1)


def test_the_gap_is_also_measured_where_each_block_ends(clickhouse, planted):
    (row,) = analysis.run(clickhouse, "04_cross_pool_block_ends.sql", params(), planted)["rows"]
    # blocks 100, 101, 103, 104; only 101 ends with lo 21 bps above hi
    assert (row["blocks"], row["blocks_ending_within_the_fee"]) == (4, 3)


def test_an_episode_still_open_at_the_last_swap_is_counted_apart(clickhouse, temp_database):
    ch.apply_ddl(clickhouse, temp_database)
    rows = [swap(HI, 100, 0, 1.0), swap(LO, 100, 1, 1.0), swap(LO, 101, 0, 1.01)]
    clickhouse.insert(ch.qualified(temp_database), rows, column_names=loader.COLUMNS)
    (row,) = analysis.run(clickhouse, "03_cross_pool_episodes.sql", params(), temp_database)["rows"]
    assert (row["episodes"], row["still_open_at_the_end"]) == (1, 1)
    assert row["closed_by_lo"] + row["closed_by_hi"] == 0, "an open episode was closed by nobody"


def test_the_histogram_counts_every_gap_once(clickhouse, planted):
    q = analysis.run(clickhouse, "02_cross_pool_gap_histogram.sql", params(), planted)
    assert sum(r["swaps"] for r in q["rows"]) == len(PLANTED) - 1
    assert max(r["bucket_bps"] for r in q["rows"]) <= 20


def test_explain_reports_the_granules_the_primary_key_kept(clickhouse, planted):
    scans = analysis.granules(clickhouse, "01_cross_pool_gap.sql", params(), planted)
    assert len(scans) == 4, "two pools, each read twice: a CTE is not materialised"
    assert all(0 < s["kept"] <= s["total"] for s in scans)
    assert all(LO in s["condition"] or HI in s["condition"] for s in scans)


# --- round-trip concentration ------------------------------------------------------------------


def test_concentration_is_reported_as_ranks_and_never_names_a_sender(clickhouse, temp_database):
    clickhouse.command(
        f"CREATE TABLE {temp_database}.fct_round_trip_legs (sender String, "
        "volume_usd Nullable(Decimal256(18))) ENGINE = MergeTree ORDER BY sender"
    )
    legs = [("0x" + "01" * 20, 60), ("0x" + "02" * 20, 30), ("0x" + "02" * 20, 0),
            ("0x" + "03" * 20, 10)]  # fmt: skip
    clickhouse.insert(
        f"{temp_database}.fct_round_trip_legs", legs, column_names=["sender", "volume_usd"]
    )
    (row,) = analysis.run(
        clickhouse, "12_round_trips_concentration.sql", {"dbt": temp_database}, temp_database
    )["rows"]
    assert (row["senders"], row["total_legs"], row["total_usd"]) == (3, 4, 100)
    assert row["top1_share_of_usd"] == pytest.approx(0.6)
    assert row["top3_share_of_usd"] == pytest.approx(1.0)
    assert row["top1_share_of_legs"] == pytest.approx(0.25)
    assert not any(isinstance(v, str) and v.startswith("0x") for v in row.values())


def test_no_analysis_query_selects_an_address_or_a_hash():
    for path in sorted(analysis.ANALYSIS_DIR.glob("*.sql")):
        sql = ch.strip_sql_comments(path.read_text(encoding="utf-8"))
        select_lists = re.findall(r"SELECT(.*?)FROM", sql, re.S | re.I)
        for select in select_lists[-1:]:  # the outermost SELECT is the last one written
            assert not re.search(r"\b(sender|recipient|tx_hash|pool_address)\b", select), path.name


# --- which pools -------------------------------------------------------------------------------


def test_the_pairs_of_fee_tiers_come_from_pools_yml():
    pairs = analysis.fee_tier_pairs()
    assert [p["pair"] for p in pairs] == ["USDC/WETH", "wstETH/USDC"]
    by_pair = {p["pair"]: p for p in pairs}
    assert by_pair["USDC/WETH"]["fee_bps"] == 6.0  # 0.01% + 0.05%
    assert by_pair["wstETH/USDC"]["fee_bps"] == 35.0  # 0.05% + 0.3%
    labels = {p.key.lower(): p.label for p in load_pools()}
    for p in pairs:
        assert labels[p["lo"]] == p["lo_label"] and labels[p["hi"]] == p["hi_label"]


def test_three_pools_of_one_pair_are_refused():
    def pool(fee, n):
        return Pool("0x" + f"{n:02x}" * 20, "USDC", "WETH", 6, 18, fee, f"USDC/WETH {fee}")

    with pytest.raises(analysis.AnalysisError):
        analysis.fee_tier_pairs([pool(100, 1), pool(500, 2), pool(3000, 3)])
    with pytest.raises(analysis.AnalysisError):
        analysis.fee_tier_pairs([pool(100, 1)])


def test_both_join_algorithms_give_the_same_answer(clickhouse, planted):
    pair = {"lo": LO, "hi": HI, "fee_bps": 6.0}
    rows = analysis.join_algorithms(clickhouse, pair, database=planted)
    assert [r["join_algorithm"] for r in rows] == list(analysis.JOIN_ALGORITHMS)
    assert all(r["same_answer_as_hash"] for r in rows)
    assert all(r["runs"] == analysis.REPEATS and r["read_rows"] > 0 for r in rows)
