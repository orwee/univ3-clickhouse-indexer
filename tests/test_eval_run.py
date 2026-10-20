"""The runner and the report, with a scripted model. No network.

The runner tests ask real cases of the golden set on the marts fixture in a `test_*`
database. The model is scripted from the case itself: it runs the case's own reference
query and submits what the test tells it to. The real server has no read-only user, so for
these tests only the reader variables carry the test connection's own credentials, as in
tests/test_agent_loop.py: what is exercised is the runner, not the grants.

A variant is a file. The tests write theirs in a temporary directory; the last ones read
the committed evals/variants/baseline.yml.
"""

import dataclasses
import hashlib
import json
import os
from decimal import Decimal

import pytest

from agent import __main__ as agent_cli
from agent import llm, loop
from evalkit import fixture, golden, report, run, score, variants
from univ3_indexer import config

CACHE_SHA256 = "02f903a9dd3247d62e12443e266090cb9ee6e548ecc3a9757ff4a9a08e7c775c"

GOLDEN = config.REPO_ROOT / "evals" / "golden.jsonl"
OPUS = "claude-opus-5-5"  # the arithmetic below is written for this model's prices
PER_CALL = llm.Usage(input_tokens=1000, output_tokens=100)  # $0.006 on OPUS


class Killed(BaseException):
    """What a job that is killed looks like from inside: nothing gets to catch it."""


class FromTheCase:
    """A model that knows the golden file: for each question it runs that case's reference
    query and then submits. `wrong` ids get a wrong value, `refuse` ids are refused,
    `silent` ids never submit, `broken` ids fail with a model error, `limited` ids are
    answered 429 that many times first, and the run is killed when it reaches `kill_at`."""

    def __init__(self, model, wrong=(), refuse=(), silent=(), broken=(), usage=PER_CALL,
                 limited=None, kill_at=None):  # fmt: skip
        self.model = model
        self.by_question = {case["question"]: case for case in golden.load(GOLDEN)}
        self.wrong, self.refuse, self.silent, self.broken = wrong, refuse, silent, broken
        self.limited, self.kill_at = dict(limited or {}), kill_at
        self.usage = usage
        self.asked: list[str] = []
        self.systems: list[str] = []

    def complete(self, *, system, messages, tools, max_tokens):
        case = self.by_question[messages[0]["content"]]
        if case["id"] == self.kill_at:
            raise Killed
        if self.limited.get(case["id"], 0) > 0:
            self.limited[case["id"]] -= 1
            raise llm.LLMError("RateLimitError: HTTP 429", status_code=429, retry_after=2)
        if len(messages) == 1:
            self.asked.append(case["id"])
            self.systems.append(system)
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
    (tmp_path / "variants").mkdir()
    return {"config": str(house), "out": tmp_path / "results.json", "tmp": tmp_path}


