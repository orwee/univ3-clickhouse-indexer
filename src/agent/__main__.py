"""Ask the warehouse one question.

    PYTHONPATH=src uv run --group agent python -m agent "question" \\
        [--config evals/warehouse.yml] [--max-usd 0.25] [--json] [--model ID]

Prints the answer, the SQL used and the cost. Exit code 0 for an answer or a refusal, 1 when
there is no answer, when the question ended in an error (the API, the network or the
budget) or when the answer is not grounded in the last result, 2 when the command could
not run at all.

It connects to ClickHouse as the read-only user, with the credentials of agent-reader.env
and with nothing else. When that user is not available it says so and stops: there is no
other user it falls back to.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

import clickhouse_connect

from agent import budget, loop, tools, warehouse
from agent import llm as llm_module
from univ3_indexer import config

DEFAULT_CONFIG = config.REPO_ROOT / "evals" / "warehouse.yml"
API_KEY_NAME = "ANTHROPIC_API_KEY"  # noqa: S105 - the name of a variable, not a value
SETUP_ERROR = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agent", description=__doc__.split("\n")[0])
    parser.add_argument("question")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="the warehouse file")
    parser.add_argument("--max-usd", default=None, help="dollars for this question")
    parser.add_argument("--json", action="store_true", help="print the whole result as JSON")
    parser.add_argument("--model", default=llm_module.DEFAULT_MODEL, help="a model with a price")
    return parser


def _stop(message: str) -> int:
    print(message, file=sys.stderr)
    return SETUP_ERROR


def _connect_as_reader(database: str):
    """A client for the read-only user. Raises ``ConfigError`` when it is not configured."""
    reader = config.load_agent_reader_config()
    if reader.database != database:
        raise config.ConfigError(
            f"agent-reader.env names the database {reader.database}, the warehouse file "
            f"{database}: they have to be the same"
        )
    return clickhouse_connect.get_client(
        host=reader.host,
        port=reader.port,
        username=reader.user,
        password=reader.password,
        database=database,
    )


def connect_as_reader(database: str):
    """The same connection, for other entry points that must use this user and no other."""
    return _connect_as_reader(database)


def _render(result: loop.Result) -> str:
    lines = []
    answer = result.answer or {}
    if result.status == "answered":
        unit = f" {answer['unit']}" if answer.get("unit") else ""
        lines.append(f"Answer: {answer['value']}{unit}")
    elif result.status == "refused":
        lines.append(f"Refused: {answer['refusal_reason']}")
    elif result.status == "ungrounded":
        lines.append(f"UNGROUNDED, do not trust: {answer.get('value')}")
        lines.append(f"Why: {result.reason}")
    elif result.status == "error":
        lines.append(f"Error, the question was not answered: {result.reason}")
    else:
        lines.append(f"No answer: {result.reason}")
    if answer.get("explanation"):
        lines.append(f"Explanation: {answer['explanation']}")
    lines.append("SQL: " + (result.final_sql or "none ran successfully"))
    tokens = result.usage
    lines.append(
        f"Cost: ${result.usd} ({tokens.input_tokens:,} input and {tokens.output_tokens:,} "
        f"output tokens, {result.iterations} model calls, {result.seconds:.1f} s, "
        f"{result.model})"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, make_llm: Callable | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        house = warehouse.load(args.config)
        max_usd = Decimal(args.max_usd) if args.max_usd is not None else house.max_usd
        llm_module.price_of(args.model)
    except (warehouse.WarehouseError, llm_module.UnknownModel) as problem:
        return _stop(str(problem))
    except InvalidOperation:
        return _stop(f"--max-usd must be a number, got {args.max_usd!r}")

    try:
        client = _connect_as_reader(house.database)
    except config.ConfigError as problem:
        return _stop(
            f"The read-only user is not available: {problem}\n"
            "This command connects as that user only. See docs/AGENT_ACCESS.md."
        )
    except Exception as problem:  # noqa: BLE001 - any connection failure ends here
        code = getattr(problem, "code", None)
        detail = f"ClickHouse error {code}" if code else type(problem).__name__
        return _stop(
            f"Could not connect as the read-only user ({detail}).\n"
            "This command connects as that user only. See docs/AGENT_ACCESS.md."
        )

    try:
        if make_llm is not None:
            model = make_llm(args.model)
        else:
            model = llm_module.AnthropicLLM(config.require_api_key(API_KEY_NAME), args.model)
    except config.ConfigError as problem:
        return _stop(f"No model key: {problem}")
    except ImportError:
        return _stop("The anthropic package is not installed: run with `uv run --group agent`.")

    purse = budget.DollarBudget(max_usd, budget.default_ledger(), scope=f"question:{uuid.uuid4()}")
    result = loop.run(
        args.question,
        model,
        tools.Tools(client, house),
        purse,
        max_iterations=house.max_iterations,
        row_cap=house.row_cap,
    )
    print(json.dumps(result.to_json(), indent=2) if args.json else _render(result))
    return 0 if result.status in ("answered", "refused") else 1


if __name__ == "__main__":
    sys.exit(main())
