"""Ask the agent the questions of the documentation suite, and judge what it cites.

    PYTHONPATH=src uv run --group agent python -m evalkit.rag_run evals/rag_cases.jsonl \\
        --variant docs [--split dev|test|all] [--limit N] [--max-usd 1] [--out results.json] \\
        [--report report.md]

The agent is the one of ``evalkit.run`` with one more tool, ``search_docs``, which a variant
turns on with ``docs_tool: true``. This command asks each case once, then scores:

correct
    Every key fact of the case is in the answer. A key fact is a statement and a list of
    lower-case strings, ``any_of``; it is present when one of them occurs in the value and
    the explanation of the answer, after lower-casing, dropping backticks and asterisks and
    removing the commas inside numbers. A plain substring test: it cannot tell a fact that
    is stated from one that is denied. A refusal, no answer and an error are not correct
    (an error is left out of the figure and counted apart).
grounded
    The judge (``evals/judge_rubric_docs.md``) says every key statement of the answer is
    supported by a chunk the answer cites. The judge is shown the text of the cited chunks
    the agent was given and nothing else. An answer whose citations are not all ids that
    ``search_docs`` returned in that question is not grounded, and is not sent to the judge.
    The judge's labels have not been calibrated against a person.

What the agent searched is reported too: whether a section that answers the question was
among the chunks it was given, and whether it cited one. These come from the labels of the
case, which a model wrote.

The budget is one number. The agent may spend ``AGENT_SHARE`` of it, the rest is the
judge's; both check a call's worst case before sending it, and a case that does not fit is
recorded as not run or not judged. The results file is written after every question and
replaced in one step.

Exit code 0 when the run executed, whatever it scored; 2 when it could not start.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agent import __main__ as agent_cli
from agent import budget, docs_index, loop, tools, warehouse
from agent import llm as llm_module
from evalkit import judge, retrieval, run, score, variants
from univ3_indexer import config

DEFAULT_RUBRIC = config.REPO_ROOT / "evals" / "judge_rubric_docs.md"
AGENT_SHARE = Decimal("0.4")  # of --max-usd; the judge gets the rest
FORMAT = 1
NOT_JUDGED_NO_CITATION = "not sent to the judge: a citation is not a chunk search_docs returned"


class RagError(ValueError):
    """The run cannot start: the variant has no docs tool, or the cases are not usable."""


def normalise(text: str) -> str:
    """Lower-case, no backticks or asterisks, single spaces, no commas inside numbers."""
    text = re.sub(r"[`*]", "", text.casefold())
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return " ".join(text.split())


def answer_text(answer: dict | None) -> str:
    answer = answer or {}
    parts = (answer.get("value"), answer.get("explanation"))
    return " ".join(p for p in parts if isinstance(p, str))


def facts_present(case: dict, answer: dict | None) -> list[bool]:
    text = normalise(answer_text(answer))
    return [any(normalise(term) in text for term in fact["any_of"]) for fact in case["key_facts"]]


def section_of(chunk_id: str) -> str:
    return chunk_id.split("~", 1)[0]


def score_record(case: dict, result: dict) -> dict:
    """The deterministic part of the score of one question."""
    answer = result.get("answer")
    has_text = result["status"] in ("answered", "ungrounded") and bool(
        answer and answer.get("type") == loop.TEXT_ANSWER
    )
    present = facts_present(case, answer) if has_text else [False] * len(case["key_facts"])
    wanted = set(case["relevant"])
    given = [d["id"] for d in result.get("documents", [])]
    cited = [c for c in (answer or {}).get("citations") or [] if isinstance(c, str)]
    return {
        "has_text": has_text,
        "facts_present": present,
        "correct": has_text and all(present),
        "retrieved_relevant": any(section_of(i) in wanted for i in given),
        "cited_relevant": has_text and any(section_of(i) in wanted for i in cited),
        "citations_valid": result["status"] == "answered",
    }


def judge_item(case: dict, record: dict) -> judge.Item | None:
    """What the judge is shown for one answered question, or None when it is not judged."""
    result = record["result"]
    if not record["score"]["has_text"] or result["status"] != "answered":
        return None
    by_id = {d["id"]: d["text"] for d in result.get("documents", [])}
    cited = list(dict.fromkeys(result["answer"]["citations"]))
    blocks = [f'<chunk id="{i}">\n{by_id[i]}\n</chunk>' for i in cited]
    text = "\n".join(
        [
            "<question>",
            case["question"],
            "</question>",
            "",
            "<cited_chunks>",
            *blocks,
            "</cited_chunks>",
            "",
            "<answer>",
            result["answer"]["value"].strip(),
            "</answer>",
        ]
    )
    return judge.Item(
        key=f"{case['id']}#{record['repetition']}",
        question=case["question"],
        sql="",
        result={},
        explanation=result["answer"]["value"],
        text=text,
    )


def summarize(records: list[dict], verdicts: list[dict]) -> dict:
    ran = [r for r in records if r["status"] == "ran"]
    errors = [r for r in ran if r["result"]["status"] == "error"]
    asked = [r for r in ran if r["result"]["status"] != "error"]
    by_status: dict[str, int] = {}
    for record in asked:
        status = record["result"]["status"]
        by_status[status] = by_status.get(status, 0) + 1
    texts = [r for r in asked if r["score"]["has_text"]]
    verdict = {v["key"]: v for v in verdicts}
    grounded = sum(
        1
        for r in texts
        if verdict.get(f"{r['id']}#{r['repetition']}", {}).get("verdict") == "faithful"
    )
    unjudged = sum(
        1
        for r in texts
        if verdict.get(f"{r['id']}#{r['repetition']}", {}).get("status") not in ("judged",)
    )
    fact_total = sum(len(r["score"]["facts_present"]) for r in asked)
    fact_found = sum(sum(r["score"]["facts_present"]) for r in asked)
    usd = sum((Decimal(r["result"]["usd"]) for r in ran), Decimal(0))
    judged_usd = sum((Decimal(v.get("usd", "0")) for v in verdicts), Decimal(0))
    return {
        "records": len(records),
        "ran": len(ran),
        "not_run": len(records) - len(ran),
        "errors": len(errors),
        "asked": len(asked),
        "by_status": by_status,
        "correct": score.proportion(sum(r["score"]["correct"] for r in asked), len(asked)),
        "key_facts": {"found": fact_found, "of": fact_total},
        "grounded": score.proportion(grounded, len(texts)),
        "answers_with_text": len(texts),
        "not_judged_or_no_verdict": unjudged,
        "retrieved_relevant": score.proportion(
            sum(r["score"]["retrieved_relevant"] for r in asked), len(asked)
        ),
        "cited_relevant": score.proportion(
            sum(r["score"]["cited_relevant"] for r in asked), len(asked)
        ),
        "agent_usd": str(usd),
        "judge_usd": str(judged_usd),
    }


def _p(p: dict) -> str:
    if not p["n"]:
        return "none asked"
    return f"{p['k']} of {p['n']} = {p['value']:.1%} [{p['low']:.1%}, {p['high']:.1%}]"


def render(results: dict) -> str:
    s = results["summary"]
    lines = [
        f"# Documentation suite: {results['variant']}, split {results['split']}",
        "",
        f"**One run, not a measurement of the agent.** Run `{results['run_id']}`, "
        f"commit `{results['commit']}`, model `{results['model']}`, "
        f"judge `{results['judge_model']}`. "
        f"The labels of the cases were written by a model, not by a person, and the judge has "
        f"not been calibrated against a person.",
        "",
    ]
    if results["state"] != run.COMPLETE or s["not_run"] or s["errors"]:
        lines += [
            f"**Not a whole run:** state {results['state']}, {s['not_run']} not run, "
            f"{s['errors']} ended in an error (left out of every figure).",
            "",
        ]
    lines += [
        "| Figure | Value |",
        "|---|---|",
        f"| Questions asked | {s['asked']} (of {s['records']} selected) |",
        f"| Correct (every key fact present) | {_p(s['correct'])} |",
        f"| Key facts present | {s['key_facts']['found']} of {s['key_facts']['of']} |",
        f"| Grounded (judge: every key statement supported by a cited chunk) | "
        f"{_p(s['grounded'])}, over answers in words |",
        f"| A section that answers was among the chunks the agent was given | "
        f"{_p(s['retrieved_relevant'])} |",
        f"| A section that answers was cited | {_p(s['cited_relevant'])} |",
        f"| How the questions ended | {json.dumps(s['by_status'], sort_keys=True)} |",
        f"| Spent, agent | {s['agent_usd']} USD |",
        f"| Spent, judge | {s['judge_usd']} USD |",
        "",
    ]
    return "\n".join(lines)


def execute(
    cases: list[dict],
    model,
    client,
    house: warehouse.Warehouse,
    docs: dict[str, docs_index.Index],
    *,
    max_usd: Decimal,
    run_id: str,
    ledger: Path | None,
    prompt_addendum: str,
    transcripts: Path | None = None,
    after_each: Callable[[list[dict]], None] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> list[dict]:
    """Ask every case once, in order, until done or until the agent's budget stops it."""
    kwargs = {} if sleep is None else {"sleep": sleep}
    run_budget = budget.DollarBudget(max_usd)
    records: list[dict] = []
    stopped = ""
    for case in cases:
        record = {"id": case["id"], "repetition": 1}
        if not stopped:
            try:
                run_budget.check(house.max_usd)
            except budget.BudgetExceeded as refusal:
                stopped = f"the agent's budget: {refusal}"
        if stopped:
            records.append({**record, "status": "not_run", "why": stopped})
            continue
        scope = f"rag:{run_id}:{case['id']}"
        transcript: list = []
        result = loop.run(
            case["question"],
            model,
            tools.Tools(client, house, None),
            budget.DollarBudget(house.max_usd, ledger, scope=scope),
            max_iterations=house.max_iterations,
            row_cap=house.row_cap,
            transcript=transcript,
            prompt_addendum=prompt_addendum,
            docs=docs,
            **kwargs,
        ).to_json()
        run_budget.record(Decimal(result["usd"]), scope)
        if transcripts is not None:
            transcripts.mkdir(parents=True, exist_ok=True)
            (transcripts / f"{case['id']}_1.json").write_text(
                json.dumps({"id": case["id"], "repetition": 1, "turns": transcript}) + "\n",
                encoding="utf-8",
            )
        records.append(
            {**record, "status": "ran", "result": result, "score": score_record(case, result)}
        )
        if after_each is not None:
            after_each(records)
    return records