def go(setup, model, *arguments, sleep=None):
    """Run with the variants of the temporary directory. A variant named on the command
    line that has no file yet gets one that sets nothing."""
    named = arguments[arguments.index("--variant") + 1] if "--variant" in arguments else None
    directory = setup["tmp"] / "variants"
    if named and "/" not in named and not (directory / f"{named}.yml").exists():
        (directory / f"{named}.yml").write_text("# sets nothing\n")
    argv = [str(GOLDEN), "--config", setup["config"], "--variants", str(directory)]
    if "--out" not in arguments:
        argv += ["--out", str(setup["out"])]
    slept = [] if sleep is None else sleep
    code = run.main([*argv, *arguments], make_llm=lambda name: model, sleep=slept.append)
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
    assert summary["errors"]["count"] == 0 and summary["scored"] == len(dev)
    assert summary["overall"]["correct"]["k"] == len(dev)
    assert set(summary["by_kind"]) == {"hand", "template", "unanswerable"}
    assert set(summary["by_split"]) == {"dev"}
    # What the file says about the run.
    assert results["format"] == 2 and results["state"] == "complete"
    assert results["not_reached"] == []
    assert (
        results["variant"] == "perfect" and results["model"] == OPUS and results["split"] == "dev"
    )
    file = setup["tmp"] / "variants" / "perfect.yml"
    assert results["variant_files"] == {
        file.as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
    }
    assert len(results["commit"]) == 40
    assert results["golden_sha256"] == hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    prompt = loop.system_prompt(3, 50)
    assert results["system_prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert set(model.systems) == {prompt}
    assert results["fixture_fingerprint"] == fixture.read_fingerprint()
    assert results["started"] <= results["ended"] == results["written"]
    assert results["budget_usd"] == "5"
    assert results["limits"] == {"max_usd_per_question": "0.25", "max_iterations": 3, "row_cap": 50}
    # Every record carries the agent's whole result and its score.
    first = results["records"][0]
    assert first["result"]["status"] == "answered" and first["result"]["tool_calls"]
    assert first["result"]["final_sql"] == dev[0]["reference_sql"]
    assert first["score"] == score.score_case(dev[0], first["result"])
    assert results["spent_usd"] == str(sum(Decimal(r["result"]["usd"]) for r in results["records"]))
    assert "correct " + str(len(dev)) in capsys.readouterr().out


def test_the_rows_the_answer_was_checked_against_are_in_the_results_up_to_fifty(setup):
    """The fixture is public data, so the last result of every question is kept."""
    cases = golden.load(GOLDEN)
    one = next(c for c in cases if c["answer_type"] == "number")
    several = next(c for c in cases if c["answer_type"] == "list")
    none = next(c for c in cases if c["answer_type"] == "refusal")
    ids = setup["tmp"] / "ids.txt"
    ids.write_text("\n".join([one["id"], several["id"], none["id"]]))
    _, results = go(setup, FromTheCase(OPUS), "--variant", "rows", "--split", "all",
                    "--ids", str(ids), "--model", OPUS)  # fmt: skip
    kept = {r["id"]: r["result"]["last_result"] for r in results["records"]}
    assert kept[none["id"]] is None  # it never ran a query
    assert len(kept[one["id"]]["rows"]) == 1 == kept[one["id"]]["row_count"]
    assert score.value_matches(kept[one["id"]]["rows"][0][0], one["expected"], "number", one["tolerance"])  # fmt: skip
    assert [row[0] for row in kept[several["id"]]["rows"]] == several["expected"]
    assert all(len(k["rows"]) <= loop.KEPT_ROWS == 50 for k in kept.values() if k)


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
        h2: ("no_answer", False),  # the cap: three model calls and no answer. The model's, so wrong
        u1: ("refused", True),
        u2: ("ungrounded", False),  # answered when it should have refused
    }
    overall = results["summary"]["overall"]
    assert (overall["correct"]["k"], overall["correct"]["n"]) == (2, 6)
    assert (overall["execution_accuracy"]["k"], overall["execution_accuracy"]["n"]) == (1, 4)
    assert (overall["hallucination_rate"]["k"], overall["hallucination_rate"]["n"]) == (2, 6)
    assert overall["refusals"]["should_not_and_did"] == 1
    assert results["summary"]["errors"]["count"] == 0  # the cap is not an error
    assert model.asked == [t1, t2, h1, h2, u1, u2]  # nothing was asked twice


def test_a_model_error_is_an_error_not_a_wrong_answer_and_the_run_goes_on(setup, capsys):
    first, second, third = (case["id"] for case in golden.load(GOLDEN)[:3])
    model = FromTheCase(OPUS, broken=(first,), wrong=(second,))
    code, results = go(setup, model, "--variant", "broken", "--split", "all", "--limit", "3", "--model", OPUS)  # fmt: skip
    assert code == 0 and model.asked.count(first) == 1  # asked once, not sent again
    record = results["records"][0]
    assert record["status"] == "ran" and record["result"]["status"] == "error"
    assert record["result"]["reason"].startswith("llm_error: BadRequestError: HTTP 400")
    assert record["score"]["error"] is True and record["score"]["correct"] is False
    assert record["result"]["usd"] == "0"
    summary = results["summary"]
    assert (summary["ran"], summary["scored"], summary["errors"]["count"]) == (3, 2, 1)
    assert summary["errors"]["cases"] == [{"id": first, "repetition": 1}]
    assert list(summary["errors"]["reasons"].values()) == [1]
    # Every accuracy is over the two that were answered: one right, one wrong.
    assert (summary["overall"]["correct"]["k"], summary["overall"]["correct"]["n"]) == (1, 2)
    assert summary["overall"]["cases"] == 2 and summary["partial"] is False
    assert "1 ended in ERROR" in capsys.readouterr().out
    text = report.render(results)
    assert text.splitlines()[2] == "| RUN WITH ERRORS |"  # at the top, before any figure
    assert "1 of 3 questions asked ended in an error" in text
    assert "every accuracy is over the other 2" in text
    assert f"| {first} | 1 | error (llm_error: BadRequestError: HTTP 400" in text
    assert "| not scored |" in text


def test_a_429_is_waited_for_and_the_wait_is_in_the_results(setup):
    first, second = (case["id"] for case in golden.load(GOLDEN)[:2])
    slept = []
    model = FromTheCase(OPUS, limited={first: 2, second: 4})
    code, results = go(setup, model, "--variant", "limited", "--split", "all", "--limit", "2",
                       "--model", OPUS, sleep=slept)  # fmt: skip
    assert code == 0 and slept == [2.0] * 5  # two for the first, three for the second
    one, two = results["records"]
    assert one["result"]["status"] == "answered" and one["score"]["correct"] is True
    assert [w["seconds"] for w in one["result"]["waits"]] == [2.0, 2.0]
    assert (one["score"]["waits"], one["score"]["waited_seconds"]) == (2, 4.0)
    # Refused a fourth time: the question ends in an error, after its three waits.
    assert two["result"]["status"] == "error" and len(two["result"]["waits"]) == 3
    assert two["result"]["reason"] == "llm_error: RateLimitError: HTTP 429"
    assert results["summary"]["waits"] == {"count": 5, "questions": 2, "seconds": 10.0}
    assert results["summary"]["errors"]["count"] == 1 and results["spent_usd"] == "0.012"
    assert "| Waits after a 429 or a 529 | 5 in 2 questions, 10 s in all |" in report.render(
        results
    )


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
    assert results["state"] == "complete" and results["not_reached"] == []  # it ended itself
    text = report.render(results)
    assert "PARTIAL RUN" in text and "3 of 5 questions were not asked" in text
    assert "UNFINISHED" not in text
    assert text.count("| not run |") == 3


