"""The README describes only what exists: every link, anchor and diagram node must resolve."""

import re

import pytest

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


DRAFT = "**DRAFT — to be reviewed and rewritten by Roberto**"
STATES = {"EXPLAINED", "PARTLY EXPLAINED", "UNEXPLAINED"}
FINDINGS = REPO_ROOT / "docs" / "RECONCILIATION_FINDINGS.md"


def section(title: str) -> str:
    return VISIBLE.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0].strip()


def test_the_owner_sections_are_marked_as_drafts_until_roberto_rewrites_them():
    # Until 2026-09-20 these two sections held only "PENDING — written by Roberto". Roberto
    # asked for a draft in their place; what must not happen is a draft that does not say so.
    for title in ("Reconciliation findings", "Limitations"):
        assert section(title).startswith(DRAFT), title
    assert FINDINGS.read_text().split("\n", 3)[2] == DRAFT


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
    assert "<!--" not in README, "no hidden candidates left behind"


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
    for path in (REPO_ROOT / "README.md", FINDINGS):
        text = " ".join(path.read_text().split())
        assert hedge in text, path.name
        assert text.lower().count("sandwich") == text.count(hedge), path.name


def test_the_sql_practice_material_is_no_longer_in_the_repo():
    for name in ("docs/SQL_PRACTICE.md", "docs/SQL_PRACTICE_SOLUTIONS.md",
                 "docs/sql_practice_solutions.sql", "scripts/check_sql_practice.py"):  # fmt: skip
        assert not (REPO_ROOT / name).exists(), name
    assert "SQL_PRACTICE" not in README
