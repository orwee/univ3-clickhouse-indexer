"""Retrieval over the repository's documentation: chunks by heading, and a BM25 ranker.

``README.md``, ``DECISIONS.md`` and ``docs/*.md`` are split at their headings. A chunk is
the text under one heading up to the next one, and its id is ``<file>#<heading>``, the file
relative to the repository root and the heading as written, without the ``#`` marks. A
heading that appears twice in one file gets `` (2)``, `` (3)`` after it. A section longer
than ``max_chars`` is cut at paragraph breaks into pieces; the first keeps the id, the
others add ``~2``, ``~3``. ``section`` of a chunk is its id without that suffix: what a
question is labelled with, and what a ranking is counted in.

The ranker is Okapi BM25 in plain Python: no dependency, no embeddings, no service, no
network. The words of a heading are counted ``heading_weight`` times in the chunk they
head, because a heading names what the section is about.

The column descriptions of dbt are indexed too: every ``schema.yml`` under ``dbt/``, outside
dbt's own output directories, gives one chunk per model and per seed, with its description
and each column with its own. Its id is ``<file>#<name>``, and it is never cut.

Nothing here knows what the documents say.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT_FILES = ("README.md", "DECISIONS.md")
DOCS_DIRECTORY = "docs"
DBT_DIRECTORY = "dbt"
DBT_SCHEMA_FILE = "schema.yml"
# Where dbt writes compiled copies and installed packages: copies, not sources.
DBT_OUTPUT_DIRECTORIES = frozenset({"target", "dbt_packages", "logs"})
# The entries of a schema.yml that describe something with columns, and what each is called.
DBT_RESOURCES = (("models", "model"), ("seeds", "seed"))
# Tuned on the dev split only (docs/EVALS.md, "Retrieval over the documentation").
DEFAULT_MAX_CHARS = 1000
DEFAULT_HEADING_WEIGHT = 8
K1 = 1.5
B = 0.75

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be by do does for from how in is it its of on or so than that the "
    "then there these this to was were what when where which who why with".split()
)


@dataclass(frozen=True)
class Chunk:
    id: str
    section: str  # the id without the piece suffix
    heading: str
    text: str


def tokens(text: str) -> list[str]:
    """Lower-case words and numbers, without the stop words. ``0.05`` is ``0`` and ``05``."""
    return [t for t in _TOKEN.findall(text.casefold()) if t not in STOPWORDS]


def _sections(path: str, text: str) -> list[tuple[str, str, str]]:
    """``(id, heading, body)`` for each heading of one file, code fences respected."""
    found: list[tuple[str, list[str]]] = []
    fenced = False
    current: tuple[str, list[str]] = (path, [])  # text before the first heading
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line)
        if match:
            found.append(current)
            current = (match.group(2), [])
        else:
            current[1].append(line)
    found.append(current)
    seen: Counter[str] = Counter()
    out = []
    for heading, lines in found:
        body = "\n".join(lines).strip()
        if not body and heading == path:
            continue
        seen[heading] += 1
        name = heading if seen[heading] == 1 else f"{heading} ({seen[heading]})"
        out.append((f"{path}#{name}", heading, body))
    return out


def _pieces(body: str, max_chars: int) -> list[str]:
    """The body cut at blank lines into pieces of at most about ``max_chars``."""
    if len(body) <= max_chars:
        return [body]
    pieces, current = [], ""
    for paragraph in re.split(r"\n\s*\n", body):
        if current and len(current) + len(paragraph) + 2 > max_chars:
            pieces.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    return pieces


def chunk_text(path: str, text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    chunks = []
    for section, heading, body in _sections(path, text):
        for n, piece in enumerate(_pieces(body, max_chars), start=1):
            chunks.append(Chunk(section if n == 1 else f"{section}~{n}", section, heading, piece))
    return chunks


def document_files(root: Path) -> list[Path]:
    return [root / name for name in ROOT_FILES] + sorted((root / DOCS_DIRECTORY).glob("*.md"))


def dbt_schema_files(root: Path) -> list[Path]:
    found = (root / DBT_DIRECTORY).rglob(DBT_SCHEMA_FILE)
    return sorted(
        p for p in found if not DBT_OUTPUT_DIRECTORIES & set(p.relative_to(root).parts[1:-1])
    )


def dbt_chunks(path: str, text: str) -> list[Chunk]:
    """One chunk per model and per seed of one ``schema.yml``: its description, then one line
    per column, ``name: description`` or the name alone."""
    loaded = yaml.safe_load(text) or {}
    chunks = []
    for key, kind in DBT_RESOURCES:
        for entry in loaded.get(key) or []:
            name = entry["name"]
            about = " ".join(str(entry.get("description", "")).split())
            lines = [f"dbt {kind} {name}. {about}".rstrip(), "Columns:"]
            for column in entry.get("columns") or []:
                about = " ".join(str(column.get("description", "")).split())
                lines.append(f"- {column['name']}: {about}" if about else f"- {column['name']}")
            section = f"{path}#{name}"
            chunks.append(Chunk(section, section, name, "\n".join(lines)))
    return chunks


def load_chunks(root: Path, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    chunks = []
    for path in document_files(root):
        relative = path.relative_to(root).as_posix()
        chunks.extend(chunk_text(relative, path.read_text(encoding="utf-8"), max_chars))
    for path in dbt_schema_files(root):
        relative = path.relative_to(root).as_posix()
        chunks.extend(dbt_chunks(relative, path.read_text(encoding="utf-8")))
    return chunks


class Index:
    """BM25 over a list of chunks. ``search`` returns ``(score, chunk)``, best first."""

    def __init__(self, chunks: list[Chunk], heading_weight: int = DEFAULT_HEADING_WEIGHT):
        self.chunks = chunks
        self._frequencies: list[Counter[str]] = []
        for chunk in chunks:
            counts = Counter(tokens(chunk.text))
            for word in tokens(chunk.heading):
                counts[word] += heading_weight
            self._frequencies.append(counts)
        self._lengths = [sum(c.values()) for c in self._frequencies]
        self._average = (sum(self._lengths) / len(chunks)) if chunks else 0.0
        containing: Counter[str] = Counter()
        for counts in self._frequencies:
            containing.update(counts.keys())
        n = len(chunks)
        self._idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in containing.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[float, Chunk]]:
        words = [w for w in dict.fromkeys(tokens(query)) if w in self._idf]
        scored = []
        for position, counts in enumerate(self._frequencies):
            score = 0.0
            norm = K1 * (1 - B + B * self._lengths[position] / self._average)
            for word in words:
                tf = counts.get(word, 0)
                if tf:
                    score += self._idf[word] * tf * (K1 + 1) / (tf + norm)
            if score > 0:
                scored.append((score, position))
        scored.sort(key=lambda item: (-item[0], item[1]))  # a tie keeps document order
        return [(score, self.chunks[position]) for score, position in scored[: max(k, 0)]]

    def sections(self, query: str, k: int) -> list[str]:
        """The ids of the first ``k`` different sections for the query, best first."""
        ranked = [chunk.section for _, chunk in self.search(query, len(self.chunks))]
        return list(dict.fromkeys(ranked))[:k]


DEFAULT_K = 5
MAX_K = 8


def search_docs(index: Index, query: object, k: object = DEFAULT_K) -> dict:
    """What the ``search_docs`` tool returns: the best chunks with their ids and their text.

    Never raises: a bad argument comes back as a result with ``ok`` false, as the other tools
    do. ``k`` is clamped to 1 to ``MAX_K``.
    """
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "error": {"kind": "rejected", "message": "query must be text."}}
    count = k if isinstance(k, int) and not isinstance(k, bool) else DEFAULT_K
    found = index.search(query, min(max(count, 1), MAX_K))
    return {
        "ok": True,
        "chunks": [{"id": chunk.id, "text": chunk.text} for _, chunk in found],
    }