def test_a_job_that_is_killed_leaves_a_whole_file_that_says_what_was_not_reached(
    setup, monkeypatch
):
    """The file is written after every question and replaced in one step. The run here is
    killed when it reaches the third of five questions."""
    ids = [case["id"] for case in golden.load(GOLDEN)[:5]]
    replaced = []
    real_replace = os.replace

    def replace(source, target):
        replaced.append((str(source), str(target)))
        real_replace(source, target)

    monkeypatch.setattr(run.os, "replace", replace)
    model = FromTheCase(OPUS, kill_at=ids[2])
    with pytest.raises(Killed):
        go(setup, model, "--variant", "killed", "--split", "all", "--limit", "5", "--model", OPUS)
    results = json.loads(setup["out"].read_text())  # a whole file, not half of one
    assert results["state"] == "unfinished" and results["ended"] is None
    assert results["not_reached"] == [{"id": i, "repetition": 1} for i in ids[2:]]
    assert [r["status"] for r in results["records"]] == ["ran", "ran", "not_run", "not_run", "not_run"]  # fmt: skip
    assert all(r["why"] == run.NOT_REACHED for r in results["records"][2:])
    summary = results["summary"]
    assert summary["partial"] is True and (summary["ran"], summary["not_run"]) == (2, 3)
    assert summary["overall"]["correct"]["n"] == 2 and results["spent_usd"] == "0.024"
    # Written once before the first question and once after each one: every time to a
    # temporary file next to it, then moved over the old one in one step.
    out = str(setup["out"])
    assert replaced == [(out + ".writing", out)] * 3
    assert not list(setup["tmp"].glob("*.writing"))
    text = report.render(results)
    assert text.splitlines()[2] == "| UNFINISHED RUN |"
    assert "after 2 of 5 questions" in text and "3 questions were not reached" in text
    assert "not finished; file last written" in text


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
    written = setup["out"].read_text()
    assert '"turns"' not in written and "tool_result" not in written
    booked = [
        json.loads(line) for line in (data / "agent" / "ledger.jsonl").read_text().splitlines()
    ]
    assert len(booked) == 2 and all(e["scope"].startswith("eval:") for e in booked)
    assert config.REPO_ROOT not in kept.parents


# --- only the errors, again ----------------------------------------------------------------


def test_only_errors_asks_again_the_cases_that_ended_in_error_and_writes_the_merged_file(setup):
    a, b, c, d = (case["id"] for case in golden.load(GOLDEN)[:4])
    first = FromTheCase(OPUS, broken=(a, c), wrong=(d,))
    go(setup, first, "--variant", "again", "--split", "all", "--limit", "4", "--model", OPUS)
    earlier = json.loads(setup["out"].read_text())
    assert earlier["summary"]["errors"]["cases"] == [
        {"id": a, "repetition": 1}, {"id": c, "repetition": 1},
    ]  # fmt: skip
    merged_file = setup["tmp"] / "merged.json"
    second = FromTheCase(OPUS, broken=(c,))  # a works now, c fails again
    code, _ = go(setup, second, "--only-errors", str(setup["out"]), "--out", str(merged_file))
    assert code == 0 and second.asked == [a, c]  # the two errors, and nothing else
    merged = json.loads(merged_file.read_text())
    assert json.loads(setup["out"].read_text()) == earlier  # the earlier file is as it was
    by_id = {r["id"]: r for r in merged["records"]}
    assert [r["id"] for r in merged["records"]] == [a, b, c, d]
    assert by_id[a]["result"]["status"] == "answered" and by_id[a]["score"]["correct"] is True
    assert by_id[a]["asked_again_after"].startswith("llm_error: BadRequestError: HTTP 400")
    assert by_id[c]["result"]["status"] == "error" and "asked_again_after" in by_id[c]
    assert by_id[b] == earlier["records"][1] and by_id[d] == earlier["records"][3]  # untouched
    summary = merged["summary"]
    assert (summary["scored"], summary["errors"]["count"]) == (3, 1)
    assert (summary["overall"]["correct"]["k"], summary["overall"]["correct"]["n"]) == (2, 3)
    (again,) = merged["reruns"]
    assert again["of_run"] == earlier["run_id"] == merged["run_id"] and again["ended"]
    assert again["asked_again"] == [{"id": a, "repetition": 1}, {"id": c, "repetition": 1}]
    assert again["not_asked_again"] == [] and again["spent_usd"] == "0.012"
    assert Decimal(merged["spent_usd"]) == Decimal(earlier["spent_usd"]) + Decimal("0.012")
    assert merged["state"] == "complete" and merged["variant"] == "again"
    assert "| Errors asked again | 2 in run " in report.render(merged)
    # And once more on the merged file: only c is left.
    third = FromTheCase(OPUS)
    final_file = setup["tmp"] / "final.json"
    go(setup, third, "--only-errors", str(merged_file), "--out", str(final_file))
    final = json.loads(final_file.read_text())
    assert third.asked == [c] and final["summary"]["errors"]["count"] == 0
    assert len(final["reruns"]) == 2 and final["summary"]["scored"] == 4


