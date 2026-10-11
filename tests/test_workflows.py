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
TESTS, AGENT = WORKFLOWS / "tests.yml", WORKFLOWS / "agent.yml"
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


@pytest.mark.parametrize("path", [TESTS, AGENT], ids=lambda p: p.name)
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


@pytest.mark.parametrize("path", [TESTS, AGENT], ids=lambda p: p.name)
def test_read_only_token_and_a_timeout_on_every_job(path):
    workflow = load(path)
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert 0 < job["timeout-minutes"] <= 20
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
    assert "tests/test_marts_fixture.py" in run
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


@pytest.mark.parametrize("path", [TESTS, AGENT], ids=lambda p: p.name)
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
