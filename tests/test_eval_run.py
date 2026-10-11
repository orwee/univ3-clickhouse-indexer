"""The runner and the report, with a scripted model. No network.

The runner tests ask real cases of the golden set on the marts fixture in a `test_*`
database. The model is scripted from the case itself: it runs the case's own reference
query and submits what the test tells it to. The real server has no read-only user, so for
these tests only the reader variables carry the test connection's own credentials, as in
tests/test_agent_loop.py: what is exercised is the runner, not the grants.
"""

import hashlib
import json
from decimal import Decimal

import pytest

from agent import __main__ as agent_cli
from agent import llm, loop
from evalkit import fixture, golden, report, run, score
from univ3_indexer import config

GOLDEN = config.REPO_ROOT / "evals" / "golden.jsonl"
OPUS = "claude-opus-5-5"  # the arithmetic below is written for this model's prices
PER_CALL = llm.Usage(input_tokens=1000, output_tokens=100)  # $0.006 on OPUS


class FromTheCase:
    """A model that knows the golden file: for each question it runs that case's reference
    query and then submits. `wrong` ids get a wrong value, `refuse` ids are refused,
    `silent` ids never submit, `broken` ids fail with a model error."""

    def __init__(self, model, wrong=(), refuse=(), silent=(), broken=(), usage=PER_CALL):
        self.model = model
        self.by_question = {case["question"]: case for case in golden.load(GOLDEN)}
        self.wrong, self.refuse, self.silent, self.broken = wrong, refuse, silent, broken
        self.usage = usage
        self.asked: list[str] = []

    def complete(self, *, system, messages, tools, max_tokens):
        case = self.by_question[messages[0]["content"]]
        if len(messages) == 1:
            self.asked.append(case["id"])
        if case["id"] in self.broken:
            raise llm.LLMError(
                "BadRequestError: HTTP 400, invalid_request_error: nope",
                status_code=400,
                error_type="invalid_request_error",
            )
        if case["id"] in self.silent:
            return llm.response(llm.tool_use("describe_schema", {}), usage=self.usage)
        if case["answer_type"] == "refusal" or case["id"] in self.refuse:
            if case["id"] in self.wrong:
                answer = {"type": "number", "value": "0"}
            else:
                answer = {"type": "refusal", "refusal_reason": "The data does not hold it."}
            return llm.response(llm.tool_use("submit_answer", answer), usage=self.usage)
        if len(messages) == 1:
            call = llm.tool_use("run_sql", {"sql": case["reference_sql"]})
            return llm.response(call, usage=self.usage)
        value = case["expected"]
        if case["id"] in self.wrong:
            value = "wrong" if case["answer_type"] != "number" else "123456789"
        answer = {"type": case["answer_type"], "value": value, "sql": case["reference_sql"]}
        return llm.response(llm.tool_use("submit_answer", answer), usage=self.usage)


@pytest.fixture
def setup(clickhouse, marts_database, monkeypatch, tmp_path):
    real = config.load_clickhouse_config()
    values = (real.host, str(real.port), marts_database, real.user, real.password)
    for name, value in zip(config.AGENT_READER_NAMES.values(), values, strict=True):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(tmp_path / "data"))
    house = tmp_path / "warehouse.yml"
    house.write_text(
        f"database: {marts_database}\n"
        f"tables: [{', '.join(fixture.TABLES)}]\n"
        "limits: {row_cap: 50, max_iterations: 3, max_usd: 0.25}\n"
    )
    return {"config": str(house), "out": tmp_path / "results.json", "tmp": tmp_path}


def go(setup, model, *arguments):
    argv = [str(GOLDEN), "--config", setup["config"], "--out", str(setup["out"]), *arguments]
    code = run.main(argv, make_llm=lambda name: model)
    return code, json.loads(setup["out"].read_text()) if setup["out"].exists() else None


