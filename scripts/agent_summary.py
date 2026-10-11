"""The job summary of the `agent` workflow: one question, what came back, what it cost.

    python3 scripts/agent_summary.py agent-result.json agent-exit-code.txt agent-stderr.txt
    python3 scripts/agent_summary.py --status agent-result.json

The first form reads the JSON that `python -m agent --json` printed and writes Markdown to
standard output. It always writes something: when the command did not get as far as printing
a result, the summary says so and shows what the command wrote to standard error instead.
The second form prints the status alone, or nothing when there is no result.

Standard library only, so that the runner's own Python runs it without the project.
Everything that came from the model or from the question goes inside <pre>, escaped: it is
text to show, never Markdown to render.
"""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path


def pre(text: object) -> str:
    return f"<pre>{html.escape(str(text))}</pre>"


def read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def load(path: str) -> dict | None:
    """The result, or None when the file is missing, empty or not a JSON object."""
    try:
        result = json.loads(read(path))
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


def render(result: dict | None, exit_code: str, stderr: str, question: str) -> str:
    lines = ["### One question to the agent", "", "**Question**", "", pre(question), ""]
    if result is None:
        lines += [
            f"**No result.** `python -m agent` exited with `{exit_code or 'unknown'}` and "
            "printed no JSON. What it wrote to standard error:",
            "",
            pre(stderr.strip() or "(nothing)"),
        ]
        return "\n".join(lines) + "\n"
    answer = result.get("answer") or {}
    status = str(result.get("status", ""))
    reason = f" ({html.escape(str(result['reason']))})" if result.get("reason") else ""
    lines += [f"**Status: `{html.escape(status)}`**{reason}", ""]
    if status == "refused":
        lines += ["**Refusal**", "", pre(answer.get("refusal_reason", "")), ""]
    elif answer:
        unit = f" {answer['unit']}" if answer.get("unit") else ""
        label = "**Answer**" if status == "answered" else "**Answer, NOT grounded: do not trust**"
        lines += [label, "", pre(f"{answer.get('value')}{unit}"), ""]
    if answer.get("explanation"):
        lines += ["**Explanation**", "", pre(answer["explanation"]), ""]
    lines += ["**SQL**", "", pre(result.get("final_sql") or "none ran successfully"), ""]
    tokens = result.get("tokens") or {}
    written = tokens.get("cache_write_5m_tokens", 0) + tokens.get("cache_write_1h_tokens", 0)
    lines += [
        "| | |",
        "|---|---|",
        f"| Model | `{html.escape(str(result.get('model', '')))}` |",
        f"| Model calls | {result.get('iterations', 0)} |",
        f"| Input tokens | {tokens.get('input_tokens', 0):,} |",
        f"| Output tokens | {tokens.get('output_tokens', 0):,} |",
        f"| Cache read / write tokens | {tokens.get('cache_read_tokens', 0):,} / {written:,} |",
        f"| Cost | ${html.escape(str(result.get('usd', '0')))} |",
        f"| Seconds | {html.escape(str(result.get('seconds', 0)))} |",
        "",
        "The whole result, every tool call included, is the artifact `agent-result`.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--status":
        result = load(argv[1])
        print(result.get("status", "") if result else "")
        return 0
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    result_path, code_path, stderr_path = argv
    question = os.environ.get("QUESTION", "")
    sys.stdout.write(
        render(load(result_path), read(code_path).strip(), read(stderr_path), question)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
