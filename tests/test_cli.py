"""The backfill command line, end to end against a fake client. No network."""

import json
import logging

import pytest

from univ3_indexer import abi, cli, landing
from univ3_indexer.rpc import RpcError, RpcRetriesExhausted


def word(value: int) -> str:
    return (value % 2**256).to_bytes(32, "big").hex()


class FakeClient:
    """One swap per block, from the first pool asked for."""

    def __init__(self, tip=2_000_000, fail_at_call=None, failure=None, retries_per_call=0,
                 finalized=None):  # fmt: skip
        self.tip = tip
        # an int: what the node says is finalised. An exception: what asking for it raises.
        self.finalized = tip - 70 if finalized is None else finalized
        self.requests_sent = 0
        self.retries = 0
        self.ranges = []
        self.fail_at_call, self.failure, self.retries_per_call = (
            fail_at_call,
            failure,
            retries_per_call,
        )

    def block_number(self):
        return self.tip

    def finalized_block_number(self):
        if isinstance(self.finalized, Exception):
            raise self.finalized
        return self.finalized

    def get_logs(self, from_block, to_block, addresses, topics):
        self.requests_sent += 1 + self.retries_per_call
        self.retries += self.retries_per_call
        self.ranges.append((from_block, to_block))
        if self.fail_at_call == len(self.ranges):
            raise self.failure
        return [
            {
                "address": addresses[0],
                "topics": [abi.SWAP_TOPIC0, "0x" + "00" * 12 + "11" * 20, "0x" + "00" * 32],
                "data": "0x" + "".join(word(v) for v in (block, -block, 2**96, 1, -5)),
                "blockNumber": hex(block),
                "blockHash": "0x" + word(block),
                "transactionHash": "0x" + word(block),
                "transactionIndex": "0x0",
                "logIndex": "0x0",
                "removed": False,
            }
            for block in range(from_block, to_block + 1)
        ]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIV3_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def run(*args, client=None):
    return cli.main(["--chunks-per-batch", "5", "--log-every", "1", *args], client=client)


def landed_blocks(data):
    return [s.block_number for s in landing.read_landing(data / "landing")]


# --- planning ---------------------------------------------------------------------


def test_window_for_days_ends_at_the_block_it_is_given():
    start, end = cli.plan_window(end=999_930, days=30)
    assert end == 999_930
    assert end - start + 1 == 216_000


def test_the_safe_head_is_the_block_the_node_calls_finalized():
    assert cli.safe_head(FakeClient(tip=1_000_000, finalized=999_921)) == (999_921, "finalized")


@pytest.mark.parametrize("answer", [RpcError("rpc error -32602: unknown block tag", code=-32602),
                                    RpcError("the node returned no block")])  # fmt: skip
def test_a_node_that_does_not_know_the_tag_falls_back_and_says_it_is_not_finalised(answer, caplog):
    with caplog.at_level(logging.WARNING):
        head = cli.safe_head(FakeClient(tip=1_000_000, finalized=answer))
    assert head == (1_000_000 - 64, "tip_minus_confirmations")
    assert "NOT finalised" in caplog.text


def test_a_network_failure_is_not_a_reason_to_fall_back():
    with pytest.raises(RpcRetriesExhausted):
        cli.safe_head(FakeClient(finalized=RpcRetriesExhausted("down")))


def test_a_finalized_block_ahead_of_the_tip_is_refused():
    with pytest.raises(cli.BackfillError, match="finalised but its tip"):
        cli.safe_head(FakeClient(tip=100, finalized=101))


def test_finality_far_behind_the_tip_is_used_and_shouted_about(caplog):
    with caplog.at_level(logging.WARNING):
        assert cli.safe_head(FakeClient(tip=1_000_000, finalized=990_000))[0] == 990_000
    assert "may not be finalising" in caplog.text


def test_an_explicit_end_beyond_the_finalized_block_is_refused(paths):
    client = FakeClient(tip=2_000, finalized=1_930)
    assert run("--from-block", "1000", "--to-block", "1931", client=client) == cli.EXIT_USAGE
    assert not (paths / "plan.json").exists() and client.ranges == []
    assert run("--from-block", "1000", "--to-block", "1930", client=client) == cli.EXIT_OK


def test_dry_run_with_explicit_blocks_touches_neither_network_nor_disk(paths, caplog):
    with caplog.at_level(logging.INFO):
        assert run("--from-block", "1000", "--to-block", "1999", "--dry-run") == cli.EXIT_OK
    assert "1000 blocks" in caplog.text and "100 calls" in caplog.text
    assert not paths.exists()


def test_defaults_live_under_the_data_dir_outside_the_repo(paths):
    run("--from-block", "1000", "--to-block", "1049", client=FakeClient())
    assert sorted(p.name for p in paths.iterdir()) == ["checkpoint.json", "landing", "plan.json"]


def test_paths_inside_the_working_copy_are_refused(paths, caplog):
    inside = cli.config.REPO_ROOT / "data" / "landing"
    code = run("--from-block", "1", "--to-block", "9", "--out", str(inside), client=FakeClient())
    assert code == cli.EXIT_USAGE
    assert "inside the working copy" in caplog.text
    assert not inside.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--from-block", "5"],
        ["--days", "1", "--from-block", "5", "--to-block", "9"],
        ["--rps", "0"],
    ],
)
def test_bad_arguments(paths, args):
    assert run(*args, client=FakeClient()) == cli.EXIT_USAGE


