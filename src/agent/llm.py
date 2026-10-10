"""The model behind the agent: a small interface, one real implementation, one scripted.

The loop only ever sees ``LLM``: messages and tools go in, content blocks and token usage
come out. ``AnthropicLLM`` is the implementation on the official SDK. ``ScriptedLLM`` replays
a fixed list of responses, so every path of the loop can be tested without a network.

Model ids and prices are never written from memory. Each one in ``PRICES`` was read from
the official page named next to it, on the date next to it.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

MODELS_URL = "https://platform.claude.com/docs/en/about-claude/models/overview"
PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens, and where and when they were read."""

    input: Decimal
    cache_write_5m: Decimal
    cache_write_1h: Decimal
    cache_read: Decimal
    output: Decimal
    id_source: str
    price_source: str
    read_on: str


def _price(input_: str, write_5m: str, write_1h: str, read: str, output: str) -> Price:
    return Price(
        Decimal(input_),
        Decimal(write_5m),
        Decimal(write_1h),
        Decimal(read),
        Decimal(output),
        id_source=MODELS_URL,  # the "Claude API ID" row of the models table
        price_source=PRICING_URL,  # the "Model pricing" table
        read_on="2026-10-10",
    )


# Columns of the pricing table, in its order: base input tokens, 5m cache writes, 1h cache
# writes, cache hits and refreshes, output tokens. All in USD per million tokens.
PRICES: dict[str, Price] = {
    # id: MODELS_URL, read 2026-10-10. prices: PRICING_URL, read 2026-10-10.
    "claude-opus-5-5": _price("4", "5", "8", "0.20", "20"),
    # id: MODELS_URL, read 2026-10-10. prices: PRICING_URL, read 2026-10-10.
    "claude-sonnet-5-5": _price("2", "2.50", "4", "0.10", "10"),
}
DEFAULT_MODEL = "claude-opus-5-5"

# Tokens the API adds around a request that are not in its text (the instructions that go
# with tool definitions, message framing). An allowance, on the generous side.
REQUEST_OVERHEAD_TOKENS = 2_000


class UnknownModel(ValueError):
    """No price is recorded for this model id, so its cost cannot be bounded or computed."""


class LLMError(RuntimeError):
    """A model call failed. The message never holds the key or the request."""


def price_of(model: str) -> Price:
    try:
        return PRICES[model]
    except KeyError:
        known = ", ".join(sorted(PRICES))
        raise UnknownModel(
            f"no price is recorded for model {model!r}; the ones with a price are: {known}. "
            f"Add it to PRICES in src/agent/llm.py from {MODELS_URL} and {PRICING_URL}, "
            "with the date it was read"
        ) from None


