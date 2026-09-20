"""The slow proof is `make dbt-prove`. These are the cheap guards around it."""

import re
import sys

import yaml

from univ3_indexer.config import REPO_ROOT

DBT = REPO_ROOT / "dbt"
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def schema_tests():
    """(model, column or None, test name) for every generic test declared in a schema file."""
    found = []
    for path in DBT.glob("models/**/schema.yml"):
        document = yaml.safe_load(path.read_text())
        for node in document.get("models", []) + document.get("seeds", []):
            for test in node.get("tests", []):
                found.append(
                    (node["name"], None, test if isinstance(test, str) else next(iter(test)))
                )
            for column in node.get("columns", []):
                for test in column.get("tests", []):
                    name = test if isinstance(test, str) else next(iter(test))
                    found.append((node["name"], column["name"], name))
    return found


def test_the_kinds_of_test_that_cannot_fail_in_clickhouse_are_gone():
    names = {name for _, _, name in schema_tests()}
    assert "relationships" not in names, "the models INNER JOIN what they would be related to"
    assert "non_negative" not in names and not (DBT / "tests/generic/non_negative.sql").exists()


def test_not_null_is_only_declared_on_the_columns_that_are_nullable():
    # The Nullable columns of the models, by construction: volume_usd is NULL without a
    # stablecoin, and what is computed from it inherits that. Everything else is not Nullable.
    nullable = {("stg_swaps", "volume_usd"), ("fct_pool_daily", "volume_usd"),
                ("fct_pool_daily", "fees_usd"),
                ("fct_pool_daily_smart_money", "smart_money_share_of_volume_usd")}  # fmt: skip
    declared = {(model, column) for model, column, name in schema_tests() if name == "not_null"}
    assert declared == nullable


def test_every_singular_test_has_a_scenario_that_breaks_it():
    import prove_dbt_tests_can_fail as proof

    expected = set().union(*(tests for _, _, tests in proof.SCENARIOS))
    singular = {p.stem for p in (DBT / "tests").glob("*.sql")}
    assert singular <= expected, singular - expected
    for model, column, name in schema_tests():
        assert any(re.match(rf"{name}_{model}_", t) for t in expected), (model, column, name)
