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
        for rates in filter(None, (price, price.long_prompt)):
            assert 0 < rates.cache_read < rates.input < rates.cache_write_5m < rates.cache_write_1h
            assert rates.input < rates.output
        assert (price.long_prompt is None) == (price.long_prompt_threshold is None)


def test_the_default_model_is_the_small_one():
    """The owner's choice. It is the only model in the table priced by prompt length."""
    assert llm.DEFAULT_MODEL == "claude-haiku-5-5"
    tiered = [m for m, p in llm.PRICES.items() if p.long_prompt is not None]
    assert tiered == ["claude-haiku-5-5"]
    price = llm.PRICES["claude-haiku-5-5"]
    assert price.long_prompt_threshold == 100_000 and price.read_on == "2026-10-11"
    assert all(
        getattr(price.long_prompt, kind) == 5 * getattr(price, kind)
        for kind in ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
    )


HAIKU = "claude-haiku-5-5"


def test_a_call_is_priced_by_its_own_prompt_length_on_both_sides_of_the_threshold():
    """Up to 100,000 prompt tokens the lower prices, one token more the higher ones, for
    every kind of token of that call, the output included. Worked out by hand."""
    # Exactly at the threshold. 60,000 x 0.10 + 40,000 x 0.01 + 1,000 x 0.50 = 6,900
    at = llm.Usage(input_tokens=60_000, cache_read_tokens=40_000, output_tokens=1_000)
    assert llm.prompt_tokens(at) == 100_000
    assert llm.cost_usd(HAIKU, at) == Decimal("0.0069")
    # One token over. 60,001 x 0.50 + 40,000 x 0.05 + 1,000 x 2.50 = 34,500.5
    over = llm.Usage(input_tokens=60_001, cache_read_tokens=40_000, output_tokens=1_000)
    assert llm.prompt_tokens(over) == 100_001
    assert llm.cost_usd(HAIKU, over) == Decimal("0.0345005")


def test_cache_reads_and_cache_writes_count_toward_the_threshold_and_output_does_not():
    # 50,000 + 30,000 + 20,001 = 100,001 prompt tokens, none of them a plain cache miss
    # over the line on its own. 50,000 x 0.50 + 30,000 x 0.625 + 20,001 x 1 = 63,751
    writes = llm.Usage(
        input_tokens=50_000, cache_write_5m_tokens=30_000, cache_write_1h_tokens=20_001
    )
    assert llm.cost_usd(HAIKU, writes) == Decimal("0.063751")
    # The same call one cache-write token shorter is at the lower prices:
    # 50,000 x 0.10 + 30,000 x 0.125 + 20,000 x 0.20 = 12,750
    under = llm.Usage(
        input_tokens=50_000, cache_write_5m_tokens=30_000, cache_write_1h_tokens=20_000
    )
    assert llm.cost_usd(HAIKU, under) == Decimal("0.01275")
    # 50,000 output tokens do not make a 100,000-token prompt long.
    # 100,000 x 0.10 + 50,000 x 0.50 = 35,000
    chatty = llm.Usage(input_tokens=100_000, output_tokens=50_000)
    assert llm.cost_usd(HAIKU, chatty) == Decimal("0.035")


def test_the_worst_case_takes_the_higher_prices_as_soon_as_the_ceiling_is_over():
    # 100,000 x 0.10 + 4,096 x 0.50 = 12,048
    assert llm.worst_case_usd(HAIKU, 100_000, 4096) == Decimal("0.012048")
    # 100,001 x 0.50 + 4,096 x 2.50 = 60,240.5
    assert llm.worst_case_usd(HAIKU, 100_001, 4096) == Decimal("0.0602405")


@pytest.mark.parametrize("ceiling", [1, 50_000, 99_999, 100_000, 100_001, 150_000, 400_000])
def test_the_worst_case_is_never_under_the_real_cost_of_a_call_within_the_ceiling(ceiling):
    """Whatever the call turns out to be, as long as its prompt is within the ceiling and
    its output within the cap. The cases include a ceiling over the threshold with a real
    prompt under it, and the other models, which have one set of prices."""
    for model in llm.PRICES:
        worst = llm.worst_case_usd(model, ceiling, 4096)
        for prompt in {1, ceiling // 2, min(ceiling, 100_000), min(ceiling, 100_001), ceiling}:
            for output in (0, 4096):
                real = llm.cost_usd(model, llm.Usage(input_tokens=prompt, output_tokens=output))
                assert real <= worst, (model, ceiling, prompt, output)


def test_a_model_with_one_set_of_prices_ignores_the_prompt_length():
    for model in ("claude-opus-5-5", "claude-sonnet-5-5"):
        price = llm.PRICES[model]
        assert price.rates_for(1) is price and price.rates_for(10_000_000) is price


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
    """Shaped like the SDK's: a status code, the parsed body, and a response with headers."""

    def __init__(self, status_code, body=None, retry_after=None):
        super().__init__(f"request with key {KEY} failed")
        self.status_code = status_code
        self.body = body
        waiting = {} if retry_after is None else {"retry-after": retry_after}
        self.response = types.SimpleNamespace(
            headers={"x-api-key": KEY, "request-id": "req_from_a_header", **waiting},
            request=types.SimpleNamespace(content=f"the request, with {KEY}"),
        )


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
            "model": "claude-haiku-5-5",
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


API_SAID = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "output_config.effort: this model\n does not   support it. " + "x" * 400,
    },
    "request_id": "req_in_the_body",
}