def test_a_run_on_the_dev_split_and_what_its_file_holds(setup, capsys):
    dev = [case for case in golden.load(GOLDEN) if case["split"] == "dev"]
    model = FromTheCase(OPUS)
    code, results = go(setup, model, "--variant", "perfect", "--split", "dev", "--model", OPUS)
    assert code == 0
    assert model.asked == [case["id"] for case in dev]  # each once, in the order of the file
    assert len(results["records"]) == len(dev) == results["cases_selected"]
    assert all(r["status"] == "ran" and r["score"]["correct"] for r in results["records"])
    summary = results["summary"]
    assert summary["partial"] is False and summary["not_run"] == 0
    assert summary["overall"]["correct"]["k"] == len(dev)
    assert set(summary["by_kind"]) == {"hand", "template", "unanswerable"}
    # What the file says about the run.
    assert (
        results["variant"] == "perfect" and results["model"] == OPUS and results["split"] == "dev"
    )
    assert len(results["commit"]) == 40
    assert results["golden_sha256"] == hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    prompt = loop.system_prompt(3, 50)
    assert results["system_prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert results["fixture_fingerprint"] == fixture.read_fingerprint()
    assert results["started"] <= results["ended"] and results["budget_usd"] == "5"
    assert results["limits"] == {"max_usd_per_question": "0.25", "max_iterations": 3, "row_cap": 50}
    # Every record carries the agent's whole result and its score.
    first = results["records"][0]
    assert first["result"]["status"] == "answered" and first["result"]["tool_calls"]
    assert first["result"]["final_sql"] == dev[0]["reference_sql"]
    assert first["score"] == score.score_case(dev[0], first["result"])
    assert results["spent_usd"] == str(sum(Decimal(r["result"]["usd"]) for r in results["records"]))
    assert "correct " + str(len(dev)) in capsys.readouterr().out


def test_wrong_answers_refusals_and_failures_are_recorded_as_they_ended(setup):
    cases = golden.load(GOLDEN)
    pick = lambda kind: [c["id"] for c in cases if c["kind"] == kind][:2]  # noqa: E731
    (t1, t2), (h1, h2), (u1, u2) = pick("template"), pick("hand"), pick("unanswerable")
    ids = setup["tmp"] / "ids.txt"
    ids.write_text("\n".join(["# six cases", t1, t2, h1, h2, u1, u2, ""]))
    model = FromTheCase(OPUS, wrong=(t2, u2), refuse=(h1,), silent=(h2,), broken=())
    code, results = go(setup, model, "--variant", "mixed", "--split", "all", "--ids", str(ids), "--model", OPUS)  # fmt: skip
    assert code == 0 and [r["id"] for r in results["records"]] == [t1, t2, h1, h2, u1, u2]
    ended = {r["id"]: (r["result"]["status"], r["score"]["correct"]) for r in results["records"]}
    assert ended == {
        t1: ("answered", True),
        t2: ("ungrounded", False),  # a value that is not in the last result, and wrong
        h1: ("refused", False),  # refusing a case that has an answer is wrong
        h2: ("no_answer", False),  # the cap: three model calls and no answer
        u1: ("refused", True),
        u2: ("ungrounded", False),  # answered when it should have refused
    }
    overall = results["summary"]["overall"]
    assert (overall["correct"]["k"], overall["correct"]["n"]) == (2, 6)
    assert (overall["execution_accuracy"]["k"], overall["execution_accuracy"]["n"]) == (1, 4)
    assert (overall["hallucination_rate"]["k"], overall["hallucination_rate"]["n"]) == (2, 6)
    assert overall["refusals"]["should_not_and_did"] == 1
    assert model.asked == [t1, t2, h1, h2, u1, u2]  # nothing was asked twice


def test_a_model_error_is_recorded_and_not_retried(setup):
    first = golden.load(GOLDEN)[0]["id"]
    model = FromTheCase(OPUS, broken=(first,))
    code, results = go(setup, model, "--variant", "broken", "--split", "all", "--limit", "2", "--model", OPUS)  # fmt: skip
    assert code == 0 and model.asked.count(first) <= 1
    record = results["records"][0]
    assert record["status"] == "ran" and record["result"]["status"] == "no_answer"
    assert record["result"]["reason"].startswith("llm_error: BadRequestError: HTTP 400")
    assert record["score"]["correct"] is False and record["result"]["usd"] == "0"
    assert results["records"][1]["score"]["correct"] is True  # the run went on


def test_a_run_that_stops_on_its_budget_is_partial_and_says_so(setup):
    """Each question costs $0.20 here and its ceiling is $0.25. On $0.60 the third question
    does not fit (0.40 spent + 0.25 > 0.60): two are asked and the rest are not run."""
    dear = llm.Usage(input_tokens=5000, output_tokens=4000)  # $0.10 a call on OPUS, two calls
    model = FromTheCase(OPUS, usage=dear)
    code, results = go(setup, model, "--variant", "short", "--split", "all", "--limit", "5",
                       "--max-usd", "0.60", "--model", OPUS)  # fmt: skip
    assert code == 0  # it executed; stopping on the budget is a result
    assert [r["status"] for r in results["records"]] == [
        "ran",
        "ran",
        "not_run",
        "not_run",
        "not_run",
    ]
    assert len(model.asked) == 2
    assert "does not fit" in results["records"][2]["why"]
    assert "score" not in results["records"][2] and "result" not in results["records"][2]
    summary = results["summary"]
    assert (summary["records"], summary["ran"], summary["not_run"]) == (5, 2, 3)
    assert summary["partial"] is True
    assert summary["overall"]["correct"]["n"] == 2  # the figures are over what ran
    assert results["spent_usd"] == "0.40" and results["budget_usd"] == "0.60"
    text = report.render(results)
    assert "PARTIAL RUN" in text and "3 of 5 questions were not asked" in text
    assert text.count("| not run |") == 3


def test_repetitions_ask_every_case_again(setup):
    model = FromTheCase(OPUS)
    code, results = go(setup, model, "--variant", "twice", "--split", "all", "--limit", "3",
                       "--repetitions", "2", "--model", OPUS)  # fmt: skip
    ids = [case["id"] for case in golden.load(GOLDEN)[:3]]
    assert [(r["id"], r["repetition"]) for r in results["records"]] == [
        *((i, 1) for i in ids), *((i, 2) for i in ids),
    ]  # fmt: skip
    rep = results["summary"]["repetitions"]
    assert rep["count"] == 2 and rep["always_passed"] == 3 and rep["spread"]["range"] == 0


def test_transcripts_and_the_ledger_go_to_the_data_directory_not_to_the_results(setup):
    model = FromTheCase(OPUS)
    go(setup, model, "--variant", "kept", "--split", "all", "--limit", "1", "--model", OPUS)
    data = setup["tmp"] / "data"
    (kept,) = (data / "evals").glob("*_kept_*/transcripts/*.json")
    turns = json.loads(kept.read_text())["turns"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert json.loads(turns[2]["content"][0]["content"])["rows"]  # the rows the model saw
    assert "rows" not in json.dumps(json.loads(setup["out"].read_text())["records"])
    booked = [
        json.loads(line) for line in (data / "agent" / "ledger.jsonl").read_text().splitlines()
    ]
    assert len(booked) == 2 and all(e["scope"].startswith("eval:") for e in booked)
    assert config.REPO_ROOT not in kept.parents


def test_without_the_reader_an_evaluation_does_not_start(setup, monkeypatch, capsys):
    for name in config.AGENT_READER_NAMES.values():
        monkeypatch.delenv(name)
    monkeypatch.setenv(config.AGENT_READER_POINTER, str(setup["tmp"] / "absent.env"))

    def never(**kwargs):
        raise AssertionError(f"a connection was opened as {kwargs.get('username')}")

    monkeypatch.setattr(agent_cli.clickhouse_connect, "get_client", never)
    used = []
    code = run.main([str(GOLDEN), "--variant", "x"], make_llm=lambda name: used.append(name))
    assert code == 2 and used == [] and not setup["out"].exists()
    assert "The read-only user is not available" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        (["--variant", "x", "--model", "claude-made-up-9"], "no price is recorded"),
        (["--variant", "x", "--max-usd", "plenty"], "--max-usd must be a number"),
        (["--variant", "x", "--limit", "0"], "no case was selected"),
        (["--variant", "x", "--repetitions", "0"], "--repetitions must be at least 1"),
    ],
)
def test_arguments_that_cannot_be_run_stop_before_anything_is_asked(arguments, says, capsys):
    assert run.main([str(GOLDEN), *arguments], make_llm=lambda name: pytest.fail("built")) == 2
    assert says in capsys.readouterr().err


