"""The dbt column descriptions in the documentation index, and the cases that need them.

No model, no network, no server. The second set of cases, ``evals/rag_cases_dbt.jsonl``,
lives in a file of its own so that the split of ``evals/rag_cases.jsonl``, which is drawn
from its set of ids, does not move.
"""

import json

import pytest

from agent import docs_index
from evalkit import retrieval
from univ3_indexer import config

ROOT = config.REPO_ROOT
CASES = ROOT / "evals" / "rag_cases_dbt.jsonl"

SCHEMA = """version: 2
seeds:
  - name: things
    description: >
      Folded
      text.
    columns:
      - name: a
        description: What a is.
      - name: b
models:
  - name: first
    description: One.
    columns:
      - name: c
        description: What c is.
  - name: second
"""


def test_one_chunk_per_model_and_per_seed_with_its_columns():
    chunks = docs_index.dbt_chunks("dbt/x/schema.yml", SCHEMA)
    assert [c.id for c in chunks] == [
        "dbt/x/schema.yml#first",
        "dbt/x/schema.yml#second",
        "dbt/x/schema.yml#things",
    ]
    assert all(c.section == c.id for c in chunks)
    first, second, things = chunks
    assert first.heading == "first"
    assert first.text == "dbt model first. One.\nColumns:\n- c: What c is."
    assert second.text == "dbt model second.\nColumns:"
    assert things.text == "dbt seed things. Folded text.\nColumns:\n- a: What a is.\n- b"


def test_the_schema_files_are_the_sources_and_not_dbts_compiled_copies(tmp_path):
    for place in ("models/a", "models/b/c", "target/compiled/models/a", "dbt_packages/p"):
        (tmp_path / "dbt" / place).mkdir(parents=True)
        (tmp_path / "dbt" / place / "schema.yml").write_text("version: 2\n")
    found = [p.relative_to(tmp_path).as_posix() for p in docs_index.dbt_schema_files(tmp_path)]
    assert found == ["dbt/models/a/schema.yml", "dbt/models/b/c/schema.yml"]


def test_the_dbt_source_holds_every_model_and_seed_of_the_dbt_project():
    ids = {c.id for c in docs_index.load_chunks(ROOT, source="dbt")}
    assert ids == {
        "dbt/models/marts/schema.yml#dim_pools",
        "dbt/models/marts/schema.yml#fct_pool_daily",
        "dbt/models/marts/schema.yml#fct_pool_daily_round_trips",
        "dbt/models/marts/schema.yml#fct_pool_daily_smart_money",
        "dbt/models/marts/schema.yml#fct_round_trip_legs",
        "dbt/models/staging/schema.yml#pools",
        "dbt/models/staging/schema.yml#stg_swaps",
    }


@pytest.fixture(scope="module")
def cases():
    return retrieval.load_cases(CASES)


def test_the_header_says_a_model_wrote_the_labels():
    header = json.loads(CASES.read_text(encoding="utf-8").splitlines()[0])
    assert "THE LABELS WERE WRITTEN BY A MODEL, NOT BY A PERSON" in header["_header"]


def test_the_cases_are_answered_only_by_dbt_chunks_that_exist(cases):
    chunks = docs_index.load_chunks(ROOT, source="dbt")
    assert retrieval.unknown_sections(chunks, cases) == []
    assert all(s.startswith("dbt/") for c in cases for s in c["relevant"])
    assert {c["id"] for c in cases} >= {"dbt-fee-500"}
    ids = [c["id"] for c in cases]
    assert len(set(ids)) == len(ids) and not set(ids) & {
        c["id"] for c in retrieval.load_cases(ROOT / "evals" / "rag_cases.jsonl")
    }


def test_the_split_is_the_one_the_seed_draws(cases):
    assert {c["id"]: c["split"] for c in cases} == retrieval.assign_split([c["id"] for c in cases])


def test_every_key_fact_can_be_found_in_the_relevant_chunks(cases):
    text = {c.section: c.text.lower() for c in docs_index.load_chunks(ROOT, source="dbt")}
    for case in cases:
        source = " ".join(text[s] for s in case["relevant"])
        for fact in case["key_facts"]:
            assert all(t == t.lower() for t in fact["any_of"]), case["id"]
            assert any(t in source for t in fact["any_of"]), (case["id"], fact["fact"])


def test_the_default_index_is_the_documents_and_the_dbt_chunks_are_a_source_of_their_own():
    """The dbt chunks used to share the documents' index and pushed six of the 44 old cases
    down; in an index of their own they change nothing in the documents' ranking."""
    docs = docs_index.load_chunks(ROOT)
    assert docs == docs_index.load_chunks(ROOT, source="docs")
    assert not any(c.id.startswith("dbt/") for c in docs)
    assert all(c.id.startswith("dbt/") for c in docs_index.load_chunks(ROOT, source="dbt"))
    library = docs_index.load_library(ROOT)
    assert set(library) == set(docs_index.SOURCES) == {"docs", "dbt"}
    assert [c.id for c in library["docs"].chunks] == [c.id for c in docs]
    old = retrieval.load_cases(ROOT / "evals" / "rag_cases.jsonl")
    assert retrieval.unknown_sections(docs, old) == []
    with pytest.raises(ValueError, match="unknown source"):
        docs_index.load_chunks(ROOT, source="code")


def test_search_docs_searches_the_documents_unless_asked_for_dbt():
    library = docs_index.load_library(ROOT)
    question = "Why is fee 500 a 0.05% tier?"
    default = docs_index.search_docs(library, question)
    assert default["ok"] and not any(c["id"].startswith("dbt/") for c in default["chunks"])
    asked = docs_index.search_docs(library, question, source="dbt")
    assert asked["ok"] and all(c["id"].startswith("dbt/") for c in asked["chunks"])
    for bad in ("code", None, 3):
        out = docs_index.search_docs(library, question, source=bad)
        assert out["ok"] is False and "source must be one of: docs, dbt." in out["error"]["message"]
