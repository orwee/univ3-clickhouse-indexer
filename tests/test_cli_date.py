"""``cli --date``: the first and last block of a UTC day, from a scripted chain. No network."""

import datetime as dt

import pytest

from tests.test_cli import FakeClient, landed_blocks, paths, run  # noqa: F401
from univ3_indexer import cli, landing
from univ3_indexer.rpc import RpcError

DAY = dt.date(2026, 10, 1)
MIDNIGHT = int(dt.datetime(2026, 10, 1, tzinfo=dt.UTC).timestamp())
GENESIS = MIDNIGHT - 5_000 * 12 + 3  # block 0; a block every 12 seconds
# With these numbers 2026-10-01 is blocks 5_000 + 0 .. 5_000 + 7_199: a block lands at 00:00:03
# of the day, and the last one of the day at 23:59:51.
FIRST, LAST = 5_000, 12_199


class Chain(FakeClient):
    """A chain with a block every 12 seconds; timestamps are looked up, as on a node."""

    def __init__(self, tip=20_000, **kwargs):
        super().__init__(tip=tip, **kwargs)
        self.timestamp_calls = 0

    def block_timestamp(self, number):
        self.timestamp_calls += 1
        return GENESIS + 12 * number


def test_the_day_is_the_blocks_with_a_timestamp_inside_it():
    assert cli.day_blocks(Chain(), DAY) == (FIRST, LAST)
    assert GENESIS + 12 * FIRST >= MIDNIGHT > GENESIS + 12 * (FIRST - 1)
    assert GENESIS + 12 * LAST < MIDNIGHT + 86_400 <= GENESIS + 12 * (LAST + 1)


def test_the_search_does_not_walk_the_chain():
    chain = Chain()
    cli.day_blocks(chain, DAY)
    assert chain.timestamp_calls < 60


def test_a_block_exactly_at_midnight_belongs_to_the_new_day(monkeypatch):
    class Aligned(Chain):
        def block_timestamp(self, number):
            return MIDNIGHT + 12 * (number - 5_000)

    assert cli.day_blocks(Aligned(), DAY) == (5_000, 5_000 + 7_199)


def test_a_day_that_is_not_over_is_refused():
    with pytest.raises(cli.BackfillError, match="not over yet"):
        cli.day_blocks(Chain(tip=LAST), DAY)


def test_a_day_before_the_chain_has_blocks_is_refused():
    with pytest.raises(cli.BackfillError, match="no block"):
        cli.day_blocks(Chain(), dt.date(2000, 1, 1))


def test_a_node_without_the_block_is_an_rpc_error_not_a_guess():
    class Empty(Chain):
        def block_timestamp(self, number):
            raise RpcError("eth_getBlockByNumber: the node returned no block")

    with pytest.raises(RpcError):
        cli.day_blocks(Empty(), DAY)


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        (None, (FIRST, LAST)),
        ((0, FIRST - 1), (FIRST, LAST)),
        ((0, FIRST + 99), (FIRST + 100, LAST)),
        ((0, LAST), None),
        ((0, LAST + 500), None),
    ],
)
def test_only_what_the_landing_zone_lacks_is_fetched(coverage, expected):
    assert cli.window_for_day(FIRST, LAST, coverage) == expected


def test_a_day_that_would_leave_a_gap_or_start_before_the_landing_zone_is_refused():
    with pytest.raises(cli.BackfillError, match="gap"):
        cli.window_for_day(FIRST, LAST, (0, FIRST - 2))
    with pytest.raises(cli.BackfillError, match="starts at block"):
        cli.window_for_day(FIRST, LAST, (FIRST + 1, LAST + 10))


def test_date_fetches_that_day_and_keeps_its_plan_and_checkpoint_per_day(paths):  # noqa: F811
    chain = Chain()
    assert run("--date", "2026-10-01", client=chain) == cli.EXIT_OK
    assert landing.check_coverage(paths / "landing") == (FIRST, LAST)
    assert landed_blocks(paths) == list(range(FIRST, LAST + 1))
    day = paths / "days" / "2026-10-01"
    assert sorted(p.name for p in day.iterdir()) == ["checkpoint.json", "plan.json"]


def test_a_second_run_of_the_same_day_fetches_nothing(paths, caplog):  # noqa: F811
    run("--date", "2026-10-01", client=Chain())
    again = Chain()
    assert run("--date", "2026-10-01", client=again) == cli.EXIT_OK
    assert again.ranges == []
    assert "already in the landing zone" in caplog.text


def test_the_next_day_continues_the_same_landing_zone(paths):  # noqa: F811
    run("--date", "2026-10-01", client=Chain(tip=30_000))
    assert run("--date", "2026-10-02", client=Chain(tip=30_000)) == cli.EXIT_OK
    assert landing.check_coverage(paths / "landing") == (FIRST, LAST + 7_200)


def test_a_day_after_a_partly_landed_one_starts_after_what_is_there(paths):  # noqa: F811
    # The landing zone ends in the middle of 2026-10-01, as when the first backfill stopped
    # at the finalized block of that day.
    run("--from-block", str(FIRST - 40), "--to-block", str(FIRST + 99), client=Chain())
    assert run("--date", "2026-10-01", client=Chain()) == cli.EXIT_OK
    assert landing.check_coverage(paths / "landing") == (FIRST - 40, LAST)
    assert landed_blocks(paths) == list(range(FIRST - 40, LAST + 1))


def test_a_run_cut_short_resumes_its_saved_plan(paths):  # noqa: F811
    failing = Chain(fail_at_call=3, failure=RpcError("boom", code=-32600))
    assert run("--date", "2026-10-01", client=failing) == cli.EXIT_PERMANENT
    assert run("--date", "2026-10-01", client=Chain()) == cli.EXIT_OK
    assert landing.check_coverage(paths / "landing") == (FIRST, LAST)


def test_a_day_beyond_the_finalized_block_is_refused_before_anything_is_written(paths):  # noqa: F811
    chain = Chain(tip=20_000, finalized=LAST - 1)
    assert run("--date", "2026-10-01", client=chain) == cli.EXIT_USAGE
    assert chain.ranges == []
    assert not (paths / "days").exists()


def test_date_cannot_be_combined_with_another_window(paths, caplog):  # noqa: F811
    assert run("--date", "2026-10-01", "--days", "1", client=Chain()) == cli.EXIT_USAGE
    assert run("--date", "2026-10-01", "--from-block", "1", client=Chain()) == cli.EXIT_USAGE
    assert "cannot be combined" in caplog.text
