"""The model interface: the price table, cost arithmetic, the SDK wrapper, the script.

Nothing here touches the network. The SDK wrapper is exercised against a stand-in module, so
these tests run with or without the optional `agent` dependency group installed.
"""

import re
import sys
import types
from decimal import Decimal

import pytest

from agent import llm

USAGE = llm.Usage(
    input_tokens=1200,
    output_tokens=350,
    cache_read_tokens=5000,
    cache_write_5m_tokens=800,
    cache_write_1h_tokens=100,
)

# --- prices ----------------------------------------------------------------------------


def test_every_price_says_where_and_when_it_was_read():
    assert llm.DEFAULT_MODEL in llm.PRICES
    for model, price in llm.PRICES.items():
        assert re.fullmatch(r"claude-[a-z]+-\d+-\d+", model)
        assert price.id_source == llm.MODELS_URL and price.price_source == llm.PRICING_URL
        assert price.id_source.startswith("https://platform.claude.com/docs/")
        assert re.fullmatch(r"\d{4}-\d\d-\d\d", price.read_on)
        assert 0 < price.cache_read < price.input < price.cache_write_5m < price.cache_write_1h
        assert price.input < price.output


def test_cost_arithmetic_against_the_price_table():
    """Each kind of token at its own price, summed, in dollars. Worked out by hand below."""
    # 1200 x 4 + 350 x 20 + 5000 x 0.20 + 800 x 5 + 100 x 8 = 17,600 millionths of a dollar
    assert llm.cost_usd("claude-opus-5-5", USAGE) == Decimal("0.0176")
    # 1200 x 2 + 350 x 10 + 5000 x 0.10 + 800 x 2.50 + 100 x 4 = 8,800
    assert llm.cost_usd("claude-sonnet-5-5", USAGE) == Decimal("0.0088")
    assert llm.cost_usd("claude-opus-5-5", llm.Usage()) == 0
    one_each = llm.Usage(1, 1, 1, 1, 1)
    assert llm.cost_usd("claude-opus-5-5", one_each) == Decimal("0.0000372")
    # A million of each kind is the sum of the table's row.
    row = llm.PRICES["claude-opus-5-5"]
    million = llm.Usage(*(5 * [1_000_000]))
    assert llm.cost_usd("claude-opus-5-5", million) == (
        row.input + row.output + row.cache_read + row.cache_write_5m + row.cache_write_1h
    )


def test_usage_adds_up_field_by_field():
    assert USAGE + USAGE == llm.Usage(2400, 700, 10000, 1600, 200)
    assert llm.cost_usd("claude-opus-5-5", USAGE + USAGE) == Decimal("0.0352")


def test_worst_case_is_all_the_input_and_the_whole_output_cap():
    # 10,000 x 4 + 4,096 x 20 = 121,920 millionths
    assert llm.worst_case_usd("claude-opus-5-5", 10_000, 4096) == Decimal("0.12192")
    assert llm.worst_case_usd("claude-sonnet-5-5", 10_000, 4096) == Decimal("0.06096")
    real = llm.cost_usd("claude-opus-5-5", llm.Usage(input_tokens=10_000, output_tokens=4096))
    assert real == llm.worst_case_usd("claude-opus-5-5", 10_000, 4096)


def test_the_input_ceiling_is_at_least_the_bytes_of_the_request():
    system, tools = "s" * 100, [{"name": "t", "description": "d" * 50}]
    messages = [{"role": "user", "content": "ñ" * 10}]
    ceiling = llm.input_token_ceiling(system, messages, tools)
    assert ceiling >= 100 + 50 + 20 + llm.REQUEST_OVERHEAD_TOKENS
    longer = llm.input_token_ceiling(system, [*messages, {"role": "user", "content": "x"}], tools)
    assert longer > ceiling

    class Block:  # an SDK object in the conversation counts through its own dump
        def model_dump(self, mode):
            return {"type": "thinking", "signature": "z" * 1000}

    with_block = [*messages, {"role": "assistant", "content": [Block()]}]
    assert llm.input_token_ceiling(system, with_block, tools) >= ceiling + 1000


def test_a_model_without_a_price_is_refused_with_the_way_to_add_it():
    for call in (
        lambda: llm.price_of("claude-made-up-9"),
        lambda: llm.cost_usd("claude-made-up-9", USAGE),
        lambda: llm.worst_case_usd("claude-made-up-9", 1, 1),
        lambda: llm.AnthropicLLM("not-a-key", "claude-made-up-9"),
    ):
        with pytest.raises(llm.UnknownModel) as err:
            call()
        assert "claude-made-up-9" in str(err.value) and "claude-opus-5-5" in str(err.value)
        assert llm.PRICING_URL in str(err.value)


# --- the SDK wrapper, against a stand-in for the SDK -------------------------------------

KEY = "not-a-real-key-0123456789"


class _APIError(Exception):
    pass


class _APIStatusError(_APIError):
    def __init__(self, status_code):
        super().__init__(f"request with key {KEY} failed")
        self.status_code = status_code


class _RateLimitError(_APIStatusError):
    pass


