"""A small JSON-RPC client over ``requests``: two methods, and full control of
the three places a backfill goes wrong (range size, rate, retries).

* ``chunk_ranges`` cuts a block interval into inclusive ranges of at most N
  blocks. Measured on 2026-09-18: the Alchemy free tier accepts 10 blocks and
  answers HTTP 400 / code -32600 to 11.
* One ``eth_getLogs`` call carries ALL pool addresses: the cost is per call,
  not per address.
* Pacing: a minimum interval between requests, so the steady state never
  trips the rate limit in the first place.
* Retries with exponential backoff and jitter on HTTP 429, 5xx, timeouts and
  connection errors. ``Retry-After`` is honoured when present. Everything else
  (a -32600 for an oversized range, a malformed request) fails immediately:
  retrying a request that is wrong only burns quota.

The endpoint URL contains the API key. It never appears in an exception, a log
record or a ``repr``: every message goes through ``_redact``.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

ALCHEMY_MAINNET = "https://eth-mainnet.g.alchemy.com/v2/"
MAX_BLOCK_RANGE = 10  # inclusive; see the measurement in docs/MEASUREMENTS.md

_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_RETRYABLE_RPC_CODES = {429, -32005}  # rate limited (Alchemy / EIP-1474 "limit exceeded")


class RpcError(RuntimeError):
    """The node answered with an error that retrying will not fix."""

    def __init__(self, message: str, *, code: int | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class RpcRetriesExhausted(RpcError):
    """Gave up after the configured number of attempts."""


@dataclass(frozen=True)
class _Outcome:
    done: bool = False
    result: object = None
    problem: str = ""
    retry_after: float | None = None


def alchemy_mainnet_url(api_key: str) -> str:
    return ALCHEMY_MAINNET + api_key


def chunk_ranges(start: int, end: int, size: int = MAX_BLOCK_RANGE) -> Iterator[tuple[int, int]]:
    """Inclusive (from, to) ranges covering [start, end] exactly once, in order."""
    if size < 1:
        raise ValueError("size must be at least 1")
    if start < 0:
        raise ValueError("start must not be negative")
    while start <= end:
        stop = min(start + size - 1, end)
        yield start, stop
        start = stop + 1


class JsonRpcClient:
    def __init__(
        self,
        url: str,
        *,
        secrets: Sequence[str] = (),
        session: requests.Session | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        min_interval: float = 0.2,
        max_attempts: int = 6,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
    ):
        self._url = url
        last_segment = url.rstrip("/").rsplit("/", 1)[-1]
        implied = (last_segment,) if len(last_segment) >= 16 and "." not in last_segment else ()
        self._secrets = tuple(s for s in (*secrets, *implied) if s)
        self._session = session or requests.Session()
        self._timeout = (connect_timeout, read_timeout)
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._last_request_at: float | None = None
        self._next_id = 0
        self.requests_sent = 0
        self.retries = 0

    def __repr__(self) -> str:
        return f"JsonRpcClient(url=<redacted>, requests_sent={self.requests_sent})"

    # -- public API -----------------------------------------------------------

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def get_logs(
        self, from_block: int, to_block: int, addresses: Sequence[str], topics: Sequence[str]
    ) -> list[dict]:
        """Raw logs for an inclusive block range, all addresses in a single call."""
        if to_block < from_block:
            raise ValueError("to_block is before from_block")
        params = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "address": list(addresses),
            "topics": list(topics),
        }
        result = self.call("eth_getLogs", [params])
        if not isinstance(result, list):
            raise RpcError("eth_getLogs did not return a list")
        return result

    def call(self, method: str, params: list):
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        problem = "no attempt made"
        for attempt in range(1, self._max_attempts + 1):
            self._pace()
            retry_after: float | None = None
            try:
                self.requests_sent += 1
                response = self._session.post(self._url, json=payload, timeout=self._timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                problem = self._redact(f"{type(exc).__name__}: {exc}")
            else:
                outcome = self._interpret(method, response)
                if outcome.done:
                    return outcome.result
                problem, retry_after = outcome.problem, outcome.retry_after
            if attempt < self._max_attempts:
                delay = self._backoff(attempt, retry_after)
                self.retries += 1
                log.warning(
                    "%s attempt %d/%d failed (%s); retrying in %.1fs",
                    method,
                    attempt,
                    self._max_attempts,
                    problem,
                    delay,
                )
                self._sleep(delay)
        raise RpcRetriesExhausted(
            f"{method}: gave up after {self._max_attempts} attempts: {problem}"
        )

    # -- internals ------------------------------------------------------------

    def _interpret(self, method: str, response) -> _Outcome:
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("code") if isinstance(error, dict) else None

        if status in _RETRYABLE_HTTP or code in _RETRYABLE_RPC_CODES:
            return _Outcome(
                problem=f"HTTP {status}" + (f", rpc code {code}" if code is not None else ""),
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )
        if error is not None:
            message = error.get("message") if isinstance(error, dict) else error
            raise RpcError(
                self._redact(f"{method}: rpc error {code}: {message}"),
                code=code,
                http_status=status,
            )
        if status != 200 or not isinstance(body, dict) or "result" not in body:
            raise RpcError(f"{method}: unexpected response, HTTP {status}", http_status=status)
        return _Outcome(done=True, result=body["result"])

    def _pace(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request_at = now

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        exponential = min(self._backoff_cap, self._backoff_base * 2 ** (attempt - 1))
        delay = exponential * (0.5 + self._rng() / 2)  # jitter in [50%, 100%]
        if retry_after is not None:
            delay = max(delay, min(retry_after, self._backoff_cap))
        return delay

    def _redact(self, text: str) -> str:
        text = text.replace(self._url, "<REDACTED_URL>")
        for secret in self._secrets:
            text = text.replace(secret, "<REDACTED>")
        return text


def _parse_retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None  # the HTTP-date form is not worth parsing here
