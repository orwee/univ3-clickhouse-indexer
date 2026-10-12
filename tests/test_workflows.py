"""The two workflows, read as files: what they may and may not do.

Nothing here runs a workflow. These tests keep the properties that matter when nobody is
looking: no secret where there should be none, every action pinned to a commit, inputs kept
out of shell scripts, and the model key in one step only.
"""

import json
import re
import subprocess
import sys

import pytest
import yaml

from agent import llm
from univ3_indexer import config

WORKFLOWS = config.REPO_ROOT / ".github" / "workflows"
TESTS, AGENT, EVAL, JUDGE = (
    WORKFLOWS / f"{name}.yml" for name in ("tests", "agent", "eval", "judge")
)
SUMMARY = config.REPO_ROOT / "scripts" / "agent_summary.py"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
EXPRESSION = "${{"
SECRET = re.compile(r"\$\{\{[^}]*\bsecrets\.")  # a secret used, not the word in a comment


def load(path):
    workflow = yaml.safe_load(path.read_text())
    workflow["on"] = workflow.pop(True)  # YAML reads the key `on` as a boolean
    return workflow


def steps(workflow):
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


@pytest.mark.parametrize("path", [TESTS, AGENT, EVAL, JUDGE], ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit_with_its_version_next_to_it(path):
    used = [step["uses"] for step in steps(load(path)) if "uses" in step]
    assert used and all(PINNED.fullmatch(action) for action in used), used
    for line in path.read_text().splitlines():
        if "uses:" in line:
            assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", line), line


def test_the_agent_workflow_pins_the_same_commits_as_the_tests_workflow():
    def pins(path):
        used = (step["uses"].split("@") for step in steps(load(path)) if "uses" in step)
        return {name: sha for name, sha in used}

    tests, agent = pins(TESTS), pins(AGENT)
    assert set(tests) == {"actions/checkout", "astral-sh/setup-uv"}
    assert {name: agent[name] for name in tests} == tests
    assert set(agent) - set(tests) == {"actions/upload-artifact"}


@pytest.mark.parametrize("path", [TESTS, AGENT, EVAL, JUDGE], ids=lambda p: p.name)
def test_read_only_token_and_a_timeout_on_every_job(path):
    workflow = load(path)
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        # Twenty minutes at most, except the evaluation: 180 questions take longer.
        assert 0 < job["timeout-minutes"] <= (60 if path == EVAL else 20)
        assert "permissions" not in job
    assert "pull_request_target" not in path.read_text().replace("never `pull_request_target`", "")


def test_the_tests_workflow_has_no_secret_and_no_environment():
    workflow = load(TESTS)
    assert set(workflow["on"]) == {"pull_request", "push"}
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert not SECRET.search(TESTS.read_text())
    assert all("environment" not in job for job in workflow["jobs"].values())
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert set(workflow["jobs"]) == {"lint-and-test", "demo", "warehouse"}


def test_the_warehouse_job_runs_the_reader_tests_and_fails_if_they_skip():
    run = "\n".join(step.get("run", "") for step in load(TESTS)["jobs"]["warehouse"]["steps"])
    assert "bash scripts/ci_warehouse.sh" in run
    for name in ("reader", "tools", "loop", "budget_fit", "guard"):
        assert f"tests/test_agent_{name}.py" in run
    assert "tests/test_marts_fixture.py" in run and "tests/test_golden.py" in run
    assert "tests/test_eval_run.py" in run
    assert 'if [ "$skipped" != "0" ]' in run and 'if [ "$reader" != "13" ]' in run


def test_the_agent_workflow_is_started_by_hand_only_in_the_agent_eval_environment():
    workflow = load(AGENT)
    assert list(workflow["on"]) == ["workflow_dispatch"]
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["question", "model", "max_usd"]
    assert inputs["question"]["required"] is True
    assert inputs["model"]["required"] is False and inputs["model"]["default"] == ""
    assert inputs["max_usd"]["default"] == "0.25"
    assert list(workflow["jobs"]) == ["ask"]
    assert workflow["jobs"]["ask"]["environment"] == "agent-eval"


@pytest.mark.parametrize("path", [TESTS, AGENT, EVAL, JUDGE], ids=lambda p: p.name)
def test_no_github_expression_is_written_inside_a_run_script(path):
    """An input or any other expression reaches the shell through `env:`, as a variable."""
    for step in steps(load(path)):
        assert EXPRESSION not in step.get("run", ""), step.get("name")


def test_the_model_key_is_given_to_the_step_that_runs_the_agent_and_to_no_other():
    workflow = load(AGENT)
    job = workflow["jobs"]["ask"]
    assert len(SECRET.findall(AGENT.read_text())) == 1
    assert "env" not in workflow and "env" not in job  # nothing is set for every step
    with_key = [s for s in job["steps"] if "ANTHROPIC_API_KEY" in json.dumps(s.get("env", {}))]
    assert [s["name"] for s in with_key] == ["Ask"]
    ask = with_key[0]
    assert ask["env"] == {
        "QUESTION": "${{ inputs.question }}",
        "MODEL": "${{ inputs.model }}",
        "MAX_USD": "${{ inputs.max_usd }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    }
    assert 'python -m agent "$QUESTION" "${arguments[@]}"' in ask["run"]
    assert "--group agent" in ask["run"] and "--json" in ask["run"]
    assert "ANTHROPIC_API_KEY" in config.API_KEY_NAMES


def test_the_agent_workflow_steps_in_order_and_the_summary_is_written_either_way():
    job = load(AGENT)["jobs"]["ask"]
    names = [step.get("name", step.get("uses", "").split("@")[0]) for step in job["steps"]]
    assert names == [
        "actions/checkout",
        "Install uv",
        "uv sync --frozen --group agent",
        "Start the warehouse",
        "Ask",
        "Summary",
        "Upload the result",
        "The status is answered or refused",
    ]
    by_name = {step.get("name"): step for step in job["steps"]}
    assert (
        by_name["Summary"]["if"] == "always()" and by_name["Upload the result"]["if"] == "always()"
    )
    assert "exit 1" not in by_name["Ask"]["run"]  # it never fails the job by itself
    verdict = by_name["The status is answered or refused"]["run"]
    assert "answered | refused) exit 0" in verdict and "exit 1" in verdict


# --- the eval workflow, in the image of the agent one ---------------------------------------


def test_the_eval_workflow_pins_the_same_commits_as_the_agent_workflow():
    def pins(path):
        return {step["uses"] for step in steps(load(path)) if "uses" in step}

    assert pins(EVAL) == pins(AGENT)  # the same actions at the same commits; one is used twice


def test_the_eval_workflow_is_started_by_hand_only_in_the_agent_eval_environment():
    workflow = load(EVAL)
    assert list(workflow["on"]) == ["workflow_dispatch"]
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert list(inputs) == [
        "variant", "split", "model", "repetitions", "max_usd", "limit", "only_errors",
    ]  # fmt: skip
    assert inputs["variant"]["required"] is True
    assert "evals/variants/" in inputs["variant"]["description"]
    assert inputs["only_errors"]["default"] == ""
    assert (
        inputs["split"]["options"] == ["dev", "test", "all"] and inputs["split"]["default"] == "dev"
    )
    assert inputs["model"]["default"] == "" and inputs["limit"]["default"] == ""
    assert inputs["repetitions"]["default"] == "1" and inputs["max_usd"]["default"] == "5"
    assert all(not inputs[name]["required"] for name in inputs if name != "variant")
    assert list(workflow["jobs"]) == ["evaluate"]
    assert workflow["jobs"]["evaluate"]["environment"] == "agent-eval"


def test_the_model_key_is_given_to_the_step_that_runs_the_evaluation_and_to_no_other():
    workflow = load(EVAL)
    job = workflow["jobs"]["evaluate"]
    assert len(SECRET.findall(EVAL.read_text())) == 1
    assert "env" not in workflow and "env" not in job
    with_key = [s for s in job["steps"] if "ANTHROPIC_API_KEY" in json.dumps(s.get("env", {}))]
    assert [s["name"] for s in with_key] == ["Evaluate"]
    evaluate = with_key[0]
    assert evaluate["env"] == {
        "VARIANT": "${{ inputs.variant }}",
        "SPLIT": "${{ inputs.split }}",
        "MODEL": "${{ inputs.model }}",
        "REPETITIONS": "${{ inputs.repetitions }}",
        "MAX_USD": "${{ inputs.max_usd }}",
        "LIMIT": "${{ inputs.limit }}",
        "ONLY_ERRORS": "${{ inputs.only_errors }}",
        "UNIV3_DATA_DIR": "${{ runner.temp }}/eval-data",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    }
    assert config.DATA_DIR_POINTER == "UNIV3_DATA_DIR"  # where the transcripts are written
    run = evaluate["run"]
    assert "python -m evalkit.run evals/golden.jsonl" in run and "--group agent" in run
    for flag, variable in [("--variant", "$VARIANT"), ("--split", "$SPLIT"), ("--limit", "$LIMIT"),
                           ("--repetitions", "$REPETITIONS"), ("--max-usd", "$MAX_USD"),
                           ("--model", "$MODEL"), ("--only-errors", "$ONLY_ERRORS")]:  # fmt: skip
        assert f'{flag} "{variable}"' in run, flag
    assert "--out eval-results.json" in run
    # With a file of earlier results, only its errors are asked: no split, no limit.
    only, normal = run.split('if [ -n "$ONLY_ERRORS" ]; then')[1].split("else", 1)
    assert "--only-errors" in only and "--split" not in only and "--limit" not in only
    assert "--split" in normal and "--repetitions" in normal


def test_the_eval_workflow_fails_only_when_the_run_could_not_execute():
    job = load(EVAL)["jobs"]["evaluate"]
    names = [step.get("name", step.get("uses", "").split("@")[0]) for step in job["steps"]]
    assert names == [
        "actions/checkout",
        "Install uv",
        "uv sync --frozen --group agent",
        "Start the warehouse",
        "Evaluate",
        "Report",
        "Upload the results and the report",
        "Upload the transcripts",
        "The evaluation executed",
    ]
    by_name = {step.get("name"): step for step in job["steps"]}
    assert "exit 1" not in by_name["Evaluate"]["run"]
    assert by_name["Report"]["if"] == "always()"
    assert "python -m evalkit.report eval-results.json --top" in by_name["Report"]["run"]
    assert "--out eval-report.md" in by_name["Report"]["run"]
    upload = by_name["Upload the results and the report"]
    assert upload["if"] == "always()" and upload["with"]["name"] == "eval-results"
    assert upload["with"]["path"].split() == ["eval-results.json", "eval-report.md"]
    # The step that asks has a limit of its own, under the job's: a run that takes too long
    # is stopped there, and what it had written is still reported and uploaded.
    assert 0 < by_name["Evaluate"]["timeout-minutes"] < job["timeout-minutes"]
    # The transcripts are a second artifact, taken from the data directory, never from the
    # working copy; they are uploaded whatever happened.
    transcripts = by_name["Upload the transcripts"]
    assert transcripts["if"] == "always()" and transcripts["with"]["name"] == "eval-transcripts"
    assert transcripts["with"]["path"] == "${{ runner.temp }}/eval-data/evals/"
    assert transcripts["uses"] == upload["uses"]
    verdict = by_name["The evaluation executed"]["run"]
    assert 'if [ "$code" != "0" ] || [ ! -f eval-results.json ]' in verdict
    # Nothing in the workflow looks at the score.
    text = EVAL.read_text()
    assert "correct" not in text.lower().replace("a low score is a result", "")
    assert "A low score is a result, not a" in text


def test_the_fetch_script_names_the_files_by_date_and_variant_and_never_overwrites():
    script = (config.REPO_ROOT / "scripts" / "fetch_eval_results.sh").read_text()
    assert 'gh run download "$run_id" --name eval-results' in script
    assert (
        'target="$root/evals/results"' in script and "$name.json" in script and "$name.md" in script
    )
    # One variant is run several times on one day: the run's number is in the name.
    assert ')_$run_id"' in script and "<date>_<variant>_<RUN_ID>.json" in script
    assert "already exists; nothing was written" in script
    # The transcripts go to the data directory, which the project resolves and which is
    # never inside the working copy. Nothing of them is copied under the repository.
    assert 'gh run download "$run_id" --name eval-transcripts' in script
    assert "config.data_dir()" in script and 'kept="$data/evals/github-run-$run_id"' in script
    copies = [line.strip() for line in script.splitlines() if line.strip().startswith("cp ")]
    assert [line for line in copies if "transcripts" in line] == [
        'cp -R "$download/transcripts" "$kept"'
    ]
    assert all('"$target/' in line or '"$kept"' in line for line in copies)
    assert "git " not in script.replace("git push", "")  # it commits and pushes nothing
    done = subprocess.run(  # noqa: S603 - this repository's script, stopped by its own check
        ["bash", str(config.REPO_ROOT / "scripts" / "fetch_eval_results.sh"), "not-a-number"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2 and "usage:" in done.stderr


# --- the summary script, run as the workflow runs it --------------------------------------

RESULT = {
    "question": "How many?",
    "model": llm.DEFAULT_MODEL,
    "status": "answered",
    "reason": "",
    "answer": {
        "type": "number",
        "value": "42",
        "unit": "rows",
        "sql": "SELECT count() AS n FROM t",
        "explanation": "Counts <all> rows & nothing else.",
        "refusal_reason": None,
    },
    "final_sql": "SELECT count() AS n FROM t WHERE a < 3",
    "tool_calls": [],
    "iterations": 3,
    "tokens": {
        "input_tokens": 12345,
        "output_tokens": 678,
        "cache_read_tokens": 0,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
    },
    "usd": "0.0015735",
    "seconds": 4.2,
}


def summary(tmp_path, result, code="0", stderr="", question="How many?"):
    (tmp_path / "result.json").write_text("" if result is None else json.dumps(result))
    (tmp_path / "code.txt").write_text(code)
    (tmp_path / "stderr.txt").write_text(stderr)
    files = [str(tmp_path / name) for name in ("result.json", "code.txt", "stderr.txt")]
    done = subprocess.run(  # noqa: S603 - this repository's script, with files of this test
        [sys.executable, str(SUMMARY), *files],
        capture_output=True,
        text=True,
        env={"QUESTION": question},
        check=True,
    )
    status = subprocess.run(  # noqa: S603
        [sys.executable, str(SUMMARY), "--status", files[0]],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout, status.stdout.strip()


def test_the_summary_has_the_answer_the_sql_the_status_the_tokens_the_cost_and_the_seconds(
    tmp_path,
):
    text, status = summary(tmp_path, RESULT)
    assert status == "answered"
    for expected in (
        "**Status: `answered`**",
        "<pre>42 rows</pre>",
        "<pre>SELECT count() AS n FROM t WHERE a &lt; 3</pre>",
        "| Input tokens | 12,345 |",
        "| Output tokens | 678 |",
        "| Cost | $0.0015735 |",
        "| Seconds | 4.2 |",
        "| Model calls | 3 |",
        f"| Model | `{llm.DEFAULT_MODEL}` |",
        "<pre>How many?</pre>",
    ):
        assert expected in text, expected
    assert "Counts &lt;all&gt; rows &amp; nothing else." in text


def test_what_the_model_or_the_question_wrote_is_shown_as_text_never_rendered(tmp_path):
    hostile = {
        **RESULT,
        "answer": {**RESULT["answer"], "value": "</pre><img src=x>", "explanation": "# big"},
        "final_sql": "SELECT '</pre><script>'",
    }
    text, _ = summary(tmp_path, hostile, question="<b>q</b> ```")
    assert "<img" not in text and "<script>" not in text and "<b>" not in text
    assert text.count("<pre>") == text.count("</pre>") == 4


@pytest.mark.parametrize(
    ("status", "says"),
    [
        ("refused", "<pre>The table has no rows.</pre>"),
        ("ungrounded", "**Answer, NOT grounded: do not trust**"),
        ("no_answer", "**Status: `no_answer`** (iteration_cap: 6 model calls without an answer)"),
    ],
)
def test_the_summary_of_every_other_status(tmp_path, status, says):
    result = {**RESULT, "status": status}
    if status == "refused":
        result["answer"] = {**RESULT["answer"], "refusal_reason": "The table has no rows."}
    if status == "no_answer":
        result["answer"], result["final_sql"] = None, None
        result["reason"] = "iteration_cap: 6 model calls without an answer"
    text, printed = summary(tmp_path, result, code="0" if status == "refused" else "1")
    assert printed == status and says in text
    if status == "no_answer":
        assert "<pre>none ran successfully</pre>" in text


def test_the_summary_says_why_a_model_call_failed(tmp_path):
    said = "llm_error: BadRequestError: HTTP 400, invalid_request_error: <b>max_tokens</b> required"
    result = {**RESULT, "status": "no_answer", "reason": said, "answer": None, "final_sql": None}
    text, status = summary(tmp_path, result, code="1")
    assert status == "no_answer"
    assert (
        "**Status: `no_answer`** (llm_error: BadRequestError: HTTP 400, "
        "invalid_request_error: &lt;b&gt;max_tokens&lt;/b&gt; required)"
    ) in text


def test_without_a_result_the_summary_says_so_and_shows_standard_error(tmp_path):
    text, status = summary(tmp_path, None, code="2", stderr="No model key: X is not set\n")
    assert status == ""
    assert "**No result.** `python -m agent` exited with `2`" in text
    assert "<pre>No model key: X is not set</pre>" in text
    text, status = summary(tmp_path, [1, 2], code="1")
    assert status == "" and "**No result.**" in text


def test_the_summary_is_what_the_command_line_prints_with_json(tmp_path):
    """The fields the summary reads are the ones `Result.to_json` writes."""
    from agent import loop

    produced = loop.Result(question="q", model=llm.DEFAULT_MODEL).to_json()
    for key in (
        "status",
        "reason",
        "answer",
        "final_sql",
        "iterations",
        "tokens",
        "usd",
        "seconds",
    ):
        assert key in produced and key in RESULT
    assert set(produced["tokens"]) == set(RESULT["tokens"])


# --- the judge workflow, in the image of the eval one ----------------------------------------


def test_the_judge_workflow_is_started_by_hand_only_in_the_agent_eval_environment():
    workflow = load(JUDGE)
    assert list(workflow["on"]) == ["workflow_dispatch"]
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["source", "model", "max_usd", "limit"]
    assert inputs["source"]["required"] is True
    assert all(not inputs[name]["required"] for name in inputs if name != "source")
    assert inputs["model"]["default"] == "" and inputs["max_usd"]["default"] == "2"
    assert list(workflow["jobs"]) == ["judge"]
    assert workflow["jobs"]["judge"]["environment"] == "agent-eval"
    pins = lambda path: {s["uses"] for s in steps(load(path)) if "uses" in s}  # noqa: E731
    assert pins(JUDGE) == pins(EVAL)


def test_the_model_key_is_given_to_the_step_that_runs_the_judge_and_to_no_other():
    workflow = load(JUDGE)
    job = workflow["jobs"]["judge"]
    assert len(SECRET.findall(JUDGE.read_text())) == 1
    assert "env" not in workflow and "env" not in job
    with_key = [s for s in job["steps"] if "ANTHROPIC_API_KEY" in json.dumps(s.get("env", {}))]
    assert [s["name"] for s in with_key] == ["Judge"]
    assert with_key[0]["env"] == {
        "SOURCE": "${{ inputs.source }}",
        "MODEL": "${{ inputs.model }}",
        "MAX_USD": "${{ inputs.max_usd }}",
        "LIMIT": "${{ inputs.limit }}",
        "UNIV3_DATA_DIR": "${{ runner.temp }}/judge-data",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    }
    run = with_key[0]["run"]
    assert 'python -m evalkit.judge "$SOURCE"' in run and "--group agent" in run
    assert '--max-usd "$MAX_USD"' in run and "--out judge-verdicts.json" in run
    assert '--model "$MODEL"' in run and '--limit "$LIMIT"' in run


def test_the_judge_workflow_needs_no_warehouse_and_fails_only_when_it_could_not_execute():
    job = load(JUDGE)["jobs"]["judge"]
    names = [step.get("name", step.get("uses", "").split("@")[0]) for step in job["steps"]]
    assert names == [
        "actions/checkout",
        "Install uv",
        "uv sync --frozen --group agent",
        "Judge",
        "Summary",
        "Upload the verdicts",
        "The judge executed",
    ]
    text = JUDGE.read_text()
    assert "ci_warehouse" not in text and "docker" not in text  # it runs no query
    by_name = {step.get("name"): step for step in job["steps"]}
    assert "exit 1" not in by_name["Judge"]["run"]
    assert 0 < by_name["Judge"]["timeout-minutes"] < job["timeout-minutes"]
    assert by_name["Summary"]["if"] == "always()"
    upload = by_name["Upload the verdicts"]
    assert upload["if"] == "always()" and upload["with"]["name"] == "judge-verdicts"
    assert upload["with"]["path"] == "judge-verdicts.json"
    verdict = by_name["The judge executed"]["run"]
    assert 'if [ "$code" != "0" ] || [ ! -f judge-verdicts.json ]' in verdict
