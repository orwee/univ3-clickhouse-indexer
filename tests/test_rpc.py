"""The RPC client, driven by a fake session: no network, no real sleeping."""

import logging

import pytest
import requests

from univ3_indexer.rpc import (
    JsonRpcClient,
    RpcError,
    RpcRetriesExhausted,
    alchemy_mainnet_url,
    chunk_ranges,
)

FAKE_KEY = "fake-key-0123456789abcdef"
URL = alchemy_mainnet_url(FAKE_KEY)


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def ok(result):
    return FakeResponse(200, {"jsonrpc": "2.0", "id": 1, "result": result})


class FakeSession:
    """Replays a script of responses (or exceptions) and records every request."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def post(self, url, json, timeout):
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(session, **kwargs):
    fake = FakeTime()
    defaults = dict(session=session, sleep=fake.sleep, clock=fake.clock, rng=lambda: 1.0)
    return JsonRpcClient(URL, **{**defaults, **kwargs}), fake


# --- chunking ------------------------------------------------------------------


def test_chunks_are_inclusive_contiguous_and_cover_the_interval_exactly():
    ranges = list(chunk_ranges(100, 134, 10))
    assert ranges == [(100, 109), (110, 119), (120, 129), (130, 134)]
    covered = [b for lo, hi in ranges for b in range(lo, hi + 1)]
    assert covered == list(range(100, 135))


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (5, 5, [(5, 5)]),
        (0, 9, [(0, 9)]),
        (0, 10, [(0, 9), (10, 10)]),
        (7, 6, []),
    ],
)
def test_chunk_edges(start, end, expected):
    assert list(chunk_ranges(start, end, 10)) == expected


def test_no_chunk_is_ever_wider_than_the_limit():
    assert max(hi - lo + 1 for lo, hi in chunk_ranges(26_000_000, 26_000_987, 10)) == 10


def test_chunk_arguments_are_validated():
    with pytest.raises(ValueError, match="size"):
        list(chunk_ranges(0, 10, 0))
    with pytest.raises(ValueError, match="negative"):
        list(chunk_ranges(-1, 10, 10))


# --- requests --------------------------------------------------------------------


def test_block_number():
    client, _ = make_client(FakeSession(ok("0x18cc942")))
    assert client.block_number() == 26_003_778


def test_finalized_block_number_asks_for_the_tag_and_reads_the_number():
    session = FakeSession(ok({"number": "0x18cc900", "hash": "0x" + "ab" * 32}))
    client, _ = make_client(session)
    assert client.finalized_block_number() == 0x18CC900
    sent = session.requests[0]["json"]
    assert (sent["method"], sent["params"]) == ("eth_getBlockByNumber", ["finalized", False])


@pytest.mark.parametrize("result", [None, {}, {"number": None}, "0x10"])
def test_a_node_without_a_finalized_block_is_an_rpc_error(result):
    client, _ = make_client(FakeSession(ok(result)))
    with pytest.raises(RpcError, match="no block"):
        client.finalized_block_number()


def test_a_node_that_rejects_the_tag_is_an_rpc_error_and_is_not_retried():
    error = {"code": -32602, "message": "invalid block tag"}
    rejected = FakeResponse(200, {"jsonrpc": "2.0", "id": 1, "error": error})
    session = FakeSession(rejected)
    client, _ = make_client(session)
    with pytest.raises(RpcError) as caught:
        client.finalized_block_number()
    assert caught.value.code == -32602 and len(session.requests) == 1


def test_get_logs_sends_every_pool_in_one_call_with_hex_bounds_and_timeouts():
    session = FakeSession(ok([{"logIndex": "0x1"}]))
    client, _ = make_client(session, connect_timeout=3, read_timeout=11)
    logs = client.get_logs(100, 109, ["0xaaa", "0xbbb", "0xccc"], ["0xtopic"])
    assert logs == [{"logIndex": "0x1"}]
    (request,) = session.requests
    assert request["timeout"] == (3, 11)
    assert request["json"]["method"] == "eth_getLogs"
    assert request["json"]["params"] == [
        {
            "fromBlock": "0x64",
            "toBlock": "0x6d",
            "address": ["0xaaa", "0xbbb", "0xccc"],
            "topics": ["0xtopic"],
        }
    ]


def test_get_logs_rejects_an_inverted_range_without_calling():
    session = FakeSession()
    client, _ = make_client(session)
    with pytest.raises(ValueError, match="before"):
        client.get_logs(10, 9, ["0xaaa"], [])
    assert session.requests == []


# --- pacing ----------------------------------------------------------------------


def test_requests_are_spaced_by_the_minimum_interval():
    client, fake = make_client(FakeSession(ok("0x1"), ok("0x2"), ok("0x3")), min_interval=0.25)
    for _ in range(3):
        client.block_number()
    assert fake.sleeps == [0.25, 0.25]


def test_no_pacing_sleep_when_enough_time_already_passed():
    client, fake = make_client(FakeSession(ok("0x1"), ok("0x2")), min_interval=0.25)
    client.block_number()
    fake.now += 5
    client.block_number()
    assert fake.sleeps == []


# --- retries ---------------------------------------------------------------------


def test_429_is_retried_with_exponential_backoff_then_succeeds():
    session = FakeSession(FakeResponse(429, None), FakeResponse(429, None), ok("0x10"))
    client, fake = make_client(session, min_interval=0, backoff_base=0.5)
    assert client.block_number() == 16
    assert fake.sleeps == [0.5, 1.0]
    assert (client.requests_sent, client.retries) == (3, 2)


def test_retry_after_header_wins_over_a_shorter_backoff():
    session = FakeSession(FakeResponse(429, None, {"Retry-After": "7"}), ok("0x10"))
    client, fake = make_client(session, min_interval=0, backoff_base=0.5)
    client.block_number()
    assert fake.sleeps == [7.0]


def test_backoff_is_capped_and_jittered():
    session = FakeSession(*[FakeResponse(503, None)] * 5, ok("0x1"))
    client, fake = make_client(
        session, min_interval=0, backoff_base=1, backoff_cap=4, rng=lambda: 0.0
    )
    client.block_number()
    assert fake.sleeps == [0.5, 1.0, 2.0, 2.0, 2.0]  # rng=0 -> 50% of min(cap, base * 2**n)


def test_rate_limit_reported_inside_a_200_body_is_retried():
    limited = FakeResponse(200, {"jsonrpc": "2.0", "id": 1, "error": {"code": 429, "message": "x"}})
    client, _ = make_client(FakeSession(limited, ok("0x1")), min_interval=0)
    assert client.block_number() == 1


def test_timeouts_and_connection_errors_are_retried():
    session = FakeSession(requests.Timeout("slow"), requests.ConnectionError("reset"), ok("0x1"))
    client, _ = make_client(session, min_interval=0)
    assert client.block_number() == 1


def test_gives_up_after_max_attempts():
    session = FakeSession(*[FakeResponse(429, None)] * 3)
    client, fake = make_client(session, min_interval=0, max_attempts=3)
    with pytest.raises(RpcRetriesExhausted, match="3 attempts"):
        client.block_number()
    assert len(session.requests) == 3
    assert len(fake.sleeps) == 2  # no pointless sleep after the last attempt


def test_oversized_range_error_is_not_retried():
    """What Alchemy's free tier really answers to an 11-block range."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32600, "message": "up to a 10 block range"},
    }
    session = FakeSession(FakeResponse(400, body))
    client, fake = make_client(session, min_interval=0)
    with pytest.raises(RpcError, match="10 block range") as err:
        client.get_logs(1, 11, ["0xaaa"], [])
    assert (err.value.code, err.value.http_status) == (-32600, 400)
    assert len(session.requests) == 1 and fake.sleeps == []