def test_an_error_status_carries_the_code_the_apis_error_type_and_the_start_of_its_message(sdk):
    """Built without a network: the three come from the body of the response, and nothing
    else of the exchange does. The key planted in the client is nowhere in the error."""
    sdk.answer = _APIStatusError(400, API_SAID)
    with pytest.raises(llm.LLMError) as err:
        llm.AnthropicLLM(KEY).complete(system="", messages=[], tools=[], max_tokens=1)
    error = err.value
    assert sdk.client["api_key"] == KEY  # the key was there to leak
    assert error.status_code == 400 and error.error_type == "invalid_request_error"
    expected = ("output_config.effort: this model does not support it. " + "x" * 400)[:300]
    assert error.detail == expected and len(error.detail) == 300
    assert str(error) == f"_APIStatusError: HTTP 400, invalid_request_error: {expected}"
    assert error.rejected is True
    for hidden in (KEY, "req_from_a_header", "req_in_the_body", "the request"):
        assert hidden not in str(error) and hidden not in repr(error.__dict__)
    assert error.__cause__ is None and error.__suppress_context__


@pytest.mark.parametrize(
    ("status", "body", "says", "rejected"),
    [
        (429, {"error": {"type": "rate_limit_error", "message": "Slow down"}},
         "_APIStatusError: HTTP 429, rate_limit_error: Slow down", True),
        (529, {"error": {"type": "overloaded_error", "message": "Overloaded"}},
         "_APIStatusError: HTTP 529, overloaded_error: Overloaded", True),
        (502, "<html>bad gateway</html>", "_APIStatusError: HTTP 502", False),
        (400, None, "_APIStatusError: HTTP 400", True),
        (400, {"error": "not an object"}, "_APIStatusError: HTTP 400", True),
        (400, {"error": {"type": 7, "message": ["x"]}}, "_APIStatusError: HTTP 400", True),
        (400, {"error": {"type": "invalid_request_error"}},
         "_APIStatusError: HTTP 400, invalid_request_error", True),
    ],
)  # fmt: skip
def test_what_an_error_says_for_each_shape_of_body(sdk, status, body, says, rejected):
    sdk.answer = _APIStatusError(status, body)
    with pytest.raises(llm.LLMError) as err:
        llm.AnthropicLLM(KEY).complete(system="", messages=[], tools=[], max_tokens=1)
    assert str(err.value) == says and err.value.rejected is rejected
    assert err.value.status_code == status and KEY not in str(err.value)


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        ("7", 7.0),
        ("0.5", 0.5),
        ("0", 0.0),
        (None, None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),  # the date form is not read
        ("-3", None),
        ("nan", None),
        ("soon", None),
    ],
)
@pytest.mark.parametrize("status", [429, 529])
def test_the_retry_after_header_is_read_as_seconds_and_no_other_header_is(
    sdk, status, header, seconds
):
    sdk.answer = _APIStatusError(status, {"error": {"type": "x", "message": "m"}}, header)
    with pytest.raises(llm.LLMError) as err:
        llm.AnthropicLLM(KEY).complete(system="", messages=[], tools=[], max_tokens=1)
    assert err.value.retry_after == seconds
    assert err.value.rate_limited is True and err.value.rejected is True
    for hidden in (KEY, "req_from_a_header"):
        assert hidden not in str(err.value) and hidden not in repr(err.value.__dict__)


def test_only_429_and_529_are_rate_limits():
    assert llm.RATE_LIMIT_STATUSES == (429, 529)
    for status, limited, rejected in [(429, True, True), (529, True, True), (400, False, True),
                                      (500, False, False), (503, False, False),
                                      (None, False, False)]:  # fmt: skip
        error = llm.LLMError("x", status_code=status)
        assert (error.rate_limited, error.rejected) == (limited, rejected), status
    assert llm.retry_after_seconds(None) is None and llm.retry_after_seconds({}) is None


def test_a_timeout_has_no_status_and_is_not_a_rejection(sdk):
    sdk.answer = _APITimeoutError("slow")
    with pytest.raises(llm.LLMError) as err:
        llm.AnthropicLLM(KEY).complete(system="", messages=[], tools=[], max_tokens=1)
    assert (err.value.status_code, err.value.error_type, err.value.detail) == (None, None, "")
    assert err.value.rejected is False


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
