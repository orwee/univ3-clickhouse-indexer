"""Run every query in sql/sanity/ and write a Markdown report.

    python -m univ3_indexer.sanity                 # -> reports/sanity.md
    python -m univ3_indexer.sanity --database test_x --out /tmp/sanity.md

Each .sql file starts with a header that says what it asks and what a bad
answer looks like:

    -- title: …
    -- question: …
    -- problem: …
    -- expect: empty | informational

``expect: empty`` means any returned row is a defect: the run exits non-zero.
``informational`` queries never fail the run; they are there to be read.
A query that the server refuses (no permission on a system table, say) is
reported as refused and does not fail the run either.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from univ3_indexer import clickhouse as ch
from univ3_indexer import config

SANITY_DIR = ch.SQL_DIR / "sanity"
DEFAULT_REPORT = config.REPO_ROOT / "reports" / "sanity.md"
MAX_ROWS_SHOWN = 40
_HEADER = re.compile(r"^--\s*(title|question|problem|expect):\s*(.*)$")


@dataclass
class Check:
    path: Path
    title: str
    question: str
    problem: str
    expect: str
    sql: str


@dataclass
class Outcome:
    check: Check
    columns: list[str]
    rows: list[tuple]
    refused: str | None = None

    @property
    def failed(self) -> bool:
        return self.check.expect == "empty" and bool(self.rows)


def parse(path: Path) -> Check:
    fields: dict[str, str] = {}
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("--"):
            break
        match = _HEADER.match(line)
        if match:
            last = match[1]
            fields[last] = match[2].strip()
        elif last:  # continuation line of the previous field
            fields[last] += " " + line.lstrip("-").strip()
    missing = {"title", "question", "problem", "expect"} - set(fields)
    if missing:
        raise ValueError(f"{path.name}: header lacks {sorted(missing)}")
    if fields["expect"] not in ("empty", "informational"):
        raise ValueError(f"{path.name}: expect must be 'empty' or 'informational'")
    sql = ch.strip_sql_comments(path.read_text(encoding="utf-8")).strip().rstrip(";")
    return Check(
        path, fields["title"], fields["question"], fields["problem"], fields["expect"], sql
    )


def checks(directory: Path = SANITY_DIR) -> list[Check]:
    return [parse(path) for path in sorted(directory.glob("*.sql"))]


def run(client, database: str, directory: Path = SANITY_DIR) -> list[Outcome]:
    ch.qualified(database)
    outcomes = []
    for check in checks(directory):
        try:
            result = client.query(check.sql, settings={"database": database})
        except Exception as exc:  # noqa: BLE001 - a refused query is reported, not fatal
            outcomes.append(Outcome(check, [], [], refused=str(exc).split("\n")[0][:300]))
            continue
        outcomes.append(Outcome(check, list(result.column_names), list(result.result_rows)))
    return outcomes


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render(outcomes: list[Outcome], database: str) -> str:
    failed = [o for o in outcomes if o.failed]
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Sanity report",
        "",
        f"Database `{database}`, generated {now} by `make sanity`.",
        "",
        f"**Result: {'FAILED' if failed else 'ok'}**"
        + (f" ({len(failed)} check(s) returned rows that must not exist)" if failed else ""),
        "",
        "| # | Check | Expectation | Rows | Status |",
        "|---|---|---|---|---|",
    ]
    for o in outcomes:
        status = "refused" if o.refused else ("**FAILED**" if o.failed else "ok")
        lines.append(
            f"| {o.check.path.stem[:2]} | {o.check.title} | {o.check.expect} | {len(o.rows)} | {status} |"
        )
    for o in outcomes:
        lines += ["", f"## {o.check.path.stem[:2]}. {o.check.title}", "",
                  f"- **Question:** {o.check.question}", f"- **A problem looks like:** {o.check.problem}",
                  f"- **Source:** `sql/sanity/{o.check.path.name}`", ""]  # fmt: skip
        if o.refused:
            lines.append(f"The server refused this query: `{o.refused}`")
            continue
        if not o.rows:
            lines.append(
                "No rows." + (" That is the expected result." if o.check.expect == "empty" else "")
            )
            continue
        if o.failed:
            lines += [f"**{len(o.rows)} row(s) that must not exist.**", ""]
        lines.append("| " + " | ".join(o.columns) + " |")
        lines.append("|" + "---|" * len(o.columns))
        lines += [
            "| " + " | ".join(_cell(v) for v in row) + " |" for row in o.rows[:MAX_ROWS_SHOWN]
        ]
        if len(o.rows) > MAX_ROWS_SHOWN:
            lines += ["", f"({len(o.rows) - MAX_ROWS_SHOWN} more rows not shown)"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.sanity")
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    database = args.database or config.load_clickhouse_config().database
    outcomes = run(ch.connect(database=database), database)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(outcomes, database), encoding="utf-8")
    failed = [o for o in outcomes if o.failed]
    for o in outcomes:
        state = "REFUSED" if o.refused else ("FAILED" if o.failed else "ok")
        print(f"{o.check.path.name:32} {o.check.expect:14} rows={len(o.rows):<7} {state}")
    print(f"report: {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
