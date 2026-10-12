"""How many of its six calls each priced model gets on the default budget.

The budget is checked against the worst case of a call before it is sent, and the worst
case counts every byte of the request as a token. That bound is loose, so a model can be
stopped with most of its money unspent. This test measures it, on the marts fixture in a
`test_*` database: six model calls, five of them a query that returns 150 rows and the
sixth the answer, with the default limits of evals/warehouse.yml.

The model is scripted. What it "really" used is not measured, it is assumed, and the
assumption is written here: one input token per four bytes of the request, 300 output tokens
per call. The number of calls that fit depends on the bound far more than on that
assumption; the dollars spent depend on it entirely.

The default model must complete all six. For the others the number that fit is recorded
here and in docs/AGENT.md, and a test keeps the two equal.
"""

import json
from decimal import Decimal

import pytest

from agent import budget, llm, loop, tools, warehouse
from univ3_indexer import clickhouse as ch
from univ3_indexer import config

WAREHOUSE_YML = config.REPO_ROOT / "evals" / "warehouse.yml"
AGENT_DOC = config.REPO_ROOT / "docs" / "AGENT.md"
ROWS = 150
BYTES_PER_INPUT_TOKEN = 4  # an assumption, see the module docstring
OUTPUT_TOKENS_PER_CALL = 300  # an assumption too
QUERIES = [
    f"SELECT * FROM fct_pool_daily ORDER BY pool_address, block_date LIMIT {ROWS} OFFSET {skip}"
    for skip in (0, 7, 14, 21, 28)
]

# Measured by this test: model calls sent, out of six, before the budget refused the next.
CALLS_THAT_FIT = {
    "claude-haiku-5-5": 6,
    "claude-opus-5-5": 2,
    "claude-sonnet-5-5": 3,
}
# What those calls cost under the assumption above, to the cent, for the documentation.
# To the cent on purpose: the exact figure moves with every byte of the system prompt.
SPENT = {
    "claude-haiku-5-5": "0.01",
    "claude-opus-5-5": "0.05",
    "claude-sonnet-5-5": "0.06",
}


class SixTurns:
    """The same six turns for any model: five queries of 150 rows, then the answer."""

    def __init__(self, model: str):
        self.model = model
        self.calls = 0

    def complete(self, *, system, messages, tools, max_tokens):
        self.calls += 1
        size = len(json.dumps([system, messages, tools]).encode("utf-8"))
        usage = llm.Usage(
            input_tokens=size // BYTES_PER_INPUT_TOKEN, output_tokens=OUTPUT_TOKENS_PER_CALL
        )
        if self.calls <= len(QUERIES):
            call = llm.tool_use("run_sql", {"sql": QUERIES[self.calls - 1]}, f"q{self.calls}")
            return llm.response(call, usage=usage)
        last = json.loads(messages[-1]["content"][0]["content"])
        assert last["row_count"] == ROWS and last["truncated"] is False
        answer = {"type": "label", "value": last["rows"][0][0], "sql": QUERIES[-1]}
        return llm.response(llm.tool_use("submit_answer", answer), usage=usage)


@pytest.fixture(scope="module")
def measured(clickhouse, marts_database):
    """One run per priced model, with the limits of the real warehouse file."""
    real = warehouse.load(WAREHOUSE_YML)
    assert (real.max_usd, real.max_iterations) == (Decimal("0.25"), 6) and real.row_cap >= ROWS
    house = warehouse.Warehouse(
        marts_database, real.tables, real.row_cap, real.max_iterations, real.max_usd
    )
    client = ch.connect(database=marts_database)
    results = {}
    for model in llm.PRICES:
        results[model] = loop.run(
            "Which is it?",
            SixTurns(model),
            tools.Tools(client, house),
            budget.DollarBudget(house.max_usd),
            max_iterations=house.max_iterations,
            row_cap=house.row_cap,
        )
    return results


def test_every_model_with_a_price_is_measured():
    assert set(CALLS_THAT_FIT) == set(llm.PRICES) == set(SPENT)


def test_the_default_model_completes_all_six_calls_on_the_default_budget(measured):
    result = measured[llm.DEFAULT_MODEL]
    assert result.status == "answered", result.reason
    assert result.iterations == 6 == len(result.tool_calls)
    assert [c.summary["row_count"] for c in result.tool_calls[:5]] == [ROWS] * 5
    assert result.usd < Decimal("0.25") / 10  # and it is nowhere near the limit


@pytest.mark.parametrize("model", sorted(CALLS_THAT_FIT))
def test_how_many_calls_fit_is_what_is_recorded(measured, model):
    result = measured[model]
    assert result.iterations == CALLS_THAT_FIT[model]
    assert str(round(result.usd, 2)) == SPENT[model]
    if CALLS_THAT_FIT[model] < 6:
        # Stopped by the bound, not by the money: most of the budget was never spent.
        assert result.status == "error" and result.reason.startswith("budget: ")
        assert result.answer is None
        assert result.usd < Decimal("0.25")


@pytest.mark.parametrize("model", sorted(CALLS_THAT_FIT))
def test_the_documentation_says_the_same(model):
    """docs/AGENT.md has one row per model with the number recorded here."""
    row = f"| `{model}` | {CALLS_THAT_FIT[model]} of 6 | about ${SPENT[model]} |"
    assert row in AGENT_DOC.read_text(), row


# --- the ceiling of the variant that runs another model -------------------------------------


class Watching(budget.DollarBudget):
    """A budget that keeps, for every call, the room it was asked for: spent plus worst."""

    def __init__(self, max_usd):
        super().__init__(max_usd)
        self.room: list[Decimal] = []

    def check(self, worst_case):
        self.room.append(self.spent + Decimal(str(worst_case)))
        super().check(worst_case)


def test_the_sonnet_variant_has_a_ceiling_that_lets_all_six_calls_through(
    clickhouse, marts_database
):
    """evals/variants/sonnet.yml sets the model and the ceiling per question, nothing else.
    The ceiling is the room the sixth call of the six turns above needs, and a little over."""
    from evalkit import variants

    variant = variants.load("sonnet", config.REPO_ROOT / "evals" / "variants", config.REPO_ROOT)
    assert variant.model == "claude-sonnet-5-5" and variant.model in llm.PRICES
    assert (variant.descriptions, variant.prompt_addendum) == (None, "")
    assert set(variant.files) == {"evals/variants/sonnet.yml"}
    real = warehouse.load(WAREHOUSE_YML)
    house = warehouse.Warehouse(
        marts_database, real.tables, real.row_cap, real.max_iterations, real.max_usd
    )
    purse = Watching(variant.max_usd_per_question)
    result = loop.run(
        "Which is it?",
        SixTurns(variant.model),
        tools.Tools(ch.connect(database=marts_database), house),
        purse,
        max_iterations=house.max_iterations,
        row_cap=house.row_cap,
    )
    assert result.status == "answered" and result.iterations == 6, result.reason
    needed = max(purse.room)
    assert needed == purse.room[-1], "the sixth call is the one that needs the most room"
    # The figure written in the variant file, to the cent: it moves with the prompt.
    assert round(needed, 2) == Decimal("0.51")
    assert needed < variant.max_usd_per_question <= needed * Decimal("1.25")
    # And the default ceiling would not do: that is why the file sets one.
    assert needed > real.max_usd
