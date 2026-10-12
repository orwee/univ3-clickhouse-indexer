"""The README describes only what exists: every link, anchor and diagram node must resolve."""

import json
import re

import pytest
import yaml

from univ3_indexer.config import REPO_ROOT

README = (REPO_ROOT / "README.md").read_text()
VISIBLE = re.sub(r"<!--.*?-->", "", README, flags=re.DOTALL)


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors_of(path) -> set[str]:
    return {slug(m.group(1)) for m in re.finditer(r"^#+ (.+)$", path.read_text(), re.MULTILINE)}


def test_every_relative_link_and_anchor_resolves():
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", VISIBLE):
        if target.startswith(("http://", "https://")):
            continue
        path, _, anchor = target.partition("#")
        file = REPO_ROOT / path
        if not file.exists():
            broken.append(f"{target}: no such file")
        elif anchor and anchor not in anchors_of(file):
            broken.append(f"{target}: no such heading")
    assert not broken, "\n".join(broken)


def test_every_node_of_the_diagram_is_a_real_file():
    diagram = re.search(r"```mermaid\n(.*?)```", README, re.DOTALL).group(1)
    nodes = re.findall(r'\["([^"]+)"\]', diagram)
    assert len(nodes) >= 15
    missing = []
    for node in nodes:
        named = [part for part in node.split("<br/>") if "/" in part or "." in part.split(" ")[0]]
        assert named, f"node without a file: {node}"
        for part in named:
            candidate = part.strip()
            if " " in candidate:  # a caption such as "JSONL files, one per 1,000 blocks"
                continue
            if not (REPO_ROOT / candidate).exists():
                missing.append(candidate)
    assert not missing, f"diagram nodes that are not files: {missing}"


def test_every_make_target_mentioned_exists():
    makefile = (REPO_ROOT / "Makefile").read_text()
    targets = set(re.findall(r"^([a-z][a-z-]*):", makefile, re.MULTILINE))
    mentioned = set(re.findall(r"`make ([a-z][a-z-]*)`", VISIBLE)) | set(
        re.findall(r"^make ([a-z][a-z-]*)$", VISIBLE, re.MULTILINE)
    )
    assert mentioned and mentioned <= targets, mentioned - targets


AUTHORSHIP = (
    "Drafted with AI assistance from the measurements in this repo and checked by an "
    "independent review pass. Design decisions were proposed with AI assistance, tested by "
    "measurement and approved by Roberto."
)
STATES = {"EXPLAINED", "PARTLY EXPLAINED", "UNEXPLAINED"}
FINDINGS = REPO_ROOT / "docs" / "RECONCILIATION_FINDINGS.md"


def section(title: str) -> str:
    return VISIBLE.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0].strip()


def test_the_authorship_note_appears_once_and_in_the_three_agreed_places():
    # It used to sit on every owner-facing section, which read as a disclaimer repeated three
    # times on one page. It now appears exactly once in the README, in "How this was built",
    # and at the top of the two documents that carry conclusions.
    assert README.count(AUTHORSHIP) == 1, "the README states it once"
    assert AUTHORSHIP in section("How this was built")
    assert FINDINGS.read_text().split("\n", 3)[2] == f"> {AUTHORSHIP}"
    decisions = (REPO_ROOT / "DECISIONS.md").read_text()
    assert decisions.count(AUTHORSHIP) == 1 and decisions.split("\n", 3)[2] == f"> {AUTHORSHIP}"


def test_every_finding_has_one_of_the_three_states_and_points_at_evidence():
    text = FINDINGS.read_text()
    findings = re.findall(r"^### (\d+)\. .+ — (.+?)(?: \(.*\))?$", text, re.MULTILINE)
    assert [int(n) for n, _ in findings] == list(range(1, 11))
    assert {state for _, state in findings} <= STATES
    for number, body in re.findall(
        r"^### (\d+)\. .+?$(.*?)(?=^##)", text, re.MULTILINE | re.DOTALL
    ):
        assert re.search(r"\]\((evidence/|\.\./DECISIONS\.md)", body), (
            f"finding {number} cites nothing"
        )
    table = dict(
        re.findall(
            r"^\| \[(\d+)\]\([^)]+\) \|.*\| ([A-Z ]+) \|$",
            section("Reconciliation findings"),
            re.MULTILINE,
        )
    )
    assert table == {n: state for n, state in findings}, "README and the draft disagree on a state"