def test_selecting_cases(tmp_path):
    cases = golden.load(GOLDEN)
    assert len(run.select(cases, "all", None, None)) == len(cases)
    dev = run.select(cases, "dev", None, None)
    assert dev and all(case["split"] == "dev" for case in dev)
    assert run.select(cases, "test", None, 4) == [c for c in cases if c["split"] == "test"][:4]
    ids = tmp_path / "ids.txt"
    ids.write_text(f"{cases[5]['id']}\n\n# a comment\n{cases[2]['id']}\n")
    assert [c["id"] for c in run.select(cases, "all", ids, None)] == [
        cases[2]["id"],
        cases[5]["id"],
    ]
    ids.write_text("no-such-case-001\n")
    with pytest.raises(ValueError, match="not in the golden file: no-such-case-001"):
        run.select(cases, "all", ids, None)


# --- the report --------------------------------------------------------------------------------


def a_results_file():
    """Built here, by hand, from four cases and what a run made of them."""
    cases = {
        "t-a-001": {"id": "t-a-001", "kind": "template", "family": "a", "answer_type": "number",
                    "expected": "100", "accepted": [], "tolerance": {"abs": "0.01", "rel": "0.001"}},
        "h-b-001": {"id": "h-b-001", "kind": "hand", "family": "b", "answer_type": "list",
                    "expected": ["x", "y"], "accepted": [], "tolerance": None},
        "u-c-001": {"id": "u-c-001", "kind": "unanswerable", "family": "c", "answer_type": "refusal",
                    "expected": None, "accepted": [], "tolerance": None},
        "u-c-002": {"id": "u-c-002", "kind": "unanswerable", "family": "c", "answer_type": "refusal",
                    "expected": None, "accepted": [], "tolerance": None},
    }  # fmt: skip

    def result(status, value=None, reason="", refusal=None, usd="0.01", ok=True):
        answer = None if status == "no_answer" else {"value": value, "refusal_reason": refusal}
        return {"status": status, "reason": reason, "answer": answer, "usd": usd, "seconds": 2.0,
                "tokens": {"input_tokens": 900, "output_tokens": 100},
                "tool_calls": [{"name": "run_sql", "summary": {"ok": ok}}]}  # fmt: skip

    made = [
        ("t-a-001", result("answered", "100.001")),
        ("h-b-001", result("ungrounded", ["y", "x"], "the value is not a cell of the last result", ok=False)),
        ("u-c-001", result("refused", refusal="Not in the | data.")),
    ]  # fmt: skip
    records = [
        {
            "id": i,
            "repetition": 1,
            "status": "ran",
            "result": r,
            "score": score.score_case(cases[i], r),
        }
        for i, r in made
    ]
    records.append(
        {"id": "u-c-002", "repetition": 1, "status": "not_run", "why": "the run's budget"}
    )
    return {
        "format": 1, "run_id": "r", "variant": "by-hand", "model": "some-model", "commit": "c" * 40,
        "system_prompt_sha256": "p" * 64, "golden_file": "golden.jsonl", "golden_sha256": "g" * 64,
        "fixture_fingerprint": {"exported_on": "2026-10-10", "built_from_commit": "f" * 40},
        "started": "2026-10-12T10:00:00+00:00", "ended": "2026-10-12T10:01:00+00:00",
        "split": "all", "repetitions": 1, "cases_selected": 4,
        "limits": {"max_usd_per_question": "0.25", "max_iterations": 6, "row_cap": 200},
        "budget_usd": "0.04", "spent_usd": "0.03",
        "summary": score.summarize(records, cases), "cases": cases, "records": records,
    }  # fmt: skip