class _APITimeoutError(_APIError):
    pass


def _block(**fields):
    return types.SimpleNamespace(**fields)


@pytest.fixture
def sdk(monkeypatch):
    """A module that looks enough like `anthropic` to see what the wrapper does with it."""
    seen = types.SimpleNamespace(client=None, requests=[], answer=None)

    class Messages:
        def create(self, **kwargs):
            seen.requests.append(kwargs)
            if isinstance(seen.answer, Exception):
                raise seen.answer
            return seen.answer

    class Anthropic:
        def __init__(self, **kwargs):
            seen.client = kwargs
            self.messages = Messages()

    module = types.ModuleType("anthropic")
    module.Anthropic = Anthropic
    module.APIError, module.APIStatusError = _APIError, _APIStatusError
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return seen


def test_the_client_never_retries_and_has_an_explicit_timeout(sdk):
    llm.AnthropicLLM(KEY)
    assert sdk.client == {"api_key": KEY, "max_retries": 0, "timeout": 120.0}
    llm.AnthropicLLM(KEY, "claude-sonnet-5-5", timeout_seconds=30.0)
    assert sdk.client["timeout"] == 30.0 and sdk.client["max_retries"] == 0
    with pytest.raises(llm.LLMError, match="empty API key"):
        llm.AnthropicLLM("")


def test_a_call_sends_what_it_was_given_and_maps_what_comes_back(sdk):
    thinking = _block(type="thinking", thinking="", signature="opaque")
    content = [
        thinking,
        _block(type="text", text="Looking."),
        _block(type="tool_use", id="toolu_1", name="run_sql", input={"sql": "SELECT 1"}),
    ]
    sdk.answer = _block(
        content=content,
        stop_reason="tool_use",
        usage=_block(
            input_tokens=1200,
            output_tokens=350,
            cache_read_input_tokens=5000,
            cache_creation_input_tokens=900,
            cache_creation=_block(ephemeral_5m_input_tokens=800, ephemeral_1h_input_tokens=100),
        ),
    )
    model = llm.AnthropicLLM(KEY)
    messages, tools = [{"role": "user", "content": "q"}], [{"name": "run_sql"}]
    out = model.complete(system="sys", messages=messages, tools=tools, max_tokens=4096)
    assert sdk.requests == [
        {
            "model": "claude-opus-5-5",
            "max_tokens": 4096,
            "system": "sys",
            "tools": tools,
            "messages": messages,
            "output_config": {"effort": "medium"},
        }
    ]
    assert out.content == (
        {"type": "text", "text": "Looking."},
        {"type": "tool_use", "id": "toolu_1", "name": "run_sql", "input": {"sql": "SELECT 1"}},
    )
    assert out.usage == USAGE and out.stop_reason == "tool_use"
    # The assistant turn goes back exactly as the SDK gave it, the unread blocks included.
    assert out.assistant_content() is content and out.assistant_content()[0] is thinking


def test_usage_without_cache_fields_is_plain_input_and_output(sdk):
    sdk.answer = _block(
        content=[], stop_reason="end_turn", usage=_block(input_tokens=10, output_tokens=2)
    )
    out = llm.AnthropicLLM(KEY).complete(system="", messages=[], tools=[], max_tokens=1)
    assert out.usage == llm.Usage(input_tokens=10, output_tokens=2)


@pytest.mark.parametrize(
    ("raised", "says"),
    [
        (_RateLimitError(429), "_RateLimitError: HTTP 429"),
        (_APITimeoutError("slow"), "_APITimeoutError"),
    ],
)
def test_an_sdk_error_becomes_one_short_error_without_the_key(sdk, raised, says):
    sdk.answer = raised
    with pytest.raises(llm.LLMError) as err:
        llm.AnthropicLLM(KEY).complete(system="", messages=[], tools=[], max_tokens=1)
    assert str(err.value) == says and KEY not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert len(sdk.requests) == 1  # one attempt, no retry


# --- the script --------------------------------------------------------------------------


def test_the_scripted_llm_replays_in_order_and_remembers_what_it_was_asked():
    first = llm.response(llm.tool_use("run_sql", {"sql": "SELECT 1"}))
    second = llm.response(llm.text("done"), usage=USAGE)
    scripted = llm.ScriptedLLM([first, RuntimeError("down"), second])
    assert first.stop_reason == "tool_use" and second.stop_reason == "end_turn"
    messages = [{"role": "user", "content": "q"}]
    assert scripted.complete(system="s", messages=messages, tools=[], max_tokens=5) is first
    messages.append({"role": "user", "content": "more"})
    with pytest.raises(RuntimeError, match="down"):
        scripted.complete(system="s", messages=messages, tools=[], max_tokens=5)
    assert scripted.complete(system="s", messages=messages, tools=[], max_tokens=5) is second
    assert [len(call["messages"]) for call in scripted.calls] == [1, 2, 2]
    assert scripted.model == llm.DEFAULT_MODEL and first.assistant_content() == list(first.content)
    with pytest.raises(AssertionError, match="no response left"):
        scripted.complete(system="s", messages=messages, tools=[], max_tokens=5)
