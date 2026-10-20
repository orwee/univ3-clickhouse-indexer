"""Retrieval over the documentation: the chunks, the ranker, the metrics and the cases.

No model, no network, no server. The metrics are checked against values worked out by hand
on a corpus of three small documents; the committed cases are checked for shape and for
pointing at sections that exist. Only ``dev`` is ever scored here: ``test`` is read once, by
the command, at the end (docs/EVALS.md).
"""

import json
import math

import pytest

from agent import docs_index
from evalkit import retrieval
from univ3_indexer import config

ROOT = config.REPO_ROOT
CASES = ROOT / "evals" / "rag_cases.jsonl"
# What the dev split scored when the settings were chosen (docs/EVALS.md). A floor, so that
# a change to the ranker or to the documents that breaks retrieval is noticed.
DEV_RECALL_AT_5_FLOOR = 13
DEV_MRR_FLOOR = 0.75

TEXT = """Intro line.

# Alpha
alpha beta gamma

## Beta
```
# not a heading
```
beta beta delta

# Alpha

second alpha, about epsilon
"""


def test_chunks_are_cut_at_headings_with_file_and_heading_in_the_id():
    chunks = docs_index.chunk_text("x.md", TEXT)
    assert [c.id for c in chunks] == [
        "x.md#x.md",
        "x.md#Alpha",
        "x.md#Beta",
        "x.md#Alpha (2)",
    ]
    assert chunks[0].text == "Intro line."
    assert "# not a heading" in chunks[2].text  # a fence is not a heading
    assert chunks[1].text == "alpha beta gamma"


def test_a_long_section_is_cut_at_paragraphs_and_the_pieces_share_a_section():
    body = "\n\n".join(f"paragraph {n} " + "word " * 20 for n in range(10))
    chunks = docs_index.chunk_text("x.md", f"# Long\n{body}", max_chars=300)
    assert len(chunks) > 1
    assert chunks[0].id == "x.md#Long"
    assert [c.id for c in chunks[1:3]] == ["x.md#Long~2", "x.md#Long~3"]
    assert {c.section for c in chunks} == {"x.md#Long"}
    assert "\n\n".join(c.text for c in chunks) == body.strip()


def test_the_files_are_readme_decisions_and_every_markdown_file_of_docs():
    names = {p.relative_to(ROOT).as_posix() for p in docs_index.document_files(ROOT)}
    assert {"README.md", "DECISIONS.md", "docs/EVALS.md", "docs/AGENT.md"} <= names
    assert all(n.count("/") == 0 or n.startswith("docs/") and n.count("/") == 1 for n in names)
    assert len(names) == 2 + len(list((ROOT / "docs").glob("*.md")))


def test_bm25_ranks_by_hand_computed_scores():
    chunks = [
        docs_index.Chunk("a#A", "a#A", "A", "cat cat dog"),
        docs_index.Chunk("a#B", "a#B", "B", "dog bird"),
        docs_index.Chunk("a#C", "a#C", "C", "fish"),
    ]
    index = docs_index.Index(chunks, heading_weight=0)
    # "cat": df 1 of 3, so idf = ln(1 + (3 - 1 + .5) / (1 + .5)).
    # A has 3 words and the average is (3 + 2 + 1) / 3 = 2.
    idf = math.log(1 + 2.5 / 1.5)
    norm = 1.5 * (1 - 0.75 + 0.75 * 3 / 2)
    expected = idf * 2 * 2.5 / (2 + norm)
    found = index.search("the cat", k=5)  # "the" is a stop word
    assert [c.id for _, c in found] == ["a#A"]
    assert found[0][0] == pytest.approx(expected)
    assert [c.id for _, c in index.search("dog", k=5)] == ["a#B", "a#A"]  # shorter text first
    assert index.search("nothing here", k=5) == []
    assert index.search("dog", k=0) == []


def test_the_words_of_a_heading_count_heading_weight_times():
    chunks = [
        docs_index.Chunk("a#X", "a#X", "zebra", "plain words"),
        docs_index.Chunk("a#Y", "a#Y", "other", "zebra"),
    ]
    heavy = docs_index.Index(chunks, heading_weight=5).search("zebra", 2)
    assert [c.id for _, c in heavy] == ["a#X", "a#Y"]
    light = docs_index.Index(chunks, heading_weight=0).search("zebra", 2)
    assert [c.id for _, c in light] == ["a#Y"]


