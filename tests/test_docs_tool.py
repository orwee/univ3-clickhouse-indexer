"""The docs tool in the loop, and the suite that asks questions of the documentation.

Scripted models only: no network, no key, no server. The properties that matter: the
baseline is exactly what it was when the tool is not asked for; an answer in words must cite
chunks that the search returned in that question; the key facts are checked by a plain
substring rule; the judge is shown only the cited chunks.
"""

import json
from decimal import Decimal

import pytest

from agent import budget, docs_index, llm, loop
from evalkit import judge, rag_run, variants
from univ3_indexer import config

ROOT = config.REPO_ROOT
HAIKU, OPUS = "claude-haiku-5-5", "claude-opus-5-5"
SMALL = llm.Usage(input_tokens=1000, output_tokens=100)


@pytest.fixture(scope="module")
def library():
    return docs_index.load_library(ROOT)


@pytest.fixture(scope="module")
def index(library):
    return library[docs_index.DOCS_SOURCE]


class NoTools:
    def describe_schema(self, tables=None):
        raise AssertionError("not called")

    def run_sql(self, sql):
        raise AssertionError("not called")


def search(query, **more):
    return llm.response(llm.tool_use("search_docs", {"query": query, **more}), usage=SMALL)


def submit(**fields):
    return llm.response(llm.tool_use("submit_answer", fields), usage=SMALL)


def ask(script, docs, question="What is net volume?"):
    model = llm.ScriptedLLM(script, HAIKU)
    result = loop.run(question, model, NoTools(), budget.DollarBudget("5"), docs=docs)
    return result, model


# --- the tool definitions -------------------------------------------------------------------


def test_without_docs_the_tools_are_the_baselines_and_nothing_else_changes():
    assert loop.tool_definitions(False) is loop.TOOL_DEFINITIONS
    assert [t["name"] for t in loop.TOOL_DEFINITIONS] == [
        "describe_schema",
        "run_sql",
        "submit_answer",
    ]
    result, model = ask(
        [
            submit(type="text", value="x", citations=["a"]),
            submit(type="refusal", refusal_reason="x"),
        ],
        docs=None,
    )
    assert "documents" not in result.to_json()
    assert model.calls[0]["tools"] == loop.TOOL_DEFINITIONS
    # the type text does not exist for the baseline: the model is told, and may go on
    assert result.status == "refused"
    assert "type must be one of: number, label, date, list, refusal." in json.dumps(
        result.tool_calls[0].summary
    )


def test_with_docs_there_is_a_fourth_tool_and_a_text_answer_with_citations(index, library):
    before = json.dumps(loop.TOOL_DEFINITIONS, sort_keys=True)
    definitions = loop.tool_definitions(True)
    assert [t["name"] for t in definitions] == [
        "describe_schema",
        "run_sql",
        "search_docs",
        "submit_answer",
    ]
    properties = definitions[3]["input_schema"]["properties"]
    assert properties["type"]["enum"][-1] == "text" and "citations" in properties
    assert json.dumps(loop.TOOL_DEFINITIONS, sort_keys=True) == before  # the baseline is intact
    source = definitions[2]["input_schema"]["properties"]["source"]
    assert source["enum"] == ["docs", "dbt"] and "only for a question about a column" in str(source)
    assert definitions[2]["input_schema"]["required"] == ["query"]
    result, model = ask([search("net volume"), submit(type="refusal", refusal_reason="x")], library)
    assert model.calls[0]["tools"] == definitions


# --- the search ---------------------------------------------------------------------------


def test_search_docs_returns_ids_and_text_and_clamps_k(index, library):
    out = docs_index.search_docs(library, "net volume round trips", k=100)
    assert out["ok"] and 1 <= len(out["chunks"]) <= docs_index.MAX_K
    assert all(set(c) == {"id", "text"} for c in out["chunks"])
    assert len(docs_index.search_docs(library, "net volume", k=2)["chunks"]) == 2
    assert len(docs_index.search_docs(library, "net volume", k=0)["chunks"]) == 1
    assert (
        len(docs_index.search_docs(library, "net volume", k=True)["chunks"]) == docs_index.DEFAULT_K
    )
    for bad in (None, "", "   ", 3):
        assert docs_index.search_docs(library, bad)["ok"] is False


