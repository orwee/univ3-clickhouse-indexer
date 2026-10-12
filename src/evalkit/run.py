"""Run the agent on a set of cases and write one results file.

    PYTHONPATH=src uv run --group agent python -m evalkit.run evals/golden.jsonl \\
        --variant baseline [--split dev|test|all] [--ids FILE] [--limit N] [--model ID] \\
        [--repetitions N] [--max-usd 5] [--out FILE] [--config evals/warehouse.yml]
    PYTHONPATH=src uv run --group agent python -m evalkit.run evals/golden.jsonl \\
        --only-errors RESULTS [--max-usd 5] [--out FILE]

What it promises:

- It connects to the database as the read-only user, exactly as ``python -m agent`` does,
  and as nobody else. Without that user it stops.
- ``--variant NAME`` is a file, ``<variants directory>/NAME.yml``, that says what this run
  changes (``evalkit.variants``). A name with no file stops the run.
- One budget for the whole run. Before every question it checks that the question's own
  ceiling still fits. When it does not, the run stops there and every case left is
  recorded as ``not_run``: a partial run is never reported as a whole one.
- The results file is written after every question, and replaced in one step. A job that
  is killed leaves a whole file that says ``unfinished`` and lists the cases it had not
  reached.
- A question is asked once. The loop sends one request again only after a 429 or a 529,
  which were not served; the waits are in the result. A question that still ends because
  of the API, the network or the budget is recorded as an ``error``, apart from the wrong
  answers. ``--only-errors RESULTS`` asks again the cases that ended in error in an earlier
  file and writes the two merged.
- The results file says what was run: the commit, the model, the variant and the SHA-256
  of its files, of the system prompt and of the golden file, the fixture's fingerprint,
  when it started and ended, the budget and what was spent, and for every case and
  repetition the agent's whole result, the first rows of the last result its answer was
  checked against, and its score.
- The full transcripts (every row the model saw) stay out of the repository: they are
  written under the data directory, next to the ledger.

Exit code 0 when the run executed, whatever it scored and even when it stopped on its
budget; 2 when it could not start.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agent import __main__ as agent_cli
from agent import budget, loop, tools, warehouse
from agent import llm as llm_module
from evalkit import fixture, golden, score, variants
from univ3_indexer import config

DEFAULT_CONFIG = config.REPO_ROOT / "evals" / "warehouse.yml"
DEFAULT_VARIANTS = config.REPO_ROOT / "evals" / "variants"
API_KEY_NAME = "ANTHROPIC_API_KEY"  # noqa: S105 - the name of a variable, not a value
FORMAT = 2
SETUP_ERROR = 2
UNFINISHED, COMPLETE = "unfinished", "complete"
NOT_REACHED = "not reached: the run had not got to this question when the file was last written"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.run", description=__doc__.split("\n")[0]
    )
    parser.add_argument("golden", type=Path, help="the file of cases")
    parser.add_argument(
        "--variant", default=None, help="a file of the variants directory, without .yml"
    )
    parser.add_argument("--variants", type=Path, default=DEFAULT_VARIANTS, help="that directory")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--ids", type=Path, default=None, help="a file with one case id per line")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases")
    parser.add_argument("--model", default=None, help="a model with a price; not with a variant's")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-usd", default="5", help="dollars for the whole run")
    parser.add_argument("--out", type=Path, default=None, help="where the results file goes")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="the warehouse file")
    parser.add_argument(
        "--only-errors",
        type=Path,
        default=None,
        metavar="RESULTS",
        help="ask again the cases that ended in error in this earlier file, and merge",
    )
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


def write(path: Path, results: dict) -> None:
    """Replace the results file in one step: a reader finds the old file or the new one,
    never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _key(record: dict) -> tuple[str, int]:
    return record["id"], record["repetition"]


def errors_of(results: dict) -> list[tuple[str, int]]:
    """The (case, repetition) pairs of a results file that ended in an error."""
    return [
        _key(record)
        for record in results["records"]
        if record["status"] == "ran" and (record.get("result") or {}).get("status") == "error"
    ]