@dataclass(frozen=True)
class Usage:
    """Tokens of one call, as billed. ``input_tokens`` excludes the cached ones."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_5m_tokens + other.cache_write_5m_tokens,
            self.cache_write_1h_tokens + other.cache_write_1h_tokens,
        )


def cost_usd(model: str, usage: Usage) -> Decimal:
    """What a call cost, exactly: every kind of token at its own price."""
    p = price_of(model)
    return (
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_read_tokens * p.cache_read
        + usage.cache_write_5m_tokens * p.cache_write_5m
        + usage.cache_write_1h_tokens * p.cache_write_1h
    ) / MILLION


def input_token_ceiling(system: str, messages: list, tools: list) -> int:
    """An upper bound on the input tokens of a request, computed without sending anything.

    A token is at least one byte of text, so the bytes of the serialised request bound its
    tokens from above; ``REQUEST_OVERHEAD_TOKENS`` covers what the API adds around it. The
    bound is loose, often three or four times the real count. That is the price of checking
    the budget before the call instead of after it.
    """

    def plain(value: object) -> object:
        dump = getattr(value, "model_dump", None)
        return dump(mode="json") if callable(dump) else str(value)

    text = json.dumps([system, messages, tools], default=plain, ensure_ascii=False)
    return len(text.encode("utf-8")) + REQUEST_OVERHEAD_TOKENS


def worst_case_usd(model: str, input_ceiling: int, max_tokens: int) -> Decimal:
    """The most a call can cost: every input token at the base rate, the whole output cap.

    Input is priced at the base rate because the requests built here carry no cache
    breakpoint, so nothing can be billed as a cache write.
    """
    p = price_of(model)
    return (input_ceiling * p.input + max_tokens * p.output) / MILLION


@dataclass(frozen=True)
class Response:
    """What came back from one call.

    ``content`` holds the blocks the loop acts on, as plain dicts: ``{"type": "text",
    "text": ...}`` and ``{"type": "tool_use", "id": ..., "name": ..., "input": {...}}``.
    ``replay`` is what must be appended to the conversation as the assistant's turn. For the
    real implementation that is the SDK's own content, unchanged, because it carries blocks
    the loop does not read but the API needs back as they were.
    """

    content: tuple[dict, ...]
    usage: Usage
    stop_reason: str
    replay: object = None

    def assistant_content(self) -> object:
        return list(self.content) if self.replay is None else self.replay


class LLM(Protocol):
    model: str

    def complete(
        self, *, system: str, messages: list, tools: list, max_tokens: int
    ) -> Response: ...


class AnthropicLLM:
    """The official SDK, with no automatic retry and an explicit timeout.

    No retry: a retried request is a second billed request the budget did not approve. The
    loop books a failed call at its worst case and stops.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        timeout_seconds: float = 120.0,
        effort: str = "medium",
    ):
        price_of(model)  # refuse a model without a recorded price before anything is sent
        if not api_key:
            raise LLMError("empty API key")
        import anthropic  # the optional `agent` dependency group

        self.model = model
        self._effort = effort
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=timeout_seconds)

    def complete(self, *, system: str, messages: list, tools: list, max_tokens: int) -> Response:
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": self._effort},
            )
        except self._anthropic.APIStatusError as exc:
            raise LLMError(f"{type(exc).__name__}: HTTP {exc.status_code}") from None
        except self._anthropic.APIError as exc:  # timeouts and connection errors
            raise LLMError(type(exc).__name__) from None
        blocks = []
        for block in message.content:
            if block.type == "text":
                blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                blocks.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
        usage = message.usage
        written = getattr(usage, "cache_creation", None)
        write_1h = getattr(written, "ephemeral_1h_input_tokens", 0) or 0
        write_all = getattr(usage, "cache_creation_input_tokens", 0) or 0
        return Response(
            content=tuple(blocks),
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_5m_tokens=max(write_all - write_1h, 0),
                cache_write_1h_tokens=write_1h,
            ),
            stop_reason=message.stop_reason or "",
            replay=message.content,
        )


def text(body: str) -> dict:
    return {"type": "text", "text": body}


def tool_use(name: str, input_: dict, id_: str = "") -> dict:
    return {"type": "tool_use", "id": id_ or f"call_{name}", "name": name, "input": input_}


def response(*blocks: dict, usage: Usage | None = None, stop_reason: str = "") -> Response:
    """A response for a script: the stop reason follows from the blocks unless given."""
    if not stop_reason:
        called = any(block["type"] == "tool_use" for block in blocks)
        stop_reason = "tool_use" if called else "end_turn"
    return Response(tuple(blocks), usage or Usage(), stop_reason)


class ScriptedLLM:
    """Replays a fixed list of responses, in order. An exception in the list is raised.

    ``calls`` keeps a copy of what each call was given, for the tests to look at.
    """

    def __init__(self, script: list[Response | Exception], model: str = DEFAULT_MODEL):
        self.model = model
        self._script = list(script)
        self.calls: list[dict] = []

    def complete(self, *, system: str, messages: list, tools: list, max_tokens: int) -> Response:
        self.calls.append(
            {
                "system": system,
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
                "max_tokens": max_tokens,
            }
        )
        if not self._script:
            raise AssertionError("the script has no response left for this call")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