def judge_records(
    cases: dict[str, dict],
    records: list[dict],
    judge_llm,
    rubric: str,
    *,
    max_usd: Decimal,
    ledger: Path | None,
    scope: str,
    sleep: Callable[[float], None] | None = None,
) -> list[dict]:
    """A verdict for every answer in words. Those with an invalid citation get none from the
    model and are recorded as ``not_judged`` with the reason."""
    items, verdicts = [], []
    for record in records:
        if record["status"] != "ran" or not record["score"]["has_text"]:
            continue
        key = f"{record['id']}#{record['repetition']}"
        item = judge_item(cases[record["id"]], record)
        if item is None:
            verdicts.append(
                {
                    "key": key,
                    "status": "not_judged",
                    "verdict": None,
                    "reason": NOT_JUDGED_NO_CITATION,
                }
            )
        else:
            items.append(item)
    kwargs = {} if sleep is None else {"sleep": sleep}
    judged, _ = judge.judge_all(
        items, judge_llm, rubric, max_usd=max_usd, ledger=ledger, scope=scope, **kwargs
    )
    return [*verdicts, *judged]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.rag_run", description=__doc__.split("\n")[0]
    )
    parser.add_argument("cases", type=Path, help="the file of cases")
    parser.add_argument("--variant", default="docs")
    parser.add_argument("--variants", type=Path, default=run.DEFAULT_VARIANTS)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases")
    parser.add_argument("--model", default=None, help="a model with a price")
    parser.add_argument("--judge-model", default=judge.DEFAULT_MODEL)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    parser.add_argument("--max-usd", default="1", help="dollars for the agent and the judge")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=run.DEFAULT_CONFIG)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    make_llm: Callable | None = None,
    make_client: Callable | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        house = warehouse.load(args.config)
        max_usd = Decimal(args.max_usd)
        if not max_usd.is_finite() or max_usd <= 0:
            return run._stop("--max-usd must be a positive number")
        cases = retrieval.load_cases(args.cases)
        variant = variants.load(args.variant, args.variants, config.REPO_ROOT)
        if not variant.docs_tool:
            raise RagError(f"the variant {args.variant!r} does not set docs_tool: nothing to test")
        model_id = args.model or variant.model or llm_module.DEFAULT_MODEL
        if args.model is not None and variant.model not in (None, args.model):
            raise RagError(
                f"the variant sets the model {variant.model!r}: --model cannot change it"
            )
        llm_module.price_of(model_id)
        llm_module.price_of(args.judge_model)
        llm_module.check_served_by(model_id, variant.provider)
        rubric = args.rubric.read_text(encoding="utf-8")
        chosen = [c for c in cases if args.split == "all" or c["split"] == args.split]
        if args.limit is not None:
            chosen = chosen[: max(args.limit, 0)]
        chunks = [
            chunk
            for source in docs_index.SOURCES
            for chunk in docs_index.load_chunks(config.REPO_ROOT, source=source)
        ]
        missing = retrieval.unknown_sections(chunks, chosen)
        if missing:
            raise RagError(f"relevant sections that do not exist: {missing}")
    except (
        retrieval.CasesError,
        RagError,
        warehouse.WarehouseError,
        llm_module.UnknownModel,
        variants.VariantError,
    ) as problem:
        return run._stop(str(problem))
    except InvalidOperation:
        return run._stop(f"--max-usd must be a number, got {args.max_usd!r}")
    except (ValueError, OSError, KeyError) as problem:
        return run._stop(f"{type(problem).__name__}: {problem}")
    if not chosen:
        return run._stop("no case was selected: nothing to run")
    if variant.max_usd_per_question is not None:
        house = dataclasses.replace(house, max_usd=variant.max_usd_per_question)
    try:
        client = (make_client or agent_cli.connect_as_reader)(house.database)
    except config.ConfigError as problem:
        return run._stop(f"The read-only user is not available: {problem}")
    except Exception as problem:  # noqa: BLE001 - any connection failure ends here
        code = getattr(problem, "code", None)
        detail = f"ClickHouse error {code}" if code else type(problem).__name__
        return run._stop(f"Could not connect as the read-only user ({detail}).")
    try:
        if make_llm is not None:
            model, judge_llm = make_llm(model_id), make_llm(args.judge_model)
        else:
            provider = llm_module.provider_of(variant.provider)
            model = llm_module.AnthropicLLM(
                config.require_api_key(provider.key_name), model_id, provider=provider.name
            )
            judge_llm = llm_module.AnthropicLLM(
                config.require_api_key(judge.API_KEY_NAME), args.judge_model
            )
    except config.ConfigError as problem:
        return run._stop(f"No model key: {problem}")
    except ImportError:
        return run._stop("The anthropic package is not installed: run with `uv run --group agent`.")

    started = run._now()
    run_id = f"{started.replace(':', '').replace('+0000', 'Z')}_rag_{uuid.uuid4().hex[:6]}"
    directory = config.data_dir() / "evals" / run_id
    out = args.out or directory / "results.json"
    docs = docs_index.load_library(config.REPO_ROOT)
    prompt = loop.system_prompt(house.max_iterations, house.row_cap, variant.prompt_addendum)
    results = {
        "format": FORMAT,
        "suite": "docs",
        "state": run.UNFINISHED,
        "run_id": run_id,
        "commit": run._commit(),
        "started": started,
        "ended": None,
        "variant": args.variant,
        "variant_files": variant.files,
        "model": model.model,
        "judge_model": judge_llm.model,
        "system_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "rubric_file": args.rubric.name,
        "rubric_sha256": hashlib.sha256(rubric.encode("utf-8")).hexdigest(),
        "cases_file": args.cases.name,
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "label_note": retrieval.LABEL_NOTE,
        "index": {
            "chunks": len(chunks),
            "max_chars": docs_index.DEFAULT_MAX_CHARS,
            "heading_weight": docs_index.DEFAULT_HEADING_WEIGHT,
        },
        "split": args.split,
        "budget_usd": str(max_usd),
        "agent_budget_usd": str(max_usd * AGENT_SHARE),
        "judge_budget_usd": str(max_usd - max_usd * AGENT_SHARE),
        "cases": {c["id"]: c for c in chosen},
    }

    def put(records: list[dict], verdicts: list[dict], finished: bool) -> None:
        results["state"] = run.COMPLETE if finished else run.UNFINISHED
        results["ended"] = run._now() if finished else None
        results["summary"] = summarize(records, verdicts)
        results["spent_usd"] = str(
            Decimal(results["summary"]["agent_usd"]) + Decimal(results["summary"]["judge_usd"])
        )
        results["records"] = records
        results["verdicts"] = verdicts
        run.write(out, results)

    put([], [], False)
    records = execute(
        chosen,
        model,
        client,
        house,
        docs,
        max_usd=max_usd * AGENT_SHARE,
        run_id=run_id,
        ledger=budget.default_ledger(),
        prompt_addendum=variant.prompt_addendum,
        transcripts=directory / "transcripts",
        after_each=lambda so_far: put(so_far, [], False),
        sleep=sleep,
    )
    put(records, [], False)
    verdicts = judge_records(
        {c["id"]: c for c in chosen},
        records,
        judge_llm,
        rubric,
        max_usd=max_usd - max_usd * AGENT_SHARE,
        ledger=budget.default_ledger(),
        scope=f"rag-judge:{run_id}",
        sleep=sleep,
    )
    put(records, verdicts, True)
    report = render(results)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    s = results["summary"]
    print(
        f"{s['asked']} asked of {s['records']}; correct {s['correct']['k']} of "
        f"{s['correct']['n']}; grounded {s['grounded']['k']} of {s['grounded']['n']}; "
        f"spent ${results['spent_usd']} of ${max_usd}"
    )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
