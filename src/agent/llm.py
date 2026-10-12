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
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

MODELS_URL = "https://platform.claude.com/docs/en/about-claude/models/overview"
PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Rates:
    """Dollars per million tokens, one price per kind of token."""

    input: Decimal
    cache_write_5m: Decimal
    cache_write_1h: Decimal
    cache_read: Decimal
    output: Decimal


@dataclass(frozen=True)
class Price(Rates):
    """The prices of one model, and where and when they were read.

    A model priced by prompt length has a second set of prices, ``long_prompt``, for a
    request whose prompt is over ``long_prompt_threshold`` tokens. The prompt length of a
    request counts all of its input tokens, cache reads and cache writes included, and a
    request over the threshold pays the higher prices for every kind of token, the output
    too.
    """

    id_source: str = ""
    price_source: str = ""
    read_on: str = ""
    long_prompt_threshold: int | None = None
    long_prompt: Rates | None = None

    def rates_for(self, prompt_tokens: int) -> Rates:
        """The prices a request with this many prompt tokens is billed at."""
        if self.long_prompt is not None and prompt_tokens > self.long_prompt_threshold:
            return self.long_prompt
        return self


def _rates(input_: str, write_5m: str, write_1h: str, read: str, output: str) -> Rates:
    return Rates(*(Decimal(x) for x in (input_, write_5m, write_1h, read, output)))


def _price(
    *rates: str, read_on: str, over: int | None = None, long_prompt: Rates | None = None
) -> Price:
    return Price(
        *(Decimal(x) for x in rates),
        id_source=MODELS_URL,  # the "Claude API ID" row of the models table
        price_source=PRICING_URL,  # the "Model pricing" table and "Long context pricing"
        read_on=read_on,
        long_prompt_threshold=over,
        long_prompt=long_prompt,
    )


# Columns of the pricing table, in its order: base input tokens, 5m cache writes, 1h cache
# writes, cache hits and refreshes, output tokens. All in USD per million tokens.
PRICES: dict[str, Price] = {
    # id: MODELS_URL, read 2026-10-11. prices: PRICING_URL, read 2026-10-11. Two rows in the
    # table: "for prompts up to 100,000 tokens" and "for prompts over 100,000 tokens". What
    # counts, from "Long context pricing" on the same page: "A request's prompt length
    # counts all of its input tokens, including cache reads and cache writes. Each request
    # is priced on its own".
    "claude-haiku-5-5": _price(
        "0.10", "0.125", "0.20", "0.01", "0.50",
        read_on="2026-10-11",
        over=100_000,
        long_prompt=_rates("0.50", "0.625", "1", "0.05", "2.50"),
    ),
    # id: MODELS_URL, read 2026-10-10. prices: PRICING_URL, read 2026-10-10.
    "claude-opus-5-5": _price("4", "5", "8", "0.20", "20", read_on="2026-10-10"),
    # id: MODELS_URL, read 2026-10-10. prices: PRICING_URL, read 2026-10-10.
    "claude-sonnet-5-5": _price("2", "2.50", "4", "0.10", "10", read_on="2026-10-10"),
}  # fmt: skip
# The owner's choice: the small model is the agent.
DEFAULT_MODEL = "claude-haiku-5-5"

# Tokens the API adds around a request that are not in its text (the instructions that go
# with tool definitions, message framing). An allowance, on the generous side.
REQUEST_OVERHEAD_TOKENS = 2_000


class UnknownModel(ValueError):
    """No price is recorded for this model id, so its cost cannot be bounded or computed."""


ERROR_MESSAGE_CHARS = 300
# The two statuses with which the API says "not now": too many requests, and overloaded.
# Neither request was served, so neither was billed.
RATE_LIMIT_STATUSES = (429, 529)