def execute(
    plan: list[tuple[dict, int]],
    model,
    client,
    house: warehouse.Warehouse,
    *,
    max_usd: Decimal,
    run_id: str,
    ledger: Path | None,
    transcripts: Path | None,
    descriptions: dict | None = None,
    prompt_addendum: str = "",
    prompt_cache: bool = False,
    after_each: Callable[[list[dict]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict], Decimal]:
    """Ask every (case, repetition) of the plan, in order, until done or until the budget
    stops it.

    Returns the records and what the run spent. The run's budget is asked, before each
    question, whether that question's whole ceiling still fits; the question then runs on
    a budget of its own of exactly that ceiling. ``after_each`` is called with the records
    so far after every question that was asked.
    """
    run_budget = budget.DollarBudget(max_usd)
    records: list[dict] = []
    stopped = ""
    for case, repetition in plan:
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
            tools.Tools(client, house, descriptions),
            budget.DollarBudget(house.max_usd, ledger, scope=scope),
            max_iterations=house.max_iterations,
            row_cap=house.row_cap,
            transcript=transcript,
            prompt_addendum=prompt_addendum,
            sleep=sleep,
            prompt_cache=prompt_cache,
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
        if after_each is not None:
            after_each(records)
    return records, run_budget.spent


def _earlier(path: Path, golden_sha: str, variants_dir: Path, named: str | None) -> dict:
    """An earlier results file, checked: its error cases can be asked again and merged.

    Refused, with the reason, when the merged file would mix two different things: another
    format, another golden file, or a variant whose files changed since.
    """
    try:
        results = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as problem:
        raise ValueError(f"{path}: cannot be read ({type(problem).__name__})") from None
    if not isinstance(results, dict) or results.get("format") != FORMAT:
        raise ValueError(f"{path}: not a results file of format {FORMAT}")
    if named is not None and named != results["variant"]:
        raise ValueError(f"{path} is of variant {results['variant']!r}, not {named!r}")
    if results["golden_sha256"] != golden_sha:
        raise ValueError(
            f"{path} was run on another golden file ({results['golden_sha256'][:12]}...): "
            "rescore it first, or use the file it was run on"
        )
    now = variants.load(results["variant"], variants_dir, config.REPO_ROOT)
    if now.files != results["variant_files"]:
        raise ValueError(f"the files of variant {results['variant']!r} changed since {path}")
    if not errors_of(results):
        raise ValueError(f"{path}: no case ended in error, nothing to run")
    return results


def main(
    argv: list[str] | None = None,
    *,
    make_llm: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = _parser().parse_args(argv)
    try:
        house = warehouse.load(args.config)
        max_usd = Decimal(args.max_usd)
        cases = golden.load(args.golden)
        golden_sha = hashlib.sha256(args.golden.read_bytes()).hexdigest()
        earlier = None
        if args.only_errors is not None:
            if args.ids is not None or args.limit is not None or args.model is not None:
                return _stop("--only-errors takes its cases and its model from the file")
            earlier = _earlier(args.only_errors, golden_sha, args.variants, args.variant)
            name = earlier["variant"]
        elif args.variant is None:
            return _stop("--variant is required: the name of a file in the variants directory")
        else:
            name = args.variant
        variant = variants.load(name, args.variants, config.REPO_ROOT)
        if args.model is not None and variant.model not in (None, args.model):
            return _stop(
                f"the variant {name!r} sets the model {variant.model!r}: --model cannot change it"
            )
        model_id = (
            earlier["model"] if earlier else args.model or variant.model or llm_module.DEFAULT_MODEL
        )
        llm_module.price_of(model_id)
        by_id = {case["id"]: case for case in cases}
        if earlier:
            chosen = [by_id[case_id] for case_id in earlier["cases"]]
            plan = [(by_id[case_id], repetition) for case_id, repetition in errors_of(earlier)]
        else:
            if args.repetitions < 1:
                return _stop("--repetitions must be at least 1")
            chosen = select(cases, args.split, args.ids, args.limit)
            plan = [(case, n) for n in range(1, args.repetitions + 1) for case in chosen]
    except (
        warehouse.WarehouseError,
        llm_module.UnknownModel,
        golden.GoldenError,
        variants.VariantError,
    ) as problem:
        return _stop(str(problem))
    except (ValueError, OSError, KeyError) as problem:
        return _stop(f"{type(problem).__name__}: {problem}")
    except InvalidOperation:
        return _stop(f"--max-usd must be a number, got {args.max_usd!r}")
    if not plan:
        return _stop("no case was selected: nothing to run")
    if variant.max_usd_per_question is not None:
        house = dataclasses.replace(house, max_usd=variant.max_usd_per_question)
    prompt = loop.system_prompt(
        house.max_iterations,
        house.row_cap,
        variant.prompt_addendum,
        descriptions=bool(variant.descriptions),
    )
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if earlier and earlier["system_prompt_sha256"] != prompt_sha:
        return _stop(f"the system prompt changed since {args.only_errors}: not the same run")

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
            model = make_llm(model_id)
        else:
            model = llm_module.AnthropicLLM(config.require_api_key(API_KEY_NAME), model_id)
    except config.ConfigError as problem:
        return _stop(f"No model key: {problem}")
    except ImportError:
        return _stop("The anthropic package is not installed: run with `uv run --group agent`.")

    started = _now()
    run_id = f"{started.replace(':', '').replace('+0000', 'Z')}_{name}_{uuid.uuid4().hex[:6]}"
    directory = config.data_dir() / "evals" / run_id
    out = args.out or directory / "results.json"
    this_run = {"run_id": run_id, "commit": _commit(), "started": started, "ended": None}
    if earlier:
        results = dict(earlier)
        base = list(earlier["records"])
        again = set(errors_of(earlier))
        rerun = {
            **this_run,
            "of_run": earlier["run_id"],
            "asked_again": [],
            "not_asked_again": [],
            "budget_usd": str(max_usd),
            "spent_usd": "0",
        }
        results["reruns"] = [*earlier.get("reruns", []), rerun]
    else:
        rerun, again = None, set()
        base = [
            {"id": case["id"], "repetition": n, "status": "not_run", "why": NOT_REACHED}
            for case, n in plan
        ]
        results = {
            "format": FORMAT,
            "state": UNFINISHED,
            "not_reached": [],
            **this_run,
            "written": started,
            "variant": name,
            "variant_files": variant.files,
            "model": model.model,
            "system_prompt_sha256": prompt_sha,
            "golden_file": args.golden.name,
            "golden_sha256": golden_sha,
            "fixture_fingerprint": fixture.read_fingerprint(),
            "split": args.split,
            "repetitions": args.repetitions,
            "cases_selected": len(chosen),
            "limits": {
                "max_usd_per_question": str(house.max_usd),
                "max_iterations": house.max_iterations,
                "row_cap": house.row_cap,
            },
            "budget_usd": str(max_usd),
            "spent_usd": "0",
        }
    results["cases"] = {case["id"]: case for case in chosen}
    spent_before = Decimal(earlier["spent_usd"]) if earlier else Decimal(0)

    def put(records: list[dict], finished: bool) -> None:
        """The whole file as it stands: what was asked so far over what was there before."""
        new = {_key(record): record for record in records}
        if earlier:  # an error that could not be asked again stays the error it was
            new = {key: record for key, record in new.items() if record["status"] == "ran"}
            for key, record in new.items():
                was = next(r for r in base if _key(r) == key)
                record["asked_again_after"] = was["result"]["reason"]
        merged = [new.get(_key(record), record) for record in base]
        asked = [record for record in new.values() if record["status"] == "ran"]
        spent = sum((Decimal(record["result"]["usd"]) for record in asked), Decimal(0))
        now = _now()
        if rerun is not None:
            rerun["ended"] = now if finished else None
            rerun["spent_usd"] = str(spent)
            rerun["asked_again"] = [{"id": i, "repetition": n} for i, n in new]
            rerun["not_asked_again"] = [
                {"id": i, "repetition": n} for i, n in sorted(again - set(new))
            ]
        else:
            waiting = [_key(record) for record in base if _key(record) not in new]
            results["state"] = COMPLETE if finished else UNFINISHED
            results["ended"] = now if finished else None
            results["not_reached"] = (
                [] if finished else [{"id": i, "repetition": n} for i, n in waiting]
            )
        results["written"] = now
        results["spent_usd"] = str(spent_before + spent)
        results["summary"] = score.summarize(merged, by_id)
        results["records"] = merged
        write(out, results)

    put([], finished=False)
    records, _ = execute(
        plan,
        model,
        client,
        house,
        max_usd=max_usd,
        run_id=run_id,
        ledger=budget.default_ledger(),
        transcripts=directory / "transcripts",
        descriptions=variant.descriptions,
        prompt_addendum=variant.prompt_addendum,
        prompt_cache=variant.prompt_cache,
        after_each=lambda so_far: put(so_far, finished=False),
        sleep=sleep,
    )
    put(records, finished=True)
    summary = results["summary"]
    correct = summary["overall"]["correct"]
    print(
        f"{summary['ran']} of {summary['records']} ran"
        + (f", {summary['not_run']} NOT RUN (partial)" if summary["partial"] else "")
        + (f", {summary['errors']['count']} ended in ERROR" if summary["errors"]["count"] else "")
        + f"; correct {correct['k']} of {correct['n']}; spent ${results['spent_usd']} of ${max_usd}"
    )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
