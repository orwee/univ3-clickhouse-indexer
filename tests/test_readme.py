"""The README describes only what exists: every link, anchor and diagram node must resolve."""

import re

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


def test_the_owner_sections_carry_the_pending_text_and_nothing_else():
    for title in ("Reconciliation findings", "Limitations"):
        body = VISIBLE.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0].strip()
        assert body == "PENDING — written by Roberto", title


def test_limitation_candidates_exist_only_inside_an_html_comment():
    comment = re.search(r"<!--(.*?)-->", README, re.DOTALL).group(1)
    for phrase in ("reorg", "block_hash", "1 USD", "read-only", "one chain", "tx.from"):
        assert phrase in comment, phrase
        assert phrase not in VISIBLE.split("## Limitations", 1)[1].split("\n## ", 1)[0]


def test_how_it_was_built_does_not_mention_what_was_not_used():
    lowered = VISIBLE.lower()
    assert "kanban" not in lowered and "orca" not in lowered
