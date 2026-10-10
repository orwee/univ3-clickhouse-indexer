"""The dollar budget: check before, record after, a failure at its worst case, and a ledger."""

import json
from decimal import Decimal

import pytest

from agent import budget
from univ3_indexer import config


def test_a_call_that_does_not_fit_is_refused_before_it_is_made():
    b = budget.DollarBudget("0.25")
    b.check("0.25")
    b.record("0.10")
    assert b.spent == Decimal("0.10") and b.remaining == Decimal("0.15")
    b.check("0.15")
    with pytest.raises(budget.BudgetExceeded) as err:
        b.check("0.150001")
    assert "$0.150001" in str(err.value) and "$0.10 of $0.25" in str(err.value)
    assert b.spent == Decimal("0.10")  # a refusal books nothing


def test_the_real_cost_is_recorded_and_a_failed_call_is_booked_at_its_worst_case():
    b = budget.DollarBudget("1")
    b.check("0.40")
    b.record("0.031")  # it cost far less than the worst case
    b.check("0.40")
    b.fail("0.40")  # no usage came back: assume it was served and billed in full
    assert b.spent == Decimal("0.431")
    b.check("0.40")
    b.record("0.40")
    with pytest.raises(budget.BudgetExceeded):
        b.check("0.40")


def test_amounts_add_up_exactly():
    b = budget.DollarBudget("0.3")
    for _ in range(3):
        b.check("0.1")
        b.record("0.1")
    assert b.spent == Decimal("0.3") and b.remaining == 0
    with pytest.raises(budget.BudgetExceeded):
        b.check("0.000001")


@pytest.mark.parametrize("bad", ["-0.01", "NaN", "Infinity"])
def test_what_is_not_a_dollar_amount_is_refused(bad):
    with pytest.raises(ValueError, match="not a dollar amount"):
        budget.DollarBudget("1").record(bad)
    with pytest.raises(ValueError, match="not a dollar amount"):
        budget.DollarBudget(bad)


def test_floats_are_not_accepted():
    with pytest.raises(TypeError, match="never float"):
        budget.DollarBudget("1").record(0.1)


def test_the_ledger_makes_the_ceiling_outlive_the_process(tmp_path):
    ledger = tmp_path / "deep" / "ledger.jsonl"
    first = budget.DollarBudget("0.25", ledger, scope="run-1")
    first.check("0.20")
    first.record("0.07", "question 1", model="some-model", input_tokens=1200)
    first.fail("0.12", "question 2 timed out")

    second = budget.DollarBudget("0.25", ledger, scope="run-1")
    assert second.spent == Decimal("0.19")
    with pytest.raises(budget.BudgetExceeded):
        second.check("0.07")
    second.check("0.06")
    second.record("0.06")
    assert budget.DollarBudget("0.25", ledger, scope="run-1").remaining == 0

    lines = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [(e["usd"], e["outcome"]) for e in lines] == [
        ("0.07", "ok"),
        ("0.12", "failed"),
        ("0.06", "ok"),
    ]
    assert lines[0]["details"] == {"model": "some-model", "input_tokens": 1200}
    assert lines[0]["note"] == "question 1" and "details" not in lines[1]
    assert all(e["scope"] == "run-1" and e["at"].endswith("+00:00") for e in lines)


def test_another_scope_has_its_own_ceiling_and_no_scope_counts_everything(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    budget.DollarBudget("1", ledger, scope="a").record("0.30")
    budget.DollarBudget("1", ledger, scope="b").record("0.05")
    assert budget.DollarBudget("1", ledger, scope="a").spent == Decimal("0.30")
    assert budget.DollarBudget("1", ledger, scope="b").spent == Decimal("0.05")
    assert budget.DollarBudget("1", ledger, scope="c").spent == 0
    assert budget.DollarBudget("1", ledger).spent == Decimal("0.35")


def test_without_a_ledger_nothing_is_written(tmp_path):
    b = budget.DollarBudget("1")
    b.record("0.5")
    assert b.spent == Decimal("0.5") and list(tmp_path.iterdir()) == []


def test_the_default_ledger_is_under_the_data_directory_outside_the_repo(monkeypatch, tmp_path):
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(tmp_path / "data"))
    path = budget.default_ledger()
    assert path == (tmp_path / "data").resolve() / "agent" / "ledger.jsonl"
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(config.REPO_ROOT / "inside"))
    with pytest.raises(config.ConfigError, match="inside the working copy"):
        budget.default_ledger()