def test_only_errors_refuses_to_merge_two_different_things(setup, capsys):
    a = golden.load(GOLDEN)[0]["id"]
    go(setup, FromTheCase(OPUS, broken=(a,)), "--variant", "strict", "--split", "all",
       "--limit", "2", "--model", OPUS)  # fmt: skip
    earlier = setup["out"]
    capsys.readouterr()

    def refused(*arguments, golden_file=GOLDEN):
        argv = [str(golden_file), "--config", setup["config"], "--variants",
                str(setup["tmp"] / "variants"), "--out", str(setup["tmp"] / "never.json"),
                *arguments]  # fmt: skip
        code = run.main(argv, make_llm=lambda name: pytest.fail("a model was built"))
        assert code == 2 and not (setup["tmp"] / "never.json").exists()
        return capsys.readouterr().err

    assert "takes its cases and its model from the file" in refused(
        "--only-errors", str(earlier), "--limit", "1"
    )
    assert "is of variant 'strict', not 'other'" in refused(
        "--only-errors", str(earlier), "--variant", "other"
    )
    other_golden = setup["tmp"] / "golden.jsonl"
    other_golden.write_text(GOLDEN.read_text().replace("How", "how", 1))
    assert "was run on another golden file" in refused(
        "--only-errors", str(earlier), golden_file=other_golden
    )
    variant_file = setup["tmp"] / "variants" / "strict.yml"
    kept = variant_file.read_text()
    variant_file.write_text("max_usd_per_question: 0.2\n")
    assert "the files of variant 'strict' changed since" in refused("--only-errors", str(earlier))
    variant_file.write_text(kept)
    clean = setup["tmp"] / "clean.json"
    go(setup, FromTheCase(OPUS), "--only-errors", str(earlier), "--out", str(clean))
    capsys.readouterr()
    assert "no case ended in error, nothing to run" in refused("--only-errors", str(clean))
    assert "cannot be read" in refused("--only-errors", str(setup["tmp"] / "absent.json"))


# --- variants as files ---------------------------------------------------------------------


def test_a_variant_file_sets_the_model_the_notes_the_addendum_and_the_ceiling(setup, capsys):
    directory = setup["tmp"] / "variants"
    (directory / "notes.yml").write_text(
        "tables:\n  dim_pools:\n    description: One row per thing.\n"
        "    columns:\n      pool_label: Its name.\n"
    )
    (directory / "more.md").write_text("A volume is in whole units.\n")
    (directory / "full.yml").write_text(
        f"model: {OPUS}\nschema_notes: notes.yml\nprompt_addendum: more.md\n"
        "max_usd_per_question: 0.5\n"
    )
    first = golden.load(GOLDEN)[0]["id"]
    model = FromTheCase(OPUS, silent=(first,))  # it calls describe_schema, three times
    code, results = go(setup, model, "--variant", "full", "--split", "all", "--limit", "1")
    assert code == 0 and results["model"] == OPUS  # from the file: no --model was given
    assert results["limits"]["max_usd_per_question"] == "0.5"
    assert results["variant_files"] == {
        (directory / name).as_posix(): hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ("full.yml", "notes.yml", "more.md")
    }
    (system,) = set(model.systems)
    assert system.endswith("\n\nA volume is in whole units.\n")
    assert loop.WITH_DESCRIPTIONS in system and loop.NO_DESCRIPTIONS not in system
    assert results["system_prompt_sha256"] == hashlib.sha256(system.encode()).hexdigest()
    # The descriptions reached the model through describe_schema, next to names and types.
    (kept,) = (setup["tmp"] / "data" / "evals").glob("*_full_*/transcripts/*.json")
    schema = json.loads(json.loads(kept.read_text())["turns"][2]["content"][0]["content"])
    assert schema["descriptions"] == {"dim_pools": "One row per thing."}
    labels = [c for c in schema["tables"]["dim_pools"] if c["name"] == "pool_label"]
    assert labels[0]["description"] == "Its name." and labels[0]["type"]
    # --model may repeat what the file says, and may not contradict it.
    code = run.main([str(GOLDEN), "--variants", str(directory), "--variant", "full", "--model",
                     "claude-sonnet-5-5"], make_llm=lambda name: pytest.fail("built"))  # fmt: skip
    assert code == 2 and "--model cannot change it" in capsys.readouterr().err


