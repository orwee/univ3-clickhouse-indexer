"""Run the agent on a set of cases and write one results file.

    PYTHONPATH=src uv run --group agent python -m evalkit.run evals/golden.jsonl \\
        --variant baseline [--split dev|test|all] [--ids FILE] [--limit N] [--model ID] \\
        [--repetitions N] [--max-usd 5] [--out FILE] [--config evals/warehouse.yml]

What it promises:

- It connects to the database as the read-only user, exactly as ``python -m agent`` does,
  and as nobody else. Without that user it stops.
- One budget for the whole run. Before every question it checks that the question's own
  ceiling still fits. When it does not, the run stops there and every case left is
  recorded as ``not_run``: a partial run is never reported as a whole one.
- Nothing is retried. A question that ends in a model error is recorded as it ended.
- The results file says what was run: the commit, the model, the variant, the SHA-256 of
  the system prompt and of the golden file, the fixture's fingerprint, when it started and
  ended, the budget and what was spent, and for every case and repetition the agent's whole
  result and its score.
- The full transcripts (every row the model saw) stay out of the repository: they are
  written under the data directory, next to the ledger.

Exit code 0 when the run executed, whatever it scored and even when it stopped on its
budget; 2 when it could not start.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agent import __main__ as agent_cli
from agent import budget, loop, tools, warehouse
from agent import llm as llm_module
from evalkit import fixture, golden, score
from univ3_indexer import config

DEFAULT_CONFIG = config.REPO_ROOT / "evals" / "warehouse.yml"
API_KEY_NAME = "ANTHROPIC_API_KEY"  # noqa: S105 - the name of a variable, not a value
FORMAT = 1
VARIANT = re.compile(r"[A-Za-z0-9._-]+")  # it becomes part of file names
SETUP_ERROR = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.run", description=__doc__.split("\n")[0]
    )
    parser.add_argument("golden", type=Path, help="the file of cases")
    parser.add_argument("--variant", required=True, help="a name for this run; goes into the file")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--ids", type=Path, default=None, help="a file with one case id per line")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases")
    parser.add_argument("--model", default=llm_module.DEFAULT_MODEL)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-usd", default="5", help="dollars for the whole run")
    parser.add_argument("--out", type=Path, default=None, help="where the results file goes")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="the warehouse file")
    return parser


def _stop(message: str) -> int:
    print(message, file=sys.stderr)
    return SETUP_ERROR


def _commit() -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=config.REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def select(cases: list[dict], split: str, ids: Path | None, limit: int | None) -> list[dict]:
    """The cases of a run, in the order of the file: by split, then by id, then the first N."""
    chosen = [case for case in cases if split == "all" or case["split"] == split]
    if ids is not None:
        wanted = [line.strip() for line in ids.read_text(encoding="utf-8").splitlines()]
        wanted = [line for line in wanted if line and not line.startswith("#")]
        known = {case["id"] for case in cases}
        unknown = [case_id for case_id in wanted if case_id not in known]
        if unknown:
            raise ValueError(f"not in the golden file: {', '.join(unknown)}")
        chosen = [case for case in chosen if case["id"] in set(wanted)]
    return chosen if limit is None else chosen[: max(limit, 0)]


def execute(
    cases: list[dict],
    model,
    client,
    house: warehouse.Warehouse,
    *,
    repetitions: int,
    max_usd: Decimal,
    run_id: str,
    ledger: Path | None,
    transcripts: Path | None,
) -> tuple[list[dict], Decimal]:
    """Ask every case, repetition by repetition, until done or until the budget stops it.

    Returns the records and what the run spent. The run's budget is asked, before each
    question, whether that question's whole ceiling still fits; the question then runs on
    a budget of its own of exactly that ceiling.
    """
    run_budget = budget.DollarBudget(max_usd)
    records: list[dict] = []
    stopped = ""
    for repetition in range(1, repetitions + 1):
        for case in cases:
            record = {"id": case["id"], "repetition": repetition}
            if not stopped:
                try:
                    run_budget.check(house.max_usd)
                except budget.BudgetExceeded as refusal:
                    stopped = f"the run's budget: {refusal}"
            if stopped:
                records.append({**record, "status": "not_run", "why": stopped})
                continue
            scope = f"eval:{run_id}:{case['id']}:{repetition}"
            transcript: list = []
            result = loop.run(
                case["question"],
                model,
                tools.Tools(client, house),
                budget.DollarBudget(house.max_usd, ledger, scope=scope),
                max_iterations=house.max_iterations,
                row_cap=house.row_cap,
                transcript=transcript,
            ).to_json()
            run_budget.record(Decimal(result["usd"]), scope)
            if transcripts is not None:
                transcripts.mkdir(parents=True, exist_ok=True)
                name = f"{case['id']}_{repetition}.json"
                (transcripts / name).write_text(
                    json.dumps({"id": case["id"], "repetition": repetition, "turns": transcript})
                    + "\n",
                    encoding="utf-8",
                )
            records.append(
                {
                    **record,
                    "status": "ran",
                    "result": result,
                    "score": score.score_case(case, result),
                }
            )
    return records, run_budget.spent


def main(argv: list[str] | None = None, *, make_llm: Callable | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        house = warehouse.load(args.config)
        max_usd = Decimal(args.max_usd)
        llm_module.price_of(args.model)
        cases = golden.load(args.golden)
        chosen = select(cases, args.split, args.ids, args.limit)
    except (warehouse.WarehouseError, llm_module.UnknownModel, golden.GoldenError) as problem:
        return _stop(str(problem))
    except (ValueError, OSError) as problem:
        return _stop(f"{type(problem).__name__}: {problem}")
    except InvalidOperation:
        return _stop(f"--max-usd must be a number, got {args.max_usd!r}")
    if not VARIANT.fullmatch(args.variant):
        return _stop("--variant is letters, digits, dot, dash and underscore: it names files")
    if not chosen:
        return _stop("no case was selected: nothing to run")
    if args.repetitions < 1:
        return _stop("--repetitions must be at least 1")

    try:
        client = agent_cli.connect_as_reader(house.database)
    except config.ConfigError as problem:
        return _stop(
            f"The read-only user is not available: {problem}\n"
            "An evaluation connects as that user only. See docs/AGENT_ACCESS.md."
        )
    except Exception as problem:  # noqa: BLE001 - any connection failure ends here
        code = getattr(problem, "code", None)
        detail = f"ClickHouse error {code}" if code else type(problem).__name__
        return _stop(f"Could not connect as the read-only user ({detail}).")

    try:
        if make_llm is not None:
            model = make_llm(args.model)
        else:
            model = llm_module.AnthropicLLM(config.require_api_key(API_KEY_NAME), args.model)
    except config.ConfigError as problem:
        return _stop(f"No model key: {problem}")
    except ImportError:
        return _stop("The anthropic package is not installed: run with `uv run --group agent`.")

    started = _now()
    run_id = (
        f"{started.replace(':', '').replace('+0000', 'Z')}_{args.variant}_{uuid.uuid4().hex[:6]}"
    )
    directory = config.data_dir() / "evals" / run_id
    prompt = loop.system_prompt(house.max_iterations, house.row_cap)
    records, spent = execute(
        chosen,
        model,
        client,
        house,
        repetitions=args.repetitions,
        max_usd=max_usd,
        run_id=run_id,
        ledger=budget.default_ledger(),
        transcripts=directory / "transcripts",
    )
    by_id = {case["id"]: case for case in cases}
    results = {
        "format": FORMAT,
        "run_id": run_id,
        "variant": args.variant,
        "model": model.model,
        "commit": _commit(),
        "system_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "golden_file": args.golden.name,
        "golden_sha256": hashlib.sha256(args.golden.read_bytes()).hexdigest(),
        "fixture_fingerprint": fixture.read_fingerprint(),
        "started": started,
        "ended": _now(),
        "split": args.split,
        "repetitions": args.repetitions,
        "cases_selected": len(chosen),
        "limits": {
            "max_usd_per_question": str(house.max_usd),
            "max_iterations": house.max_iterations,
            "row_cap": house.row_cap,
        },
        "budget_usd": str(max_usd),
        "spent_usd": str(spent),
        "summary": score.summarize(records, by_id),
        "cases": {case["id"]: case for case in chosen},
        "records": records,
    }
    out = args.out or directory / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = results["summary"]
    correct = summary["overall"]["correct"]
    print(
        f"{summary['ran']} of {summary['records']} ran"
        + (f", {summary['not_run']} NOT RUN (partial)" if summary["partial"] else "")
        + f"; correct {correct['k']} of {correct['n']}; spent ${spent} of ${max_usd}"
    )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