# --- the grounding of an answer in words ---------------------------------------------------


def test_an_answer_that_cites_a_chunk_the_search_returned_is_answered(index, library):
    first = index.search("net volume round trips", 3)[0][1].id
    result, _ = ask(
        [
            search("net volume round trips", k=3),
            submit(type="text", value="Volume without round trips.", citations=[first]),
        ],
        library,
    )
    assert result.status == "answered" and result.answer["citations"] == [first]
    assert first in [d["id"] for d in result.documents]
    assert result.to_json()["documents"] == result.documents
    assert result.tool_calls[0].summary["ids"][0] == first


@pytest.mark.parametrize(
    "citations", [None, [], ["no.md#such"], "README.md#Limitations", [7]], ids=repr
)
def test_an_answer_with_no_valid_citation_is_ungrounded(index, citations, library):
    result, _ = ask(
        [search("net volume"), submit(type="text", value="Some words.", citations=citations)],
        library,
    )
    assert result.status == "ungrounded"
    assert result.reason == "the answer cites no chunk that search_docs returned"


def test_a_chunk_returned_in_another_question_does_not_count(index, library):
    first = index.search("net volume", 1)[0][1].id
    ask([search("net volume"), submit(type="refusal", refusal_reason="x")], library)
    result, _ = ask([submit(type="text", value="Words.", citations=[first])], library)
    assert result.status == "ungrounded"


def test_a_text_answer_needs_words_and_a_number_answer_still_needs_a_cell(index, library):
    result, _ = ask(
        [
            submit(type="text", value="", citations=["a"]),
            submit(type="number", value="5", citations=["a"]),
        ],
        library,
    )
    assert result.status == "ungrounded"  # the empty text was refused, the number had no rows
    assert "must be the answer, in words" in json.dumps(result.tool_calls[0].summary)
    assert result.reason == "the value is not a cell of the last result"


# --- the variant ---------------------------------------------------------------------------


def test_the_docs_variant_turns_the_tool_on_and_the_baseline_does_not():
    docs = variants.load("docs", ROOT / "evals" / "variants", ROOT)
    assert docs.docs_tool is True and docs.max_usd_per_question == Decimal("0.05")
    assert "search_docs" in docs.prompt_addendum and "citations" in docs.prompt_addendum
    assert "evals/variants/docs_addendum.md" in docs.files
    assert variants.load("baseline", ROOT / "evals" / "variants", ROOT).docs_tool is False


def test_docs_tool_must_be_a_boolean(tmp_path):
    (tmp_path / "v.yml").write_text("docs_tool: yes please\n")
    with pytest.raises(variants.VariantError, match="docs_tool must be true or false"):
        variants.load("v", tmp_path)


# --- the scoring ---------------------------------------------------------------------------

CASE = {
    "id": "c",
    "question": "What is net volume?",
    "split": "dev",
    "relevant": ["DECISIONS.md#18. Round trips are measured, not removed"],
    "key_facts": [
        {"fact": "no round trips", "any_of": ["without the legs", "excluding round trip"]},
        {"fact": "the column", "any_of": ["net_volume_usd"]},
    ],
}


def test_a_key_fact_is_a_substring_after_lower_casing_and_without_marks_or_number_commas():
    assert (
        rag_run.normalise("A `Net_Volume_USD` of **32,768** rows")
        == "a net_volume_usd of 32768 rows"
    )
    answer = {"value": "Volume WITHOUT THE LEGS.", "explanation": "See `net_volume_usd`."}
    assert rag_run.facts_present(CASE, answer) == [True, True]
    assert rag_run.facts_present(CASE, {"value": "Something else."}) == [False, False]
    assert rag_run.facts_present(CASE, None) == [False, False]
    number = {"key_facts": [{"fact": "n", "any_of": ["32,768"]}]}
    assert rag_run.facts_present(number, {"value": "32768 rows"}) == [True]