def test_the_committed_baseline_sets_nothing():
    """evals/variants/baseline.yml is the agent as the code has it."""
    baseline = variants.load("baseline", run.DEFAULT_VARIANTS, config.REPO_ROOT)
    assert (baseline.model, baseline.descriptions, baseline.max_usd_per_question) == (
        None,
        None,
        None,
    )
    assert baseline.prompt_addendum == ""
    file = run.DEFAULT_VARIANTS / "baseline.yml"
    assert baseline.files == {
        "evals/variants/baseline.yml": hashlib.sha256(file.read_bytes()).hexdigest()
    }
    # So the baseline's prompt is the prompt of the code, with nothing appended.
    assert loop.system_prompt(6, 200, baseline.prompt_addendum, bool(baseline.descriptions)) == (
        loop.system_prompt(6, 200)
    )


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("colour: red\n", "unknown ['colour']; a variant may set model, schema_notes"),
        ("- a\n- list\n", "expected a mapping, or nothing at all"),
        ("model: 7\n", "model must be a model id"),
        ("schema_notes: absent.yml\n", "points at absent.yml, which is not a file"),
        ("prompt_addendum: empty.md\n", "the prompt addendum is empty"),
        ("max_usd_per_question: plenty\n", "max_usd_per_question must be a number"),
        ("max_usd_per_question: 0\n", "must be a positive number"),
        ("prompt_cache: sometimes\n", "prompt_cache must be true or false"),
        ("schema_notes: bad.yml\n", "expected one key, 'tables'"),
        ("schema_notes: odd.yml\n", "t: unknown ['colour']"),
        ("schema_notes: blank.yml\n", "t.c must be a non-empty text"),
    ],
)
def test_a_variant_file_that_is_not_the_four_settings_is_refused(tmp_path, text, says):
    (tmp_path / "v.yml").write_text(text)
    (tmp_path / "empty.md").write_text("  \n")
    (tmp_path / "bad.yml").write_text("columns: {}\n")
    (tmp_path / "odd.yml").write_text("tables:\n  t:\n    colour: red\n")
    (tmp_path / "blank.yml").write_text("tables:\n  t:\n    columns:\n      c: ''\n")
    with pytest.raises(variants.VariantError) as refusal:
        variants.load("v", tmp_path)
    assert says in str(refusal.value)


def test_a_variant_is_a_file_that_exists_and_its_files_are_pinned_by_content(tmp_path):
    with pytest.raises(variants.VariantError, match="no variant named 'absent'"):
        variants.load("absent", tmp_path)
    for name in ("../x", "a b", ""):
        with pytest.raises(variants.VariantError, match="letters, digits, dot, dash"):
            variants.load(name, tmp_path)
    (tmp_path / "notes.yml").write_text("tables:\n  t:\n    description: ' One   thing. '\n")
    (tmp_path / "v.yml").write_text("schema_notes: notes.yml\n")
    first = variants.load("v", tmp_path)
    assert first.descriptions == {"t": {"description": "One thing.", "columns": {}}}
    assert set(first.files) == {(tmp_path / n).as_posix() for n in ("v.yml", "notes.yml")}
    (tmp_path / "notes.yml").write_text("tables:\n  t:\n    description: Another thing.\n")
    second = variants.load("v", tmp_path)
    assert second.files != first.files  # the same names, another content: another variant
    assert variants.FIELDS == (
        "model",
        "schema_notes",
        "prompt_addendum",
        "max_usd_per_question",
        "prompt_cache",
        "provider",
        "docs_tool",
    )


def test_without_the_reader_an_evaluation_does_not_start(setup, monkeypatch, capsys):
    for name in config.AGENT_READER_NAMES.values():
        monkeypatch.delenv(name)
    monkeypatch.setenv(config.AGENT_READER_POINTER, str(setup["tmp"] / "absent.env"))

    def never(**kwargs):
        raise AssertionError(f"a connection was opened as {kwargs.get('username')}")

    monkeypatch.setattr(agent_cli.clickhouse_connect, "get_client", never)
    used = []
    code = run.main([str(GOLDEN), "--variant", "baseline"], make_llm=lambda name: used.append(name))
    assert code == 2 and used == [] and not setup["out"].exists()
    assert "The read-only user is not available" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        (["--variant", "baseline", "--model", "claude-made-up-9"], "no price is recorded"),
        (["--variant", "baseline", "--max-usd", "plenty"], "--max-usd must be a number"),
        (["--variant", "baseline", "--limit", "0"], "no case was selected"),
        (["--variant", "baseline", "--repetitions", "0"], "--repetitions must be at least 1"),
        (["--variant", "../x"], "a variant name is letters, digits, dot, dash and underscore"),
        (["--variant", "a b"], "a variant name is letters, digits, dot, dash and underscore"),
        (["--variant", "no-such-variant"], "no variant named 'no-such-variant'"),
        ([], "--variant is required"),
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


