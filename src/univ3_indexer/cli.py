"""Command line for the backfill.

    python -m univ3_indexer.cli --days 30                  # last 30 days
    python -m univ3_indexer.cli --from-block A --to-block B
    python -m univ3_indexer.cli --days 30 --dry-run        # show the plan, write nothing

Run the same command again to resume: the plan (block range and pools) is saved
next to the checkpoint on the first run and reused afterwards, so ``--days``
does not slide the window forward every time the command is repeated.

Exit codes
    0  finished
    2  bad arguments or configuration
    3  the provider rejected a request permanently (for example -32600: block
       range too wide). Retrying would not help, so nothing was retried.
    4  network trouble outlasted the retries
    5  too many requests needed a retry: aborted to protect the quota
    130 interrupted (Ctrl-C or SIGTERM)

Whatever the exit code, the checkpoint is consistent: it only ever points at
the end of a batch whose file is completely on disk.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from univ3_indexer import config
from univ3_indexer.backfill import (
    CONFIRMATIONS,
    BackfillError,
    Batch,
    FileCheckpointStore,
    run_backfill,
)
from univ3_indexer.landing import JsonlSink
from univ3_indexer.pools import load_pools
from univ3_indexer.rpc import (
    MAX_BLOCK_RANGE,
    JsonRpcClient,
    RpcError,
    RpcRetriesExhausted,
    alchemy_mainnet_url,
)

log = logging.getLogger("univ3_indexer.backfill")

BLOCKS_PER_DAY = 7200  # 12-second slots
EXIT_OK, EXIT_USAGE, EXIT_PERMANENT, EXIT_NETWORK, EXIT_BUDGET, EXIT_INTERRUPTED = (
    0,
    2,
    3,
    4,
    5,
    130,
)


class ErrorBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Plan:
    start_block: int
    end_block: int
    pools: tuple[str, ...]

    @property
    def blocks(self) -> int:
        return self.end_block - self.start_block + 1

    @property
    def calls(self) -> int:
        return -(-self.blocks // MAX_BLOCK_RANGE)


FINALIZED, BEHIND_TIP = "finalized", "tip_minus_confirmations"
MAX_FINALITY_LAG = 1_000  # blocks; normal is 64 to 95. Beyond this something is off: say so.


def safe_head(client, confirmations: int = CONFIRMATIONS) -> tuple[int, str]:
    """(block, how it was chosen): the last block the backfill may read.

    The node's own `finalized` block when it gives one. When the provider REJECTS the request
    (an rpc error or an empty answer: RpcError), fall back to tip - confirmations and say, in
    the log and in plan.json, that the window does NOT end at a finalised block. A network
    failure is not a rejection: RpcRetriesExhausted propagates like any other."""
    tip = client.block_number()
    try:
        finalized = client.finalized_block_number()
    except RpcRetriesExhausted:
        raise
    except RpcError as exc:
        log.warning("the node did not give a finalized block (%s): falling back to tip - %d, "
                    "which is NOT finalised, only deep", exc, confirmations)  # fmt: skip
        return tip - confirmations, BEHIND_TIP
    if finalized > tip:
        raise BackfillError(f"the node says block {finalized} is finalised but its tip is {tip}")
    if tip - finalized > MAX_FINALITY_LAG:
        log.warning(
            "finality is %d blocks behind the tip (normal: 64 to 95): the chain may not be "
            "finalising; the window still ends at the finalised block",
            tip - finalized,
        )
    return finalized, FINALIZED


def plan_window(end: int, days: float) -> tuple[int, int]:
    """(start, end) for the ``days`` days that end at block ``end`` (see safe_head)."""
    return end - round(days * BLOCKS_PER_DAY) + 1, end


def load_or_create_plan(
    path: Path, wanted: Plan | None, pools: tuple[str, ...], *, save: bool, end_chosen_by: str = ""
) -> Plan:
    """The first run fixes the plan; later runs must agree with it."""
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        plan = Plan(saved["start_block"], saved["end_block"], tuple(saved["pools"]))
        if plan.pools != pools:
            raise BackfillError(
                f"{path} was written for a different set of pools than pools.yml has now. "
                "Use another --checkpoint (and --out) for the new pool set."
            )
        return plan
    if wanted is None:
        raise BackfillError("no saved plan: give --days or --from-block/--to-block")
    if save:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "start_block": wanted.start_block,
                    "end_block": wanted.end_block,
                    "pools": list(wanted.pools),
                    # "finalized", "tip_minus_confirmations" or "explicit": read by people
                    "end_chosen_by": end_chosen_by or "explicit",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return wanted


class Progress:
    """Plain log lines every N batches: no progress bar, safe to tail or grep."""

    def __init__(self, plan: Plan, already_done: int, client, every: int, clock=time.monotonic):
        self.plan, self.client, self.every, self.clock = plan, client, max(1, every), clock
        self.started = clock()
        self.done_at_start = already_done
        self.batches = self.rows = 0

    def __call__(self, batch: Batch) -> None:
        self.batches += 1
        self.rows += len(batch.swaps)
        if self.batches % self.every == 0 or batch.to_block >= self.plan.end_block:
            log.info(self.line(batch.to_block))

    def line(self, current_block: int) -> str:
        elapsed = max(self.clock() - self.started, 1e-9)
        done = current_block - self.plan.start_block + 1
        this_run = done - self.done_at_start
        blocks_per_s = this_run / elapsed
        remaining = self.plan.blocks - done
        eta = remaining / blocks_per_s if blocks_per_s > 0 else float("inf")
        return (
            f"block {current_block} | {100 * done / self.plan.blocks:5.1f}% | "
            f"rows this run {self.rows} | {self.client.requests_sent / elapsed:.2f} calls/s "
            f"({self.client.retries} retries) | {blocks_per_s:.0f} blocks/s | ETA {_hms(eta)}"
        )


def _hms(seconds: float) -> str:
    if seconds == float("inf"):
        return "unknown"
    seconds = int(seconds)
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m{seconds % 60:02d}s"


def guarded_get_logs(client, max_retry_ratio: float, min_requests: int = 200):
    """Abort when too large a share of requests needed a retry: something is wrong
    (rate limit set too high, provider incident) and grinding on only burns quota."""

    def get_logs(from_block, to_block, addresses, topics):
        logs = client.get_logs(from_block, to_block, addresses, topics)
        sent, retries = client.requests_sent, client.retries
        if sent >= min_requests and retries / sent > max_retry_ratio:
            raise ErrorBudgetExceeded(
                f"{retries} of {sent} requests needed a retry "
                f"({100 * retries / sent:.0f}% > {100 * max_retry_ratio:.0f}%)"
            )
        return logs

    return get_logs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m univ3_indexer.cli",
        description="Backfill Uniswap v3 Swap logs for the pools in pools.yml.",
    )
    window = parser.add_argument_group("block window (first run only; saved in plan.json)")
    window.add_argument("--days", type=float, help="this many days back from the chain tip")
    window.add_argument("--from-block", type=int)
    window.add_argument("--to-block", type=int)
    parser.add_argument("--sink", choices=["jsonl"], default="jsonl")
    parser.add_argument("--out", type=Path, help="output directory (default: <data dir>/landing)")
    parser.add_argument("--checkpoint", type=Path, help="default: <data dir>/checkpoint.json")
    parser.add_argument("--rps", type=float, default=5.0, help="maximum calls per second")
    parser.add_argument("--chunks-per-batch", type=int, default=100, help="10 blocks per chunk")
    parser.add_argument("--log-every", type=int, default=5, help="progress line every N batches")
    parser.add_argument("--max-retry-ratio", type=float, default=0.2)
    parser.add_argument("--log-file", type=Path, help="also append the log to this file")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return parser


def _setup_logging(log_file: Path | None) -> None:
    """Configure the package logger only: the root logger belongs to the host program."""
    package = logging.getLogger("univ3_indexer")
    for handler in [h for h in package.handlers if getattr(h, "_univ3_cli", False)]:
        package.removeHandler(handler)
        handler.close()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in handlers:
        handler._univ3_cli = True
        handler.setFormatter(formatter)
        package.addHandler(handler)
    package.setLevel(logging.INFO)


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None, *, client=None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.log_file)
    explicit = args.from_block is not None or args.to_block is not None
    if explicit and (args.days is not None or args.from_block is None or args.to_block is None):
        log.error("give either --days, or both --from-block and --to-block")
        return EXIT_USAGE
    if args.rps <= 0 or args.chunks_per_batch < 1:
        log.error("--rps and --chunks-per-batch must be positive")
        return EXIT_USAGE

    try:
        data_dir = config.data_dir()
        out = (args.out or data_dir / "landing").resolve()
        checkpoint_path = (args.checkpoint or data_dir / "checkpoint.json").resolve()
        for path in (out, checkpoint_path):
            if path == config.REPO_ROOT or config.REPO_ROOT in path.parents:
                raise config.ConfigError(f"{path} is inside the working copy: choose another path")
        pools = tuple(sorted(p.key for p in load_pools()))
        plan_path = checkpoint_path.with_name("plan.json")

        if client is None and not (args.dry_run and (explicit or plan_path.exists())):
            key = config.require_api_key("ALCHEMY_API_KEY")
            client = JsonRpcClient(alchemy_mainnet_url(key), min_interval=1 / args.rps)

        wanted, chosen_by = None, ""
        if explicit:
            wanted = Plan(args.from_block, args.to_block, pools)
            if client is not None and not plan_path.exists():
                head, how = safe_head(client)
                if args.to_block > head:
                    raise BackfillError(
                        f"--to-block {args.to_block} is beyond the last safe block {head} ({how}): "
                        "blocks after it can still be reorganised"
                    )
        elif args.days is not None and not plan_path.exists():
            head, chosen_by = safe_head(client)
            log.info("window ends at block %d (%s)", head, chosen_by)
            wanted = Plan(*plan_window(head, args.days), pools)
        plan = load_or_create_plan(
            plan_path, wanted, pools, save=not args.dry_run, end_chosen_by=chosen_by
        )
        if wanted and (wanted.start_block, wanted.end_block) != (plan.start_block, plan.end_block):
            raise BackfillError(
                f"{plan_path} already fixes blocks {plan.start_block}-{plan.end_block}. "
                "Resume with the same command, or use another --checkpoint for a new window."
            )
    except (config.ConfigError, BackfillError, ValueError) as exc:
        log.error("%s", exc)
        return EXIT_USAGE

    checkpoints = FileCheckpointStore(checkpoint_path)
    saved = checkpoints.load()
    done = (saved.last_block - plan.start_block + 1) if saved else 0
    remaining_calls = -(-(plan.blocks - done) // MAX_BLOCK_RANGE)
    log.info(
        "blocks %d-%d (%d blocks, %d pools)",
        plan.start_block,
        plan.end_block,
        plan.blocks,
        len(plan.pools),
    )
    log.info("already done: %d blocks (%.1f%%)", done, 100 * done / plan.blocks)
    log.info(
        "remaining: %d calls, about %s at %.1f calls/s",
        remaining_calls,
        _hms(remaining_calls / args.rps),
        args.rps,
    )
    log.info("sink: %s -> %s", args.sink, out)
    log.info("checkpoint: %s", checkpoint_path)
    if args.dry_run:
        log.info("dry run: nothing fetched, nothing written")
        return EXIT_OK

    signal.signal(signal.SIGTERM, _raise_interrupt)
    progress = Progress(plan, done, client, args.log_every)
    try:
        summary = run_backfill(
            get_logs=guarded_get_logs(client, args.max_retry_ratio),
            sink=JsonlSink(out),
            checkpoints=checkpoints,
            pools=plan.pools,
            start_block=plan.start_block,
            end_block=plan.end_block,
            chunks_per_batch=args.chunks_per_batch,
            on_batch=progress,
        )
    except KeyboardInterrupt:
        log.warning("interrupted. The checkpoint is consistent: run the same command to resume")
        return EXIT_INTERRUPTED
    except ErrorBudgetExceeded as exc:
        log.error("aborting to protect the quota: %s. Lower --rps and resume", exc)
        return EXIT_BUDGET
    except RpcRetriesExhausted as exc:
        log.error("network: %s. The checkpoint is consistent: resume later", exc)
        return EXIT_NETWORK
    except RpcError as exc:
        log.error("the provider rejected the request and retrying cannot fix it: %s", exc)
        return EXIT_PERMANENT
    except BackfillError as exc:
        log.error("%s", exc)
        return EXIT_USAGE
    log.info(
        "finished: %d batches, %d calls, %d rows, through block %s",
        summary.batches,
        summary.chunks,
        summary.logs,
        summary.last_block,
    )
    return EXIT_OK


if __name__ == "__main__":
    os.umask(0o022)
    sys.exit(main())
