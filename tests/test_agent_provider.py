"""A second provider, through the same SDK. A stand-in for the SDK, no network.

What is checked: where the requests go and what they carry, what the gateway's own account
of a call is and how it is read, that an empty wallet is an error and not an answer, and
that nothing here ever turns to the other provider.
"""

import dataclasses
import sys
import types
from decimal import Decimal

import pytest

from agent import budget, llm, loop

SONNET_DIRECT, SONNET_GATEWAY = "claude-sonnet-5-5", "claude-sonnet-5.5"


class Block:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def a_message(**extra):
    usage = Block(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0,
                  cache_creation_input_tokens=0, cache_creation=None)  # fmt: skip
    block = Block(type="tool_use", id="t1", name="describe_schema", input={})
    return Block(content=[block], usage=usage, stop_reason="tool_use", **extra)


class APIError(Exception):
    pass


class APIStatusError(APIError):
    def __init__(self, status_code, body, headers=None):
        super().__init__(f"HTTP {status_code}")
        self.status_code, self.body = status_code, body
        self.response = Block(headers=headers or {})


@pytest.fixture
def sdk(monkeypatch):
    """A module named `anthropic` that records every client built and every call made."""
    made = types.SimpleNamespace(clients=[], calls=[], answer=None, headers={})

    class Raw:
        def __init__(self, message):
            self.headers, self._message = dict(made.headers), message

        def parse(self):
            return self._message

    class Messages:
        def __init__(self, raw):
            self._raw = raw
            if not raw:
                self.with_raw_response = Messages(raw=True)

        def create(self, **request):
            made.calls.append({"raw": self._raw, **request})
            if isinstance(made.answer, Exception):
                raise made.answer
            return Raw(made.answer) if self._raw else made.answer

    class Anthropic:
        def __init__(self, **options):
            made.clients.append(options)
            self.messages = Messages(raw=False)

    module = types.ModuleType("anthropic")
    module.Anthropic, module.APIError, module.APIStatusError = Anthropic, APIError, APIStatusError
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return made


def ask(client):
    return client.complete(system="s", messages=[{"role": "user", "content": "q"}], tools=[],
                           max_tokens=100)  # fmt: skip


def test_the_default_provider_is_the_one_there_was_and_the_client_is_built_as_before(sdk):
    sdk.answer = a_message(model=SONNET_DIRECT)
    client = llm.AnthropicLLM("key-a", SONNET_DIRECT)
    assert client.provider.name == llm.DEFAULT_PROVIDER == "anthropic"
    assert sdk.clients == [{"api_key": "key-a", "max_retries": 0, "timeout": 120.0}]
    response = ask(client)
    assert [call["raw"] for call in sdk.calls] == [False]
    assert response.served_model == SONNET_DIRECT
    assert response.billed_usd is None and response.reports == ()
    assert client.may_write_cache is False


def test_the_gateway_gets_its_own_base_url_its_own_key_and_one_header(sdk):
    sdk.answer = a_message(
        model=SONNET_GATEWAY,
        cheaper_inference={"request_id": "r", "billing": {"billed_cost_usd": "0.001950"}},
    )
    sdk.headers = {"x-ci-cache": "miss", "x-ci-discount-percent": "35", "set-cookie": "secret"}
    client = llm.AnthropicLLM("key-b", SONNET_GATEWAY, provider="cheaperinference")
    # One client, with the gateway's address and no /v1: the SDK appends /v1/messages and
    # puts the key in X-Api-Key, as it does for Anthropic.
    assert sdk.clients == [
        {
            "api_key": "key-b",
            "max_retries": 0,
            "timeout": 120.0,
            "base_url": "https://api.cheaperinference.com",
            "default_headers": {"x-ci-prompt-cache": "off"},
        }
    ]
    response = ask(client)
    (call,) = sdk.calls
    assert call["raw"] is True and call["model"] == SONNET_GATEWAY  # the gateway's own id
    assert response.served_model == SONNET_GATEWAY
    assert response.billed_usd == Decimal("0.001950")
    # Only the headers asked for are kept, and only when they were sent.
    assert dict(response.reports) == {"x-ci-cache": "miss", "x-ci-discount-percent": "35"}
    assert client.may_write_cache is True


def test_the_billed_cost_is_read_from_the_response_or_taken_as_not_said():
    def said(value):
        return {"cheaper_inference": {"billing": {"billed_cost_usd": value}}}

    assert llm.billed_usd(said("0.012345")) == Decimal("0.012345")
    assert llm.billed_usd(said(0)) == Decimal(0)
    billing = Block(billing=Block(billed_cost_usd="0.5"))
    assert llm.billed_usd(Block(cheaper_inference=billing)) == Decimal("0.5")  # as objects
    for nothing in ({}, {"cheaper_inference": None}, {"cheaper_inference": {"billing": {}}},
                    said(None), said("soon"), said("NaN"), said("-1"), said(True)):  # fmt: skip
        assert llm.billed_usd(nothing) is None, nothing


