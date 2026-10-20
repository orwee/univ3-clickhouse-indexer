"""How well the documentation search finds the section that answers a question.

    PYTHONPATH=src uv run python -m evalkit.retrieval evals/rag_cases.jsonl \\
        [--split dev|test|all] [--max-chars N] [--heading-weight N] [--without-dbt]
    PYTHONPATH=src uv run python -m evalkit.retrieval evals/rag_cases.jsonl --tune

A case is a question, the sections of the documentation that answer it (``relevant``, ids
as ``agent.docs_index`` makes them: ``file#heading``) and the facts an answer must contain.
The labels of the committed file were written by a model, not by a person: its first line
says so, and so does the report.

No model and no network take part. The ranker is the plain BM25 of ``agent.docs_index``.

recall@k
    The share of the cases with at least one relevant section among the first ``k``
    different sections of the ranking. A chunk of a long section counts as its section.
MRR
    The mean over the cases of 1 / (the rank of the first relevant section), 0 when none is
    in the ranking.

``--without-dbt`` leaves the dbt column descriptions out of the index, to compare with the
index as it was before they were added.

``--tune`` tries the settings of the ranker on ``dev`` and on nothing else, and prints them
ordered by MRR. There is no way to ask it for ``test``: that split is read once, at the end,
with the settings ``dev`` chose.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from agent import docs_index
from univ3_indexer import config

KS = (1, 3, 5)
SPLIT_SEED = 20261019
LABEL_NOTE = "labels written by a model, not by a person"
CASE_FIELDS = ("id", "question", "split", "relevant", "key_facts")


class CasesError(ValueError):
    """The file of cases is not what it should be."""


def assign_split(ids: list[str], seed: int = SPLIT_SEED) -> dict[str, str]:
    """``dev`` for a third of the ids (rounded), ``test`` for the rest, drawn with a seed.

    Depends on the set of ids and the seed only, not on the order they are given in.
    """
    ordered = sorted(ids)
    rng = random.Random(seed)  # noqa: S311 - a reproducible draw, not security
    dev = set(rng.sample(ordered, round(len(ordered) / 3)))
    return {case_id: "dev" if case_id in dev else "test" for case_id in ordered}


def load_cases(path: Path) -> list[dict]:
    """The cases of a JSON Lines file. A line with a ``_header`` key is a note, not a case."""
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError:
            raise CasesError(f"{path}:{number}: not JSON") from None
        if "_header" in case:
            continue
        validate(case, f"{path}:{number}")
        cases.append(case)
    if not cases:
        raise CasesError(f"{path}: no cases")
    return cases


def validate(case: dict, where: str = "case") -> None:
    if tuple(case) != CASE_FIELDS:
        raise CasesError(f"{where}: the fields must be {', '.join(CASE_FIELDS)}")
    if case["split"] not in ("dev", "test"):
        raise CasesError(f"{where}: split must be dev or test")
    relevant = case["relevant"]
    if not (isinstance(relevant, list) and relevant and all(isinstance(r, str) for r in relevant)):
        raise CasesError(f"{where}: relevant must be a list of section ids")
    facts = case["key_facts"]
    if not (isinstance(facts, list) and 2 <= len(facts) <= 4):
        raise CasesError(f"{where}: a case has 2 to 4 key facts")
    for fact in facts:
        if set(fact) != {"fact", "any_of"} or not fact["any_of"]:
            raise CasesError(f"{where}: a key fact is a fact and a non-empty any_of")


def ranks(index: docs_index.Index, cases: list[dict]) -> list[int | None]:
    """For each case, the rank (from 1) of its first relevant section, or None."""
    out = []
    for case in cases:
        ranking = index.sections(case["question"], len(index.chunks))
        wanted = set(case["relevant"])
        out.append(next((n for n, s in enumerate(ranking, start=1) if s in wanted), None))
    return out


def metrics(found: list[int | None]) -> dict:
    n = len(found)
    return {
        "cases": n,
        **{f"recall@{k}": sum(1 for r in found if r is not None and r <= k) for k in KS},
        "mrr": sum(1 / r for r in found if r) / n if n else 0.0,
    }


def evaluate(index: docs_index.Index, cases: list[dict]) -> dict:
    return metrics(ranks(index, cases))


def unknown_sections(chunks: list[docs_index.Chunk], cases: list[dict]) -> list[tuple[str, str]]:
    """``(case id, section)`` for every relevant section that no chunk has."""
    known = {chunk.section for chunk in chunks}
    return [(c["id"], s) for c in cases for s in c["relevant"] if s not in known]


def tune(
    root: Path,
    dev_cases: list[dict],
    sizes: tuple[int, ...] = (600, 1000, 1500, 2500, 100000),
    weights: tuple[int, ...] = (1, 2, 3, 5, 8),
) -> list[dict]:
    """Every combination of chunk size and heading weight, scored on the cases given, which
    the caller must have taken from ``dev``. Best first: MRR, then recall@3, then the
    smaller setting."""
    if any(case["split"] != "dev" for case in dev_cases):
        raise CasesError("tuning reads dev only")
    rows = []
    for size in sizes:
        chunks = docs_index.load_chunks(root, size)
        for weight in weights:
            rows.append(
                {
                    "max_chars": size,
                    "heading_weight": weight,
                    **evaluate(docs_index.Index(chunks, weight), dev_cases),
                }
            )
    rows.sort(key=lambda r: (-r["mrr"], -r["recall@3"], r["max_chars"], r["heading_weight"]))
    return rows


def _line(name: str, m: dict) -> str:
    n = m["cases"]
    cells = [f"recall@{k} {m[f'recall@{k}']} of {n} = {m[f'recall@{k}'] / n:.1%}" for k in KS]
    return f"{name}: " + ", ".join(cells) + f", MRR {m['mrr']:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evalkit.retrieval", description="recall@k")
    parser.add_argument("cases", type=Path)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--max-chars", type=int, default=docs_index.DEFAULT_MAX_CHARS)
    parser.add_argument("--heading-weight", type=int, default=docs_index.DEFAULT_HEADING_WEIGHT)
    parser.add_argument("--without-dbt", action="store_true", help="index the documents only")
    parser.add_argument("--tune", action="store_true", help="try the settings on dev")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.cases)
    except (CasesError, OSError) as problem:
        print(str(problem), file=sys.stderr)
        return 2
    root = config.REPO_ROOT
    print(f"NOTE: {LABEL_NOTE}.")
    if args.tune:
        dev = [c for c in cases if c["split"] == "dev"]
        for row in tune(root, dev):
            print(
                f"max_chars {row['max_chars']:>6}  heading_weight {row['heading_weight']}  "
                f"recall@1 {row['recall@1']}  recall@3 {row['recall@3']}  "
                f"recall@5 {row['recall@5']}  MRR {row['mrr']:.3f}  (of {row['cases']})"
            )
        return 0
    chunks = docs_index.load_chunks(root, args.max_chars, dbt=not args.without_dbt)
    missing = unknown_sections(chunks, cases)
    if missing:
        print(f"relevant sections that do not exist: {missing}", file=sys.stderr)
        return 2
    chosen = [c for c in cases if args.split == "all" or c["split"] == args.split]
    index = docs_index.Index(chunks, args.heading_weight)
    print(f"{len(chunks)} chunks, max_chars {args.max_chars}, heading_weight {args.heading_weight}")
    print(_line(args.split, evaluate(index, chosen)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
