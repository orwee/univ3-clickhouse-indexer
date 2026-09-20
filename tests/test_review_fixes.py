"""Defects found by an independent review on 2026-09-20. Each test pins one of the fixes."""

import re

import pytest

from univ3_indexer import clickhouse as ch
from univ3_indexer import mv, reconcile
from univ3_indexer.config import REPO_ROOT

from .test_reconcile import world  # noqa: F401 - pytest fixture

SQL_WITH_OUTER_JOINS = sorted(
    p
    for p in ch.SQL_DIR.rglob("*.sql")
    # joins that KEEP unmatched rows; ANTI and SEMI joins return no columns of the other side
    if re.search(r"\b(FULL|LEFT|RIGHT)\s+(OUTER\s+)?JOIN\b", p.read_text())
)
DOCS = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]


def test_the_control_queries_do_not_depend_on_a_session_setting():
    """They compare an unmatched side with '' and 0. Under join_use_nulls = 1 that is a
    comparison with NULL, and the WHERE drops exactly the rows that matter."""
    assert SQL_WITH_OUTER_JOINS, "there are outer joins in sql/"
    unpinned = [
        str(p.relative_to(REPO_ROOT))
        for p in SQL_WITH_OUTER_JOINS
        if "SETTINGS join_use_nulls = 0" not in ch.strip_sql_comments(p.read_text())
    ]
    assert not unpinned, unpinned


def test_a_missing_day_is_still_detected_by_a_session_that_uses_nulls(clickhouse, world):  # noqa: F811
    pool, day = clickhouse.query(
        f"SELECT pool_address, block_date FROM {ch.qualified(world, mv.READ_VIEW)} LIMIT 1"
    ).result_rows[0]
    clickhouse.command(
        f"ALTER TABLE {ch.qualified(world, mv.TARGET)} DELETE WHERE pool_address = '{pool}' "
        f"AND block_date = '{day}'",
        settings={"mutations_sync": 2},
    )
    hostile = ch.connect(database="default")
    hostile.set_client_setting("join_use_nulls", "1")
    (bad,) = reconcile.run(hostile, world, internal_only=True).internal
    assert (bad["pool_address"], bad["block_date"], bad["problem"]) == (
        pool,
        day,
        "only in recomputation",
    )
    assert len(mv.mismatches(hostile, world)) == 1


def test_documented_commands_can_be_pasted():
    """The package is not installed (pyproject: package = false): without PYTHONPATH=src a
    `python -m univ3_indexer…` is a ModuleNotFoundError."""
    broken = []
    for doc in DOCS:
        for number, line in enumerate(doc.read_text().splitlines(), start=1):
            for match in re.finditer(r"python -m univ3_indexer", line):
                if "PYTHONPATH=src" not in line[: match.start()]:
                    broken.append(f"{doc.relative_to(REPO_ROOT)}:{number}")
    assert not broken, broken


def test_make_load_looks_where_the_backfill_writes():
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert re.search(r"^LANDING \?=\s*$", makefile, re.MULTILINE), "no hard-coded landing directory"
    assert "--landing $(LANDING)" not in makefile.replace(
        "$(if $(LANDING),--landing $(LANDING),)", ""
    )


def test_the_readme_does_not_hard_code_a_count_of_dbt_tests():
    assert not re.search(r"dbt build.{0,20}\(\d+ tests\)", (REPO_ROOT / "README.md").read_text())


@pytest.mark.parametrize("claim", ["removed index pruning**", "anula la poda**", "no pruning"])
def test_the_claim_that_final_removed_pruning_is_gone(claim):
    """The raw results show the same rows read with and without FINAL."""
    for path in ("DECISIONS.md", "README.md", "docs/SCHEMA_EXPERIMENTS.md"):
        assert claim not in (REPO_ROOT / path).read_text(), path