def result_of(
    status="answered",
    citations=("DECISIONS.md#18. Round trips are measured, not removed",),
    value="Volume without the legs, net_volume_usd.",
):
    return {
        "status": status,
        "usd": "0.001",
        "answer": {"type": "text", "value": value, "explanation": "", "citations": list(citations)},
        "documents": [{"id": c, "text": f"text of {c}"} for c in citations],
    }


def test_correct_needs_every_fact_and_an_answer_in_words():
    ok = rag_run.score_record(CASE, result_of())
    assert ok["correct"] and ok["cited_relevant"] and ok["retrieved_relevant"]
    half = rag_run.score_record(CASE, result_of(value="Volume without the legs."))
    assert half["facts_present"] == [True, False] and not half["correct"]
    refused = rag_run.score_record(
        CASE, {"status": "refused", "usd": "0", "answer": {"type": "refusal"}}
    )
    assert not refused["correct"] and not refused["has_text"]
    ungrounded = rag_run.score_record(CASE, result_of(status="ungrounded"))
    assert ungrounded["correct"] and not ungrounded["citations_valid"]  # right words, no source
    elsewhere = rag_run.score_record(CASE, result_of(citations=("README.md#Limitations",)))
    assert not elsewhere["cited_relevant"] and not elsewhere["retrieved_relevant"]
    assert rag_run.section_of("a.md#X~3") == "a.md#X"


def test_the_judge_is_shown_the_question_the_cited_chunks_and_the_answer_only():
    record = {"id": "c", "repetition": 1, "status": "ran", "result": result_of()}
    record["score"] = rag_run.score_record(CASE, record["result"])
    item = rag_run.judge_item(CASE, record)
    assert item.key == "c#1"
    text = judge.message(item)
    assert text.startswith("<question>\nWhat is net volume?\n</question>")
    assert '<chunk id="DECISIONS.md#18. Round trips are measured, not removed">' in text
    assert "<answer>\nVolume without the legs, net_volume_usd.\n</answer>" in text
    assert "final_sql" not in text
    record["result"] = result_of(status="ungrounded")
    record["score"] = rag_run.score_record(CASE, record["result"])
    assert rag_run.judge_item(CASE, record) is None


# --- the whole command, with scripted models -------------------------------------------------


def write_cases(path, cases):
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")