def test_unexpected_response_shape_is_an_error():
    client, _ = make_client(FakeSession(FakeResponse(200, {"jsonrpc": "2.0", "id": 1})))
    with pytest.raises(RpcError, match="unexpected response"):
        client.block_number()


# --- the key never leaks ---------------------------------------------------------


def test_key_is_redacted_from_exhausted_retries_and_from_log_records(caplog):
    leaky = requests.ConnectionError(f"Max retries exceeded with url: /v2/{FAKE_KEY}")
    client, _ = make_client(FakeSession(leaky, leaky), min_interval=0, max_attempts=2)
    with caplog.at_level(logging.WARNING), pytest.raises(RpcRetriesExhausted) as err:
        client.block_number()
    assert FAKE_KEY not in str(err.value)
    assert FAKE_KEY not in caplog.text
    assert "<REDACTED>" in str(err.value)


def test_key_is_redacted_from_rpc_error_messages():
    body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": f"bad url {URL}"}}
    client, _ = make_client(FakeSession(FakeResponse(200, body)))
    with pytest.raises(RpcError) as err:
        client.block_number()
    assert FAKE_KEY not in str(err.value)


def test_repr_does_not_show_the_url():
    client, _ = make_client(FakeSession())
    assert FAKE_KEY not in repr(client) and "alchemy" not in repr(client)


def test_block_hash_asks_for_the_height_in_hex():
    session = FakeSession(ok({"number": "0x10", "hash": "0x" + "cd" * 32}))
    client, _ = make_client(session)
    assert client.block_hash(16) == "0x" + "cd" * 32
    assert session.requests[0]["json"]["params"] == ["0x10", False]
    with pytest.raises(RpcError, match="no block"):
        make_client(FakeSession(ok(None)))[0].block_hash(16)