# --- running and resuming -----------------------------------------------------------


def test_full_run_lands_every_block_once(paths):
    client = FakeClient()
    assert run("--from-block", "1000", "--to-block", "1149", client=client) == cli.EXIT_OK
    assert landed_blocks(paths) == list(range(1000, 1150))
    assert max(hi - lo + 1 for lo, hi in client.ranges) == 10
    assert json.loads((paths / "checkpoint.json").read_text())["last_block"] == 1149


def test_days_window_is_fixed_on_the_first_run_and_survives_a_moving_tip(paths):
    failing = FakeClient(tip=2_000_000, fail_at_call=8, failure=RpcRetriesExhausted("down"))
    assert run("--days", "0.02", client=failing) == cli.EXIT_NETWORK
    plan = json.loads((paths / "plan.json").read_text())
    # Until 2026-09-21 the window ended at tip - 64. It now ends at the node's finalized block.
    assert plan["end_block"] == 2_000_000 - 70 and plan["end_chosen_by"] == "finalized"

    later = FakeClient(tip=2_000_500)  # the chain moved on; the plan must not
    assert run("--days", "0.02", client=later) == cli.EXIT_OK
    assert landed_blocks(paths) == list(range(plan["start_block"], plan["end_block"] + 1))
    assert json.loads((paths / "plan.json").read_text()) == plan


def test_network_failure_exits_4_and_resume_completes_without_duplicates(paths):
    failing = FakeClient(fail_at_call=8, failure=RpcRetriesExhausted("gave up"))
    code = run("--from-block", "1000", "--to-block", "1149", client=failing)
    assert code == cli.EXIT_NETWORK
    assert json.loads((paths / "checkpoint.json").read_text())["last_block"] == 1049  # batch 1 only
    assert landed_blocks(paths) == list(range(1000, 1050))

    assert run("--from-block", "1000", "--to-block", "1149", client=FakeClient()) == cli.EXIT_OK
    assert landed_blocks(paths) == list(range(1000, 1150))


def test_permanent_provider_error_exits_3_without_advancing(paths, caplog):
    too_wide = RpcError("eth_getLogs: rpc error -32600: up to a 10 block range", code=-32600)
    client = FakeClient(fail_at_call=1, failure=too_wide)
    assert run("--from-block", "1000", "--to-block", "1149", client=client) == cli.EXIT_PERMANENT
    assert "retrying cannot fix it" in caplog.text and "-32600" in caplog.text
    assert not (paths / "checkpoint.json").exists()
    assert len(client.ranges) == 1


def test_too_many_retries_abort_with_5_to_protect_the_quota(paths, caplog):
    client = FakeClient(retries_per_call=1)  # every call needed a retry: 50%
    code = run(
        "--from-block", "1000", "--to-block", "9999", "--max-retry-ratio", "0.2", client=client
    )
    assert code == cli.EXIT_BUDGET
    assert "protect the quota" in caplog.text
    assert len(client.ranges) == 100  # stopped as soon as 200 requests had been seen
    landing.check_coverage(paths / "landing")  # whatever landed is still consistent


def test_interrupt_exits_130_and_leaves_a_resumable_state(paths):
    client = FakeClient(fail_at_call=8, failure=KeyboardInterrupt())
    assert run("--from-block", "1000", "--to-block", "1149", client=client) == cli.EXIT_INTERRUPTED
    assert run("--from-block", "1000", "--to-block", "1149", client=FakeClient()) == cli.EXIT_OK
    assert landed_blocks(paths) == list(range(1000, 1150))


def test_a_different_window_on_the_same_checkpoint_is_refused(paths, caplog):
    run("--from-block", "1000", "--to-block", "1049", client=FakeClient())
    code = run("--from-block", "500", "--to-block", "1049", client=FakeClient())
    assert code == cli.EXIT_USAGE
    assert "already fixes blocks 1000-1049" in caplog.text


def test_a_changed_pool_set_is_refused(paths, caplog):
    run("--from-block", "1000", "--to-block", "1049", client=FakeClient())
    plan_path = paths / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan["pools"] = plan["pools"][:-1]
    plan_path.write_text(json.dumps(plan))
    assert run("--from-block", "1000", "--to-block", "1049", client=FakeClient()) == cli.EXIT_USAGE
    assert "different set of pools" in caplog.text


# --- progress -----------------------------------------------------------------------


def test_progress_lines_are_plain_and_complete(paths, caplog):
    with caplog.at_level(logging.INFO):
        run("--from-block", "1000", "--to-block", "1149", client=FakeClient())
    progress = [r.getMessage() for r in caplog.records if r.getMessage().startswith("block ")]
    assert len(progress) == 3
    assert "100.0%" in progress[-1]
    for field in ("rows this run", "calls/s", "retries", "blocks/s", "ETA"):
        assert field in progress[0]
    assert "\r" not in caplog.text


def test_progress_after_resume_counts_percent_from_the_whole_plan():
    plan = cli.Plan(1000, 1999, ("0xaa",))
    client = FakeClient()
    client.requests_sent = 25
    ticks = iter([0.0, 5.0])
    progress = cli.Progress(
        plan, already_done=500, client=client, every=1, clock=lambda: next(ticks)
    )
    line = progress.line(1749)
    assert " 75.0%" in line  # 750 of 1000 blocks are done overall
    assert "50 blocks/s" in line  # but only 250 were fetched in these 5 seconds
    assert "ETA 0h00m05s" in line