def run_main(tmp_path, monkeypatch, scripts, *extra, cases=None):
    monkeypatch.setenv("UNIV3_DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "cases.jsonl"
    write_cases(path, cases or [CASE])
    models = {
        HAIKU: llm.ScriptedLLM(scripts[HAIKU], HAIKU),
        OPUS: llm.ScriptedLLM(scripts[OPUS], OPUS),
    }
    out, report = tmp_path / "r.json", tmp_path / "r.md"
    code = rag_run.main(
        [str(path), "--split", "all", "--out", str(out), "--report", str(report), *extra],
        make_llm=lambda model_id: models[model_id],
        make_client=lambda database: None,
    )
    return code, out, report, models


def verdict(kind, reason="r"):
    return llm.response(
        llm.tool_use("submit_verdict", {"verdict": kind, "reason": reason}), usage=SMALL
    )


def test_the_command_asks_judges_scores_and_reports_with_the_budget_split(tmp_path, monkeypatch):
    section = CASE["relevant"][0]
    top = docs_index.Index(docs_index.load_chunks(ROOT)).search("net volume round trips", 8)
    cited = next(c.id for _, c in top if c.section == section)
    scripts = {
        HAIKU: [
            search("net volume round trips", k=8),
            submit(
                type="text", value="Volume without the legs, in net_volume_usd.", citations=[cited]
            ),
        ],
        OPUS: [verdict("faithful", "supported")],
    }
    code, out, report, models = run_main(tmp_path, monkeypatch, scripts)
    assert code == 0
    results = json.loads(out.read_text())
    assert results["state"] == "complete" and results["suite"] == "docs"
    assert results["label_note"] == "labels written by a model, not by a person"
    assert Decimal(results["agent_budget_usd"]) + Decimal(results["judge_budget_usd"]) == Decimal(
        results["budget_usd"]
    )
    s = results["summary"]
    assert (s["correct"]["k"], s["correct"]["n"]) == (1, 1)
    assert (s["grounded"]["k"], s["grounded"]["n"]) == (1, 1)
    assert s["by_status"] == {"answered": 1} and s["retrieved_relevant"]["k"] == 1
    assert Decimal(s["agent_usd"]) > 0 and Decimal(s["judge_usd"]) > 0
    text = report.read_text()
    assert "One run, not a measurement" in text and "written by a model, not by a person" in text
    # the judge was given the rubric of documents and the cited chunk
    call = models[OPUS].calls[0]
    assert call["system"] == (ROOT / "evals" / "judge_rubric_docs.md").read_text()
    assert f'<chunk id="{cited}">' in call["messages"][0]["content"]


def test_an_answer_with_an_invalid_citation_is_not_sent_to_the_judge_and_is_not_grounded(
    tmp_path, monkeypatch
):
    scripts = {
        HAIKU: [
            submit(type="text", value="Volume without the legs net_volume_usd.", citations=["x#y"])
        ],
        OPUS: [],
    }
    code, out, _, models = run_main(tmp_path, monkeypatch, scripts)
    assert code == 0 and models[OPUS].calls == []
    results = json.loads(out.read_text())
    assert results["summary"]["grounded"]["k"] == 0 and results["summary"]["grounded"]["n"] == 1
    assert results["verdicts"][0]["reason"] == rag_run.NOT_JUDGED_NO_CITATION


def test_a_budget_too_small_for_a_question_leaves_it_not_run(tmp_path, monkeypatch):
    scripts = {HAIKU: [], OPUS: []}
    code, out, report, _ = run_main(tmp_path, monkeypatch, scripts, "--max-usd", "0.01")
    assert code == 0
    results = json.loads(out.read_text())
    assert results["summary"]["not_run"] == 1 and results["summary"]["asked"] == 0
    assert "Not a whole run" in report.read_text()


def test_a_variant_without_the_docs_tool_stops_the_run(tmp_path, monkeypatch, capsys):
    scripts = {HAIKU: [], OPUS: []}
    code, *_ = run_main(tmp_path, monkeypatch, scripts, "--variant", "baseline")
    assert code == 2 and "does not set docs_tool" in capsys.readouterr().err


def test_a_case_that_points_at_a_section_that_does_not_exist_stops_the_run(
    tmp_path, monkeypatch, capsys
):
    bad = dict(CASE, relevant=["README.md#No such heading"])
    code, *_ = run_main(tmp_path, monkeypatch, {HAIKU: [], OPUS: []}, cases=[bad])
    assert code == 2 and "do not exist" in capsys.readouterr().err


def test_the_report_command_renders_a_docs_results_file_without_the_agent_group(
    tmp_path, monkeypatch
):
    code, out, _, _ = run_main(
        tmp_path, monkeypatch, {HAIKU: [submit(type="refusal", refusal_reason="x")], OPUS: []}
    )
    assert code == 0
    from evalkit import report

    text = report.render(json.loads(out.read_text()))
    assert text.startswith("# Documentation suite: docs, split all")
    assert report.render(json.loads(out.read_text()), top_only=True) == text


def test_the_loop_passes_the_source_the_model_asked_for(library):
    result, _ = ask(
        [search("fee tier", source="dbt"), submit(type="refusal", refusal_reason="x")], library
    )
    assert result.documents and all(c["id"].startswith("dbt/") for c in result.documents)
    result, _ = ask([search("fee tier"), submit(type="refusal", refusal_reason="x")], library)
    assert result.documents and not any(c["id"].startswith("dbt/") for c in result.documents)