class LLMError(RuntimeError):
    """A model call failed. The message never holds the key, the request or a header.

    When the API answered with an error status, ``status_code`` is that status,
    ``error_type`` the API's own name for the error and ``detail`` the start of its message,
    all three read from the body of the response. ``retry_after`` is the number of seconds
    in the ``retry-after`` header of that response, when it has one: one number, and the
    only thing read from the headers. For a timeout or a connection error there was no
    answer, and all four are empty.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
        detail: str = "",
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status_code, self.error_type, self.detail = status_code, error_type, detail
        self.retry_after = retry_after

    @property
    def rate_limited(self) -> bool:
        """The API answered 429 or 529: the request was not served, and may be sent again."""
        return self.status_code in RATE_LIMIT_STATUSES

    @property
    def rejected(self) -> bool:
        """The API refused the request, with a 4xx status or a 529: it was not served."""
        if self.status_code is None:
            return False
        return 400 <= self.status_code < 500 or self.rate_limited


def retry_after_seconds(headers: object) -> float | None:
    """The ``retry-after`` header as seconds, when it is a plain non-negative number.

    The header may also be a date; that form is not read, and gives None like no header.
    """
    get = getattr(headers, "get", None)
    raw = get("retry-after") if callable(get) else None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _api_error(body: object) -> tuple[str | None, str]:
    """The error type and the start of the message, from the body of an error response.

    Only the two fields the API documents for an error are read. Anything else in the body,
    and everything outside it, is left where it is.
    """
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None, ""
    kind, message = error.get("type"), error.get("message")
    return (
        kind if isinstance(kind, str) else None,
        " ".join(message.split())[:ERROR_MESSAGE_CHARS] if isinstance(message, str) else "",
    )


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


def prompt_tokens(usage: Usage) -> int:
    """The prompt length of a call: all of its input tokens, cached or not."""
    return (
        usage.input_tokens
        + usage.cache_read_tokens
        + usage.cache_write_5m_tokens
        + usage.cache_write_1h_tokens
    )


def cost_usd(model: str, usage: Usage) -> Decimal:
    """What a call cost, exactly: every kind of token at its own price.

    For a model priced by prompt length, the prices are the ones of this call's own prompt
    length.
    """
    p = price_of(model).rates_for(prompt_tokens(usage))
    return (
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_read_tokens * p.cache_read
        + usage.cache_write_5m_tokens * p.cache_write_5m
        + usage.cache_write_1h_tokens * p.cache_write_1h
    ) / MILLION


def input_token_ceiling(system: str | list, messages: list, tools: list) -> int:
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


def worst_case_usd(
    model: str, input_ceiling: int, max_tokens: int, cache_write: bool = False
) -> Decimal:
    """The most a call can cost: every input token at its dearest rate, the whole output cap.

    Without a cache breakpoint nothing can be billed as a cache write, so input is priced
    at the base rate. With one (``cache_write``), the prefix may be written to the cache,
    which costs more than reading it plainly, so every input token is priced as a
    five-minute cache write. For a model priced by prompt length, the higher prices apply
    as soon as the ceiling is over the threshold: the real prompt may be shorter, but
    nothing shows that before the call.
    """
    p = price_of(model).rates_for(input_ceiling)
    per_input = max(p.input, p.cache_write_5m) if cache_write else p.input
    return (input_ceiling * per_input + max_tokens * p.output) / MILLION


def cached_prefix(system: str) -> list[dict]:
    """The system prompt as one block that ends the cached prefix.

    The API builds the prefix in the order tools, system, messages, and caches everything
    up to and including the block that carries ``cache_control``. So one breakpoint on the
    system prompt covers the tool definitions and the system prompt: what every call of
    every question repeats. The default lifetime, five minutes, is refreshed by each read.
    """
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


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
        self, *, system: str | list, messages: list, tools: list, max_tokens: int
    ) -> Response: ...


class AnthropicLLM:
    """The official SDK, with no automatic retry and an explicit timeout.

    The SDK retries nothing here: a retried request is a second billed request the budget
    did not approve. The one request that is sent again is sent by the loop, after a 429 or
    a 529, which say the request was not served. Any other failed call ends the question,
    booked at its worst case unless the API rejected it.
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

    def complete(
        self, *, system: str | list, messages: list, tools: list, max_tokens: int
    ) -> Response:
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
            kind, detail = _api_error(getattr(exc, "body", None))
            said = f", {kind}" if kind else ""
            said += f": {detail}" if detail else ""
            raise LLMError(
                f"{type(exc).__name__}: HTTP {exc.status_code}{said}",
                status_code=exc.status_code,
                error_type=kind,
                detail=detail,
                retry_after=retry_after_seconds(
                    getattr(getattr(exc, "response", None), "headers", None)
                ),
            ) from None
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

    def complete(
        self, *, system: str | list, messages: list, tools: list, max_tokens: int
    ) -> Response:
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