def test_every_link_of_the_findings_resolves_anchors_included():
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", FINDINGS.read_text()):
        if target.startswith(("http://", "https://")):
            continue
        path, _, anchor = target.partition("#")
        file = (FINDINGS.parent / path).resolve()
        if not file.exists():
            broken.append(f"{target}: no such file")
        elif anchor and anchor not in anchors_of(file):
            broken.append(f"{target}: no such heading")
    assert not broken, "\n".join(broken)


def test_the_limitations_cover_what_was_known_before_the_draft():
    # These were the candidates kept in an HTML comment while the section was pending.
    body = section("Limitations")
    for phrase in ("reorg", "block_hash", "1 USD", "read-only", "one chain", "tx.from"):
        assert phrase in body, phrase
    hidden = " ".join(re.findall(r"<!--(.*?)-->", README, re.DOTALL))
    for phrase in ("reorg", "block_hash", "1 USD", "read-only", "one chain", "tx.from"):
        assert phrase not in hidden, f"{phrase} is hidden in an HTML comment again"


def test_how_it_was_built_does_not_mention_what_was_not_used():
    lowered = VISIBLE.lower()
    assert "kanban" not in lowered and "orca" not in lowered


ALL_DOCS = sorted((REPO_ROOT / "docs").glob("*.md")) + [REPO_ROOT / "DECISIONS.md"]


@pytest.mark.parametrize("doc", ALL_DOCS, ids=lambda p: p.name)
def test_every_relative_link_in_the_docs_resolves_anchors_included(doc):
    broken = []
    text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.DOTALL)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        file = (doc.parent / path).resolve() if path else doc
        if not file.exists():
            broken.append(f"{target}: no such file")
        elif anchor and file.suffix == ".md" and anchor not in anchors_of(file):
            broken.append(f"{target}: no such heading")
    assert not broken, "\n".join(broken)


def test_the_walkthrough_and_the_licence_exist_and_the_readme_points_at_them():
    assert "(docs/WALKTHROUGH.md)" in README and "(LICENSE)" in README
    licence = (REPO_ROOT / "LICENSE").read_text()
    assert licence.startswith("MIT License") and "Roberto Fajardo Duro" in licence


def test_the_readme_figures_are_the_ones_of_the_findings():
    findings = FINDINGS.read_text()
    for figure in ("898,404 swaps", "128 pool-days", "120 compared"):
        assert figure in README and figure in findings, figure


def test_the_drafts_never_say_sandwich_without_the_hedge():
    # Roberto's wording. What the data shows is a pattern; who did it and why is not in a log.
    hedge = "same-block round trips consistent with a sandwich pattern"
    # The README's findings table is one line per finding and no longer uses the word at all;
    # the rule is unchanged where it does appear: never "sandwich" outside the hedged phrase.
    assert hedge in " ".join(FINDINGS.read_text().split()), "the findings describe the pattern"
    for path in (REPO_ROOT / "README.md", FINDINGS):
        text = " ".join(path.read_text().split())
        assert text.lower().count("sandwich") == text.count(hedge), path.name


def test_the_sql_practice_material_is_no_longer_in_the_repo():
    for name in ("docs/SQL_PRACTICE.md", "docs/SQL_PRACTICE_SOLUTIONS.md",
                 "docs/sql_practice_solutions.sql", "scripts/check_sql_practice.py"):  # fmt: skip
        assert not (REPO_ROOT / name).exists(), name
    assert "SQL_PRACTICE" not in README


# --- the agent and its evaluation ------------------------------------------------------------