def a_results_file(*extra):
    """Built here, by hand, from four cases and what a run made of them. ``extra`` adds
    (case id, status, reason) records."""
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
        answer = None
        if status not in ("no_answer", "error"):
            answer = {"value": value, "refusal_reason": refusal}
        return {"status": status, "reason": reason, "answer": answer, "usd": usd, "seconds": 2.0,
                "tokens": {"input_tokens": 900, "output_tokens": 100},
                "tool_calls": [{"name": "run_sql", "summary": {"ok": ok}}]}  # fmt: skip

    extra = [(case_id, result(status, reason=reason)) for case_id, status, reason in extra]
    made = [
        ("t-a-001", result("answered", "100.001")),
        ("h-b-001", result("ungrounded", ["y", "x"], "the value is not a cell of the last result", ok=False)),
        ("u-c-001", result("refused", refusal="Not in the | data.")),
        *extra,
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
        "format": 2, "state": "complete", "not_reached": [], "written": "2026-10-12T10:01:00+00:00",
        "run_id": "r", "variant": "by-hand", "model": "some-model", "commit": "c" * 40,
        "variant_files": {"evals/variants/by-hand.yml": "v" * 64},
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
        f"| Variant file evals/variants/by-hand.yml | SHA-256 {'v' * 64} |",
        "| Model | some-model |",
        f"| Commit | {'c' * 40} |",
        f"| Golden file | golden.jsonl, SHA-256 {'g' * 64} |",
        f"| System prompt | SHA-256 {'p' * 64} |",
        "| Questions asked | 3 of 4 |",
        "| Not run | 1 |",
        "| Ended in an error, in no figure below | 0 |",
        "| Scored | 3 |",
        "| Waits after a 429 or a 529 | 0 in 0 questions, 0 s in all |",
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
        "| By split |",
    ):
        assert expected in text, expected
    assert "RUN WITH ERRORS" not in text and "UNFINISHED" not in text
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


def test_a_run_with_errors_says_so_at_the_top_and_leaves_them_out_of_every_accuracy():
    plain = a_results_file()
    results = a_results_file(
        ("u-c-002", "error", "llm_error: APIConnectionError"),
        ("t-a-001", "error", "budget: a call that can cost up to $0.3 does not fit"),
    )
    results["records"] = [r for r in results["records"] if r["status"] == "ran"]
    results["summary"] = score.summarize(results["records"], results["cases"])
    text = report.render(results)
    top = text.splitlines()
    assert top[0] == "# Evaluation: by-hand" and top[2] == "| RUN WITH ERRORS |"
    assert "2 of 5 questions asked ended in an error" in top[4]
    assert "every accuracy is over the other 3" in top[4] and "They cost $0.02." in top[4]
    assert "| llm_error: APIConnectionError | 1 |" in text
    assert "| Ended in an error, in no figure below | 2 |" in text and "| Scored | 3 |" in text
    # The accuracies are the ones of the same run without the two errors.
    for line in plain_lines(plain):
        assert line in text, line
    assert "| u-c-002 | 1 | error (llm_error: APIConnectionError) | not scored |" in text
    assert "RUN WITH ERRORS" in report.render(results, top_only=True)


def plain_lines(results):
    text = report.render(results)
    return [line for line in text.splitlines() if line.startswith(("| Correct, all", "| Execution", "| Hallucination", "| Valid SQL"))]  # fmt: skip


def test_the_variant_refuse_early_is_one_change_and_is_the_text_that_was_frozen():
    """One setting, a paragraph appended to the prompt. The two hashes are the ones written
    in docs/EVAL_PREREGISTRATION.md before any run of it: a word changed here after that
    page was committed would be another variant, and this test says so."""
    variant = variants.load("refuse-early", run.DEFAULT_VARIANTS, config.REPO_ROOT)
    assert (variant.model, variant.descriptions, variant.max_usd_per_question) == (
        None,
        None,
        None,
    )
    assert variant.files == {
        "evals/variants/refuse-early.yml": (
            "93af24a6913e9585812d84693aa757b0aa8b7adb7317f022a441b2f09dd23c5d"
        ),
        "evals/variants/refuse-early.md": (
            "efd4ecbb5915af6739c128ab1f64aaed353769044b8a7ee5de9b649325f498de"
        ),
    }
    assert variant.prompt_addendum.startswith("## When the data cannot answer")
    assert "Never spend" in variant.prompt_addendum
    # The prompt the model gets is the baseline's, then the paragraph, and nothing else.
    plain = loop.system_prompt(6, 200)
    with_it = loop.system_prompt(6, 200, addendum=variant.prompt_addendum)
    assert with_it.startswith(plain.rstrip("\n")) and with_it != plain
    assert with_it.endswith(variant.prompt_addendum.strip() + "\n")