def test_a_ranking_in_sections_lists_each_section_once_in_order():
    chunks = [
        docs_index.Chunk("a#S", "a#S", "S", "term"),
        docs_index.Chunk("a#S~2", "a#S", "S", "term term"),
        docs_index.Chunk("a#T", "a#T", "T", "term"),
    ]
    assert docs_index.Index(chunks, 0).sections("term", 5) == ["a#S", "a#T"]


def test_metrics_by_hand():
    found = [1, 3, None, 5, 2, 7]
    m = retrieval.metrics(found)
    assert m["cases"] == 6
    assert (m["recall@1"], m["recall@3"], m["recall@5"]) == (1, 3, 4)
    assert m["mrr"] == pytest.approx((1 + 1 / 3 + 0 + 1 / 5 + 1 / 2 + 1 / 7) / 6)
    assert retrieval.metrics([])["mrr"] == 0.0


def test_ranks_use_any_relevant_section_of_a_case():
    chunks = [
        docs_index.Chunk("a#P", "a#P", "P", "apple"),
        docs_index.Chunk("a#Q", "a#Q", "Q", "banana apple"),
    ]
    index = docs_index.Index(chunks, 0)
    cases = [{"question": "apple", "relevant": ["a#Q", "a#Z"]}]
    assert retrieval.ranks(index, cases) == [2]


def test_the_split_is_a_third_to_dev_and_the_same_for_the_same_ids_in_any_order():
    ids = [f"c{n}" for n in range(30)]
    split = retrieval.assign_split(ids)
    assert sum(v == "dev" for v in split.values()) == 10
    assert retrieval.assign_split(list(reversed(ids))) == split
    assert retrieval.assign_split(ids, seed=1) != split


# --- the committed cases ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def cases():
    return retrieval.load_cases(CASES)


def test_the_header_says_a_model_wrote_the_labels():
    header = json.loads(CASES.read_text(encoding="utf-8").splitlines()[0])
    assert "WERE WRITTEN BY A MODEL, NOT BY A PERSON" in header["_header"]


def test_there_are_about_forty_cases_with_unique_ids_and_two_to_four_facts(cases):
    ids = [c["id"] for c in cases]
    assert 36 <= len(ids) <= 48 and len(set(ids)) == len(ids)
    assert all(2 <= len(c["key_facts"]) <= 4 for c in cases)
    assert all(c["question"].endswith("?") for c in cases)


def test_the_split_is_the_one_the_seed_draws(cases):
    assert {c["id"]: c["split"] for c in cases} == retrieval.assign_split([c["id"] for c in cases])
    assert 0.25 < sum(c["split"] == "dev" for c in cases) / len(cases) < 0.4


def test_every_relevant_section_exists_and_every_key_fact_term_is_lowercase(cases):
    chunks = docs_index.load_chunks(ROOT)
    assert retrieval.unknown_sections(chunks, cases) == []
    for case in cases:
        for fact in case["key_facts"]:
            assert all(t == t.lower() for t in fact["any_of"]), case["id"]


def test_every_key_fact_of_a_case_can_be_found_in_its_relevant_sections(cases):
    """A label that its own sections cannot support is a wrong label."""
    chunks = docs_index.load_chunks(ROOT, 10**6)
    text = {}
    for chunk in chunks:
        text.setdefault(chunk.section, []).append(chunk.text)
    for case in cases:
        source = " ".join(" ".join(text[s]) for s in case["relevant"]).lower()
        for fact in case["key_facts"]:
            assert any(t in source for t in fact["any_of"]), (case["id"], fact["fact"])


def test_the_dev_split_scores_at_least_what_it_scored_when_the_settings_were_chosen(cases):
    dev = [c for c in cases if c["split"] == "dev"]
    m = retrieval.evaluate(docs_index.Index(docs_index.load_chunks(ROOT)), dev)
    assert m["recall@5"] >= DEV_RECALL_AT_5_FLOOR and m["mrr"] >= DEV_MRR_FLOOR


def test_tuning_refuses_anything_but_dev(cases):
    with pytest.raises(retrieval.CasesError, match="dev only"):
        retrieval.tune(ROOT, [c for c in cases if c["split"] == "test"][:1])


def test_a_case_with_the_wrong_shape_is_refused(cases):
    bad = dict(cases[0], key_facts=cases[0]["key_facts"][:1])
    with pytest.raises(retrieval.CasesError, match="2 to 4"):
        retrieval.validate(bad)