AGENT_SECTION = "The agent and its evaluation"
RESULTS = REPO_ROOT / "evals" / "results"
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def numbers_in(text: str) -> set[str]:
    """Every figure written in a text, as it is written. Dates, code and link targets are
    not figures: `claude-haiku-5-5` and `2026-10-11_baseline.md` name things."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"\b\d{4}-\d\d-\d\d\b", " ", text)
    return set(NUMBER.findall(text))


def figures_of_the_repository() -> dict[str, str]:
    """Every figure the section may state without a results file, and where it comes from."""
    cases = [
        json.loads(line) for line in (REPO_ROOT / "evals" / "golden.jsonl").read_text().splitlines()
    ]
    count = lambda **want: sum(  # noqa: E731
        1 for case in cases if all(case[k] == v for k, v in want.items())
    )
    limits = yaml.safe_load((REPO_ROOT / "evals" / "warehouse.yml").read_text())["limits"]
    reader = (REPO_ROOT / "clickhouse" / "users.d" / "agent_reader.xml").read_text()
    setting = lambda name: int(re.search(rf"<{name}>(\d+)</{name}>", reader).group(1))  # noqa: E731
    tests = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
    return {
        f"{len(cases)}": "cases in evals/golden.jsonl",
        f"{count(kind='template')}": "template cases",
        f"{count(kind='hand')}": "hand-written cases, and cases with no answer",
        f"{count(split='dev')}": "dev cases",
        f"{count(split='test')}": "test cases",
        f"{limits['max_iterations']}": "model calls per question, evals/warehouse.yml",
        f"{limits['max_usd']}": "dollars per question, evals/warehouse.yml",
        f"{limits['row_cap']}": "rows of a result handed to the model, evals/warehouse.yml",
        f"{setting('max_execution_time')}": "seconds, agent_reader.xml",
        f"{setting('max_result_rows'):,}": "result rows, agent_reader.xml",
        f"{setting('max_memory_usage') // 1_000_000}": "MB of memory, agent_reader.xml",
        re.search(r'"\$reader" != "(\d+)"', tests).group(1): "reader tests, tests.yml",
    }


def test_no_em_dash_anywhere_in_the_readme():
    assert "\u2014" not in README, "an em dash is back in the README"


def test_the_first_paragraph_is_about_data_and_uniswap_comes_after_with_a_glossary():
    paragraphs = [block.strip() for block in VISIBLE.split("\n\n") if block.strip()]
    assert paragraphs[0] == "# univ3-clickhouse-indexer"
    first = " ".join(paragraphs[1].split())
    assert first.startswith("1.24 million financial transactions from a public ledger")
    for said in ("loaded", "verified", "an agent that answers questions", "SQL", "measures"):
        assert said in first, said
    for word in ("Uniswap", "Ethereum", "pool", "swap", "token", "ClickHouse", "dbt"):
        assert word not in first, f"{word} is in the first paragraph"
    assert "Uniswap" in paragraphs[2]
    glossary = VISIBLE.split("## Architecture")[0]
    for word in ("Token", "Pool", "Swap"):
        assert f"- **{word}.** " in glossary, word
    assert glossary.index("Uniswap") < glossary.index("- **Token.**")
    # 1.24 million is the row count of the page, rounded.
    assert "1,240,618 swaps" in VISIBLE and round(1_240_618 / 1e6, 2) == 1.24


def test_the_agent_section_says_what_it_is_what_it_cannot_do_and_what_is_not_done():
    body = section(AGENT_SECTION)
    for part in (
        "**What the agent is.**",
        "**What it cannot do.**",
        "**Which guardrails the database enforces.**",
        "**How the right answers are computed.**",
        "**What is measured.**",
        "**The numbers.**",
        "**Not tied to this domain.**",
        "**What is not done.**",
    ):
        assert part in body, part
    order = [body.index(part) for part in ("**What the agent is.**", "**The numbers.**")]
    assert order == sorted(order)
    not_done = body.split("**What is not done.**")[1]
    for said in (
        "The judge is not calibrated.",
        "There is no regression check on pull requests.",
        "No other model or provider has been compared.",
    ):
        assert said in not_done, said
    other_warehouse = body.split("**Not tied to this domain.**")[1].split("**What is not done")[0]
    for replaced in ("warehouse.yml", "fixture", "templates", "agent_reader.xml", "make golden"):
        assert replaced in other_warehouse, replaced


def test_every_figure_of_the_agent_section_is_in_the_repository_or_in_a_results_report():
    """In the manner of the test that ties the README to the findings: a figure in this
    section is a count of the golden set, a limit read from its file, or a figure of a
    report under evals/results/. Anything else is a number somebody typed."""
    known = figures_of_the_repository()
    reports = sorted(RESULTS.glob("*.md")) if RESULTS.is_dir() else []
    measured = numbers_in(" ".join(path.read_text() for path in reports))
    typed = sorted(
        figure
        for figure in numbers_in(section(AGENT_SECTION))
        if figure not in known and figure not in measured
    )
    assert not typed, f"figures that come from no file: {typed}"
    # Without a results file the section states no measurement at all.
    if not reports:
        assert "%" not in re.sub(r"`[^`]*`", "", section(AGENT_SECTION))
        assert "There are none yet." in section(AGENT_SECTION)


def test_how_it_was_built_says_which_user_what_the_credential_can_do_and_where_the_key_is():
    body = section("How this was built")
    for said in (
        "**Which user.**",
        "**What the credential can do.**",
        "**Where the model key lives.**",
    ):
        assert said in body, said
    assert "gh pr list --state merged" in body
    assert "ran as root" in body and "could merge its own pull request" in body
    assert "could approve its own run" in body and "Not on the server." in body