def test_the_variant_cache_sets_one_thing_and_the_runner_hands_it_to_the_loop(setup):
    """prompt_cache: true and nothing else. The hash is the one written in the second entry
    of docs/EVAL_PREREGISTRATION.md before any run of it."""
    variant = variants.load("cache", run.DEFAULT_VARIANTS, config.REPO_ROOT)
    assert variant.prompt_cache is True
    assert (variant.model, variant.descriptions, variant.max_usd_per_question) == (
        None,
        None,
        None,
    )
    assert variant.prompt_addendum == ""
    assert variant.files == {"evals/variants/cache.yml": CACHE_SHA256}
    for name in ("baseline", "refuse-early"):
        assert variants.load(name, run.DEFAULT_VARIANTS, config.REPO_ROOT).prompt_cache is False
    # Through the runner: every call carries the prompt as a cached prefix, and the prompt
    # recorded for the run is the same text as without it.
    (setup["tmp"] / "variants" / "cached.yml").write_text("prompt_cache: true\n")
    model = FromTheCase(OPUS)
    code, results = go(setup, model, "--variant", "cached", "--limit", "2", "--model", OPUS)
    assert code == 0 and model.systems
    plain = loop.system_prompt(3, 50)
    assert all(system == llm.cached_prefix(plain) for system in model.systems)
    assert results["system_prompt_sha256"] == hashlib.sha256(plain.encode()).hexdigest()


# --- a second provider -----------------------------------------------------------------------

SONNET_CI_SHA256 = "8d8bfeb70ea5f7bb17f08df38643b3046325930f57d558a199ea07375fc09634"


def test_the_variant_sonnet_ci_names_the_provider_and_the_gateways_own_id():
    """The hash is the one written in the third entry of docs/EVAL_PREREGISTRATION.md."""
    variant = variants.load("sonnet-ci", run.DEFAULT_VARIANTS, config.REPO_ROOT)
    assert (variant.provider, variant.model) == ("cheaperinference", "claude-sonnet-5.5")
    assert variant.files == {"evals/variants/sonnet-ci.yml": SONNET_CI_SHA256}
    assert (variant.descriptions, variant.prompt_addendum, variant.prompt_cache) == (
        None,
        "",
        False,
    )
    direct = variants.load("sonnet", run.DEFAULT_VARIANTS, config.REPO_ROOT)
    assert variant.max_usd_per_question == direct.max_usd_per_question
    # Every other variant goes where it always went. No default changed.
    for name in ("baseline", "refuse-early", "cache", "sonnet"):
        assert variants.load(name, run.DEFAULT_VARIANTS, config.REPO_ROOT).provider == "anthropic"
    assert variants.main(["sonnet-ci", "--directory", str(run.DEFAULT_VARIANTS)]) == 0


def test_a_provider_is_one_of_two_and_a_variant_file_says_which(tmp_path, capsys):
    (tmp_path / "v.yml").write_text("provider: elsewhere\n")
    with pytest.raises(variants.VariantError, match="provider must be one of anthropic, cheaper"):
        variants.load("v", tmp_path)
    assert variants.main(["v", "--directory", str(tmp_path)]) == 2
    assert "provider must be one of" in capsys.readouterr().err
    assert set(variants.PROVIDERS) == set(llm.PROVIDERS)
    assert variants.DEFAULT_PROVIDER == llm.DEFAULT_PROVIDER


class Reporting(FromTheCase):
    """A model that reports, as a gateway does, what it billed and which model answered."""

    def complete(self, **request):
        response = super().complete(**request)
        return dataclasses.replace(
            response, billed_usd=Decimal("0.001"), served_model="claude-sonnet-5.5"
        )


def gateway_variant(setup, name="gate"):
    (setup["tmp"] / "variants" / f"{name}.yml").write_text(
        "provider: cheaperinference\nmodel: claude-sonnet-5.5\n"
    )
    return name


def test_the_results_say_the_provider_the_model_that_answered_and_what_was_billed(setup):
    name = gateway_variant(setup)
    model = Reporting("claude-sonnet-5.5")
    code, results = go(setup, model, "--variant", name, "--limit", "3")
    assert code == 0
    assert (results["provider"], results["model"]) == ("cheaperinference", "claude-sonnet-5.5")
    assert results["served_models"] == ["claude-sonnet-5.5"]
    calls = sum(record["result"]["iterations"] for record in results["records"])
    assert results["billed_questions"] == 3
    assert Decimal(results["billed_usd"]) == Decimal("0.001") * calls
    for record in results["records"]:
        made = record["result"]
        assert Decimal(made["billed_usd"]) == Decimal("0.001") * made["iterations"]
        assert made["served_models"] == ["claude-sonnet-5.5"]
        # The cost from the price table is still there, next to the one that was billed.
        assert Decimal(made["usd"]) > 0
    # A run through the default provider says so, and says that nothing was billed to it.
    code, plain = go(setup, FromTheCase(OPUS), "--variant", "plain", "--limit", "1",
                     "--model", OPUS, "--out", str(setup["tmp"] / "plain.json"))  # fmt: skip
    plain = json.loads((setup["tmp"] / "plain.json").read_text())
    assert plain["provider"] == "anthropic" and plain["billed_usd"] is None
    assert plain["billed_questions"] == 0 and plain["served_models"] == []


