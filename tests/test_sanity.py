"""Sanity checks must DETECT planted defects, not just run."""

from pathlib import Path

import pytest

from univ3_indexer import clickhouse as ch
from univ3_indexer import loader, sanity

from .test_loader import make_landing


def outcome(outcomes, prefix):
    return next(o for o in outcomes if o.check.path.name.startswith(prefix))


@pytest.fixture
def loaded(clickhouse, temp_database, tmp_path):
    make_landing(tmp_path / "landing")
    loader.load(clickhouse, temp_database, tmp_path / "landing", "full")
    return temp_database


# --- the files themselves (no server needed) ------------------------------------------


def test_every_query_has_a_complete_header_and_never_names_a_database():
    found = sanity.checks()
    assert len(found) >= 6
    for check in found:
        assert check.title and check.question and check.problem
        assert check.expect in ("empty", "informational")
        assert "onchain" not in check.sql.lower(), check.path.name
    assert {c.path.name[:2] for c in found if c.expect == "empty"} == {"02", "04"}


def test_a_file_without_a_header_is_rejected(tmp_path):
    (tmp_path / "01_x.sql").write_text("SELECT 1\n")
    with pytest.raises(ValueError, match="header lacks"):
        sanity.checks(tmp_path)


# --- against real tables ----------------------------------------------------------------


def test_clean_data_passes_every_check(clickhouse, loaded):
    outcomes = sanity.run(clickhouse, loaded)
    assert [o.check.path.name for o in outcomes if o.failed] == []
    assert outcome(outcomes, "01").rows, "rows per pool and day must not be empty"
    assert outcome(outcomes, "06").rows, "physical state must see the table's parts"
    assert not outcome(outcomes, "06").refused


def test_a_planted_duplicate_is_detected(clickhouse, loaded):
    table = ch.qualified(loaded)
    clickhouse.command(f"INSERT INTO {table} SELECT * FROM {table} ORDER BY block_number LIMIT 1")
    duplicates = outcome(sanity.run(clickhouse, loaded), "02")
    assert duplicates.failed
    assert len(duplicates.rows) == 1
    assert dict(zip(duplicates.columns, duplicates.rows[0], strict=True))["copies"] == 2


def test_a_planted_same_sign_swap_is_detected_and_listed(clickhouse, loaded):
    table = ch.qualified(loaded)
    clickhouse.command(
        f"INSERT INTO {table} SELECT pool_address, block_number, block_timestamp, tx_hash, "
        f"99999 AS log_index, sender, recipient, toInt256(5) AS amount0, toInt256(7) AS amount1, "
        f"sqrt_price_x96, liquidity, tick FROM {table} LIMIT 1"
    )
    outcomes = sanity.run(clickhouse, loaded)
    same_sign = outcome(outcomes, "04")
    assert same_sign.failed and len(same_sign.rows) == 1
    row = dict(zip(same_sign.columns, same_sign.rows[0], strict=True))
    assert (row["log_index"], row["amount0"], row["amount1"]) == (99999, 5, 7)
    assert not outcome(outcomes, "02").failed, "a new log_index is not a duplicate"


def test_negative_same_sign_and_zero_legs_are_told_apart(clickhouse, loaded):
    table = ch.qualified(loaded)
    for log_index, a0, a1 in ((90001, -5, -7), (90002, 0, 7), (90003, 0, 0)):
        clickhouse.command(
            f"INSERT INTO {table} SELECT pool_address, block_number, block_timestamp, tx_hash, "
            f"{log_index}, sender, recipient, toInt256({a0}), toInt256({a1}), sqrt_price_x96, "
            f"liquidity, tick FROM {table} LIMIT 1"
        )
    outcomes = sanity.run(clickhouse, loaded)
    assert [r[2] for r in outcome(outcomes, "04").rows] == [90001]
    zero = outcome(outcomes, "05")
    assert not zero.failed, "zero legs are listed for review, they do not fail the run"
    kinds = {r[2]: r[6] for r in zero.rows}
    assert kinds[90002] == "one zero leg" and kinds[90003] == "BOTH ZERO"


def test_the_command_writes_the_report_and_exits_non_zero_on_a_defect(clickhouse, loaded, tmp_path):
    report = tmp_path / "out" / "sanity.md"
    assert sanity.main(["--database", loaded, "--out", str(report)]) == 0
    text = report.read_text()
    assert "**Result: ok**" in text and "sql/sanity/02_duplicates.sql" in text

    table = ch.qualified(loaded)
    clickhouse.command(f"INSERT INTO {table} SELECT * FROM {table} LIMIT 1")
    assert sanity.main(["--database", loaded, "--out", str(report)]) == 1
    text = report.read_text()
    assert "**Result: FAILED**" in text and "must not exist" in text


def test_a_refused_query_is_reported_not_fatal(clickhouse, loaded, tmp_path):
    header = "-- title: t\n-- question: q\n-- problem: p\n-- expect: informational\n"
    (tmp_path / "01_refused.sql").write_text(header + "SELECT * FROM system.no_such_table\n")
    (outcome_,) = sanity.run(clickhouse, loaded, tmp_path)
    assert outcome_.refused and not outcome_.failed
    assert "refused" in sanity.render([outcome_], loaded)


def test_default_report_path_is_inside_reports():
    assert Path("reports/sanity.md") == sanity.DEFAULT_REPORT.relative_to(sanity.config.REPO_ROOT)