def test_a_model_id_is_never_sent_to_the_provider_it_is_not_of(sdk):
    with pytest.raises(llm.UnknownProvider, match="is cheaperinference's"):
        llm.AnthropicLLM("key-a", SONNET_GATEWAY)  # the gateway's id, to Anthropic
    with pytest.raises(llm.UnknownProvider, match="is anthropic's"):
        llm.AnthropicLLM("key-b", SONNET_DIRECT, provider="cheaperinference")
    with pytest.raises(llm.UnknownProvider, match="no provider named 'elsewhere'"):
        llm.AnthropicLLM("key", SONNET_DIRECT, provider="elsewhere")
    assert sdk.clients == [], "refused before a client was built"
    assert set(llm.MODEL_PROVIDER.values()) <= set(llm.PROVIDERS)
    assert set(llm.GATEWAY_PRICES) == set(llm.MODEL_PROVIDER)
    assert not set(llm.GATEWAY_PRICES) & set(llm.PRICES)


def test_the_gateway_price_says_where_and_when_it_was_read_and_is_under_the_direct_one():
    gateway, direct = llm.price_of(SONNET_GATEWAY), llm.price_of(SONNET_DIRECT)
    assert gateway.price_source == llm.CATALOG_URL == "https://www.cheaperinference.com/markets"
    assert gateway.read_on == "2026-10-13"
    assert (gateway.input, gateway.output) == (Decimal("1.30"), Decimal("6.50"))
    assert (gateway.cache_read, gateway.cache_write_5m) == (Decimal("0.13"), Decimal("1.63"))
    assert gateway.input < direct.input and gateway.output < direct.output


def test_an_empty_wallet_is_an_error_of_the_call_and_nothing_is_sent_anywhere_else(sdk):
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "no funds"}}
    sdk.answer = APIStatusError(402, body)
    client = llm.AnthropicLLM("key-b", SONNET_GATEWAY, provider="cheaperinference")
    with pytest.raises(llm.LLMError) as caught:
        ask(client)
    assert caught.value.status_code == 402 and caught.value.rejected
    assert "HTTP 402" in str(caught.value) and "key-b" not in str(caught.value)
    # One client was built and one call was made: there is no other provider to turn to.
    assert len(sdk.clients) == 1 and len(sdk.calls) == 1
    # Through the loop it ends the question as an error, booked at zero, with no answer.
    purse = budget.DollarBudget("5")
    result = loop.run("How much?", client, object(), purse)
    assert result.status == "error" and "HTTP 402" in result.reason
    assert result.answer is None and result.usd == 0 == purse.spent
    assert len(sdk.clients) == 1


def test_what_the_provider_reported_is_kept_with_the_result_call_by_call():
    class Tools:
        def describe_schema(self, tables=None):
            return {"ok": True, "database": "d", "tables": {}}

    def reported(response, billed, served, cache):
        return dataclasses.replace(
            response, billed_usd=billed, served_model=served, reports=(("x-ci-cache", cache),)
        )

    usage = llm.Usage(input_tokens=1000, output_tokens=100)
    script = [
        reported(llm.response(llm.tool_use("describe_schema", {}), usage=usage),
                 Decimal("0.001950"), SONNET_GATEWAY, "miss"),
        reported(llm.response(llm.tool_use("submit_answer", {"type": "refusal",
                                                             "refusal_reason": "Not there."}),
                              usage=usage), Decimal("0.002000"), SONNET_GATEWAY, "miss"),
    ]  # fmt: skip
    result = loop.run("How much?", llm.ScriptedLLM(script, SONNET_GATEWAY), Tools(),
                      budget.DollarBudget("5")).to_json()  # fmt: skip
    assert result["billed_usd"] == "0.003950"
    assert result["served_models"] == [SONNET_GATEWAY]
    assert result["reports"] == {"x-ci-cache": ["miss"]}
    # 2 x (1,000 x 1.30 + 100 x 6.50) per million, from the price table: 0.0039.
    assert Decimal(result["usd"]) == Decimal("0.0039")
    # A provider that reports nothing leaves nothing: the result says so, it does not guess.
    refusal = {"type": "refusal", "refusal_reason": "Not there."}
    plain = [llm.response(llm.tool_use("submit_answer", refusal))]
    quiet = loop.run("How much?", llm.ScriptedLLM(plain, SONNET_DIRECT), Tools(),
                     budget.DollarBudget("5")).to_json()  # fmt: skip
    assert quiet["billed_usd"] is None and quiet["served_models"] == []
    assert quiet["reports"] == {}


def test_a_provider_that_may_cache_has_its_worst_case_priced_as_a_cache_write():
    class Refusing(budget.DollarBudget):
        asked: list = []

        def check(self, worst_case):
            self.asked.append(Decimal(str(worst_case)))
            super().check(worst_case)

    model = llm.ScriptedLLM([llm.response(llm.tool_use("describe_schema", {}))], SONNET_GATEWAY)
    model.may_write_cache = True
    purse = Refusing("0.0000001")
    result = loop.run("How much?", model, object(), purse)
    assert result.status == "error" and result.reason.startswith("budget:")
    first = [{"role": "user", "content": "How much?"}]
    ceiling = llm.input_token_ceiling(
        loop.system_prompt(loop.DEFAULT_MAX_ITERATIONS, 200), first, loop.TOOL_DEFINITIONS
    )
    dear = llm.worst_case_usd(SONNET_GATEWAY, ceiling, loop.DEFAULT_MAX_TOKENS, True)
    assert purse.asked == [dear] and dear > llm.worst_case_usd(
        SONNET_GATEWAY, ceiling, loop.DEFAULT_MAX_TOKENS
    )