class Broke(FromTheCase):
    """The gateway's wallet is empty from the second question on."""

    def complete(self, **request):
        if len(self.asked) >= 1 and len(request["messages"]) == 1:
            self.asked.append("refused")
            raise llm.LLMError(
                "PaymentRequired: HTTP 402, invalid_request_error: insufficient balance",
                status_code=402,
                error_type="invalid_request_error",
            )
        return super().complete(**request)


def test_an_empty_wallet_ends_the_run_as_an_error_and_no_question_is_a_wrong_answer(setup):
    name = gateway_variant(setup)
    model = Broke("claude-sonnet-5.5")
    code, results = go(setup, model, "--variant", name, "--limit", "5")
    statuses = [(r["status"], (r.get("result") or {}).get("status")) for r in results["records"]]
    assert statuses == [("ran", "answered"), ("ran", "error")] + [("not_run", None)] * 3
    assert "HTTP 402" in results["records"][1]["result"]["reason"]
    assert all("wallet is empty" in r["why"] for r in results["records"][2:])
    assert len(model.asked) == 2, "the questions after it were not asked at all"
    summary = results["summary"]
    assert summary["errors"]["count"] == 1 and summary["not_run"] == 3
    # One scored question, and it was right: the refusals of payment are in no accuracy.
    assert (summary["overall"]["correct"]["k"], summary["overall"]["correct"]["n"]) == (1, 1)


def test_without_its_key_a_gateway_run_stops_and_never_turns_to_the_other_provider(
    setup, monkeypatch, capsys
):
    name = gateway_variant(setup)
    asked_for = []

    def no_key(key_name):
        asked_for.append(key_name)
        raise config.ConfigError(f"{key_name} is not set")

    monkeypatch.setattr(config, "require_api_key", no_key)
    monkeypatch.setattr(llm, "AnthropicLLM", lambda *a, **k: pytest.fail("a client was built"))
    argv = [str(GOLDEN), "--config", setup["config"], "--variants",
            str(setup["tmp"] / "variants"), "--variant", name, "--limit", "1",
            "--out", str(setup["out"])]  # fmt: skip
    assert run.main(argv) == 2
    said = capsys.readouterr().err
    assert "No model key for the provider cheaperinference" in said
    assert asked_for == ["CHEAPERINFERENCE_API_KEY"], "the other key was never asked for"
    assert not setup["out"].exists()
    # And an id of one provider is refused for the other before any key is read.
    (setup["tmp"] / "variants" / "mixed.yml").write_text("model: claude-sonnet-5.5\n")
    argv[argv.index(name)] = "mixed"
    assert run.main(argv) == 2
    assert (
        "is cheaperinference's and the provider asked for is anthropic" in capsys.readouterr().err
    )
    assert asked_for == ["CHEAPERINFERENCE_API_KEY"]


def test_the_variant_zero_day_is_one_paragraph_and_the_text_that_was_frozen():
    """The two hashes are the ones written in the fourth entry of
    docs/EVAL_PREREGISTRATION.md before any run of the variant."""
    variant = variants.load("zero-day", run.DEFAULT_VARIANTS, config.REPO_ROOT)
    assert variant.files == {
        "evals/variants/zero-day.yml": (
            "4fa515d7bcea8d3857420f51f926cd476fba72d6cb12677fd1224a889804980a"
        ),
        "evals/variants/zero-day.md": (
            "09f31ee929e61db02d4103d872c82f6d9b126f63fc1a61c8a6c7f3e5f205e2f8"
        ),
    }
    assert (variant.model, variant.descriptions, variant.max_usd_per_question) == (None, None, None)
    assert not variant.prompt_cache and variant.provider == "anthropic" and not variant.docs_tool
    # The prompt the variant gave is the default of its day plus the paragraph. The default
    # has changed since (decision 28), so the hash is read from the three results files,
    # which recorded what was sent, and not recomputed from today's prompt.
    frozen = "040507b25fa16ed7a755207090330eb3b8a16053f5d92bc54d1758fa675e3873"
    recorded = {
        json.loads(path.read_text())["system_prompt_sha256"]
        for path in (config.REPO_ROOT / "evals" / "results").glob("2026-10-20_zero-day_*.json")
    }
    assert recorded == {frozen}
    entry = (config.REPO_ROOT / "docs" / "EVAL_PREREGISTRATION.md").read_text()
    assert "# Fourth entry" in entry
    for sha in variant.files.values():
        assert sha in entry