def test_the_report_is_tables_only_and_says_what_the_file_says():
    results = a_results_file()
    text = report.render(results)
    for line in text.splitlines():
        assert line == "" or line.startswith("|") or line == "# Evaluation: by-hand", line
    for expected in (
        "| Variant | by-hand |",
        "| Model | some-model |",
        f"| Commit | {'c' * 40} |",
        f"| Golden file | golden.jsonl, SHA-256 {'g' * 64} |",
        f"| System prompt | SHA-256 {'p' * 64} |",
        "| Questions asked | 3 of 4 |",
        "| Not run | 1 |",
        "| Budget | $0.04 |",
        "| Spent | $0.03 |",
        "| PARTIAL RUN |",
        "| Correct, all cases | 2 of 3 = 66.7% [20.8%, 93.9%] |",
        "| Execution accuracy (cases with an answer) | 1 of 2 = 50.0% [9.5%, 90.5%] |",
        "| Refusal recall (cases with no answer that were refused) | 1 of 1 = 100.0% [20.7%, 100.0%] |",
        "| Hallucination rate | 1 of 3 = 33.3% [6.1%, 79.2%] |",
        "| Valid SQL (queries that ran) | 2 of 3 = 66.7% [20.8%, 93.9%] |",
        "| Should refuse | 1 | 0 |",
        "| Should not refuse | 0 | 2 |",
        "| Cost, USD | 0.01000 | 0.01000 | 0.01000 |",
        "| Per correct answer | 0.01500 |",
        "| t-a-001 | 1 | answered | yes | 100 | 100.001 |",
        "| h-b-001 | 1 | ungrounded (the value is not a cell of the last result) | NO | x, y | y, x |",
        "| u-c-001 | 1 | refused | yes | refusal | Not in the \\| data. |",
        "| u-c-002 | 1 | not run |  | — | — |",
        "| hand / b |",
        "| unanswerable |",
    ):
        assert expected in text, expected
    assert "Repetitions" not in text.replace("| Repetitions | 1 |", "")


def test_the_top_of_the_report_is_the_first_tables_only():
    results = a_results_file()
    top = report.render(results, top_only=True)
    assert top in report.render(results)[: len(top)] or report.render(results).startswith(
        top.rstrip("\n")
    )
    assert "Correct, all cases" in top and "PARTIAL RUN" in top
    assert "By family" not in top and "t-a-001" not in top


def test_the_report_command_writes_what_render_gives(tmp_path, capsys):
    results = a_results_file()
    source = tmp_path / "results.json"
    source.write_text(json.dumps(results))
    assert report.main([str(source), "--out", str(tmp_path / "report.md")]) == 0
    assert (tmp_path / "report.md").read_text() == report.render(json.loads(source.read_text()))
    assert report.main([str(source), "--top"]) == 0
    assert capsys.readouterr().out == report.render(results, top_only=True)


def test_nothing_in_the_report_comes_from_outside_the_file(monkeypatch):
    """Rendering reads the dictionary and nothing else: with the scorer and the golden
    loader removed, it gives the same text."""
    results = a_results_file()
    before = report.render(results)
    monkeypatch.setattr(score, "summarize", lambda *a, **k: pytest.fail("recomputed"))
    monkeypatch.setattr(golden, "load", lambda *a, **k: pytest.fail("read the golden file"))
    assert report.render(json.loads(json.dumps(results))) == before
    assert "evalkit.score" not in (config.REPO_ROOT / "src/evalkit/report.py").read_text()
