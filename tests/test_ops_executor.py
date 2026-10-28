"""The executor (ops/executor.py), against a scripted `gh`: no network, no account, no spend.

What matters here is what it refuses: a verdict for another commit or from another account,
a protected path, a failed check, a spend past the cap, an input it does not know. And that
what it does is pinned to the commit the verdict names.
"""

import importlib.util
import json
import sys

import pytest

from univ3_indexer import config

SPEC = importlib.util.spec_from_file_location("executor", config.REPO_ROOT / "ops" / "executor.py")
ex = importlib.util.module_from_spec(SPEC)
sys.modules["executor"] = ex  # dataclasses look the module up while the class is built
SPEC.loader.exec_module(ex)

R = ex.REPOSITORY
HEAD = "a" * 40
OLD = "b" * 40


class FakeGh(ex.Gh):
    def __init__(self, gets=None, lists=None, dry_run=False, login="orwee"):
        super().__init__(dry_run=dry_run)
        self.gets = {"user": {"login": login}, **(gets or {})}
        self.lists = lists or {}
        self.writes = []

    def get(self, path):
        return self.gets[path]

    def get_all(self, path):
        return self.lists.get(path, [])

    def _run(self, args, stdin=None):
        self.writes.append((args, json.loads(stdin) if stdin else None))
        return ""


def verdict(kind="merge", pr=7, sha=HEAD, extra=""):
    return f"Review.\n\n{ex.MARKER}\nREVIEW-VERDICT: {kind}\nPR: {pr}\nSHA: {sha}\n{extra}"


def comment(body, login="robertofd31"):
    return {"user": {"login": login}, "body": body, "html_url": "https://example.test/c/1"}


def pull(number=7, labels=("night",), sha=HEAD, ref="night/2026-10-28-x"):
    return {
        "number": number,
        "labels": [{"name": n} for n in labels],
        "head": {"sha": sha, "ref": ref},
        "base": {"ref": "main"},
    }


def checks(*pairs):
    runs = [{"name": "make lint, make test", "status": "completed", "conclusion": "success"}]
    runs += [{"name": n, "status": s, "conclusion": c} for n, s, c in pairs]
    return {"check_runs": runs}


def merge_world(comments, files=("README.md",), check_runs=None, mergeable=True, labels=None):
    return FakeGh(
        gets={
            f"repos/{R}/commits/{HEAD}/check-runs?per_page=100": check_runs or checks(),
            f"repos/{R}/pulls/7": {"mergeable": mergeable, "mergeable_state": "clean"},
        },
        lists={
            f"repos/{R}/pulls?state=open&per_page=100": [pull(labels=labels or ("night",))],
            f"repos/{R}/issues/7/comments": comments,
            f"repos/{R}/pulls/7/files?per_page=100": [{"filename": f} for f in files],
        },
    )


def run(gh, tmp_path, state=None):
    state = state or ex.State(tmp_path / "state.json")
    code = ex.Executor(gh, state, now=lambda: 0, sleep=lambda s: None).run()
    return code, state


def commands(gh):
    return [args[:2] for args, _ in gh.writes]


def test_parse_verdict_reads_the_block_and_rejects_malformed_ones():
    v = ex.parse_verdict(verdict(extra="RUNS: 3\nINPUT variant=baseline\nINPUT max_usd=1.00"))
    assert (v.kind, v.pr, v.sha, v.runs) == ("merge", 7, HEAD, 3)
    assert v.inputs == {"variant": "baseline", "max_usd": "1.00"}
    assert ex.parse_verdict("REVIEW-VERDICT: merge\nPR: 7\nSHA: " + HEAD) is None  # no marker
    assert ex.parse_verdict(verdict(sha="abc123")) is None  # not a full SHA
    assert ex.parse_verdict(verdict().replace("PR: 7", "PR: seven")) is None


def test_merges_on_a_verdict_for_the_head_pinned_to_that_commit(tmp_path):
    gh = merge_world([comment(verdict())])
    code, _ = run(gh, tmp_path)
    assert code == 0
    assert commands(gh) == [["pr", "review"], ["pr", "merge"]]
    merge = gh.writes[1][0]
    assert merge[merge.index("--match-head-commit") + 1] == HEAD
    assert "--merge" in merge


@pytest.mark.parametrize(
    "comments",
    [
        [],
        [comment(verdict(sha=OLD))],  # a verdict for an earlier commit
        [comment(verdict(kind="changes"))],
        [comment(verdict(), login="someone-else")],  # not an allowed account
        [comment(verdict(pr=8))],  # a verdict for another pull request
    ],
)
def test_does_nothing_without_a_merge_verdict_for_this_head(tmp_path, comments):
    gh = merge_world(comments)
    run(gh, tmp_path)
    assert gh.writes == []


def test_the_latest_verdict_wins(tmp_path):
    gh = merge_world([comment(verdict()), comment(verdict(kind="changes"))])
    run(gh, tmp_path)
    assert gh.writes == []


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/x.yml",
        "AGENTS.md",
        "GOAL.md",
        "ops/executor.py",
        "uv.lock",
        "docker-compose.yml",
        "pyproject.toml",
        "clickhouse/users.d/a.xml",
    ],
)
def test_never_merges_a_protected_path_and_says_so_once(tmp_path, path):
    gh = merge_world([comment(verdict())], files=("README.md", path))
    _, state = run(gh, tmp_path)
    assert commands(gh) == [["api", "-X"]]  # one comment, no review, no merge
    assert path in gh.writes[0][1]["body"]
    run(gh, tmp_path, state)
    assert len(gh.writes) == 1  # not repeated on the next pass


def test_a_failed_check_is_refused(tmp_path):
    gh = merge_world([comment(verdict())], check_runs=checks(("make demo", "completed", "failure")))
    run(gh, tmp_path)
    assert commands(gh) == [["api", "-X"]]
    assert "make demo" in gh.writes[0][1]["body"]


def test_waits_for_unfinished_checks_and_for_mergeability(tmp_path):
    gh = merge_world([comment(verdict())], check_runs=checks(("make demo", "in_progress", None)))
    run(gh, tmp_path)
    assert gh.writes == []
    gh = merge_world([comment(verdict())], mergeable=None)
    run(gh, tmp_path)
    assert gh.writes == []


def regression_world(spent=0.0):
    gh = merge_world(
        [comment(verdict())],
        check_runs=checks((ex.REGRESSION_CHECK, "waiting", None)),
    )
    gh.gets[f"repos/{R}/actions/runs?head_sha={HEAD}&status=waiting"] = {
        "workflow_runs": [{"id": 55, "path": ".github/workflows/eval-pr.yml"}]
    }
    gh.gets[f"repos/{R}/actions/runs/55/pending_deployments"] = [
        {"environment": {"id": 9, "name": "agent-eval-pr"}, "current_user_can_approve": True}
    ]
    return gh


def test_approves_the_regression_check_counts_it_and_merges_later(tmp_path):
    gh = regression_world()
    _, state = run(gh, tmp_path)
    approval = [body for args, body in gh.writes if "pending_deployments" in args[3]]
    assert approval == [
        {"environment_ids": [9], "state": "approved", "comment": approval[0]["comment"]}
    ]
    assert ["pr", "merge"] not in commands(gh)
    assert state.spent(ex.month_now()) == ex.REGRESSION_CHECK_USD
    before = len(gh.writes)
    run(gh, tmp_path, ex.State.load(tmp_path / "state.json"))
    assert len(gh.writes) == before  # approved once, not again


def test_refuses_the_regression_check_past_the_cap(tmp_path):
    gh = regression_world()
    state = ex.State(tmp_path / "state.json")
    state.spend.append({"month": ex.month_now(), "usd": ex.MONTHLY_CAP_USD, "what": "earlier"})
    run(gh, tmp_path, state)
    assert all("pending_deployments" not in args[3] for args, _ in gh.writes)
    assert "monthly cap" in gh.writes[0][1]["body"]


def test_refuses_to_run_as_anyone_but_the_expected_account(tmp_path):
    gh = merge_world([comment(verdict())])
    gh.gets["user"] = {"login": "robertofd31"}
    code, _ = run(gh, tmp_path)
    assert code == 2 and gh.writes == []


def test_a_dry_run_changes_nothing(tmp_path):
    gh = merge_world([comment(verdict())])
    gh.dry_run = True
    run(gh, tmp_path)
    assert gh.writes == []
    assert not (tmp_path / "state.json").exists()


RUNS_VERDICT = (
    "RUNS: 3\nINPUT variant=baseline\nINPUT golden=evals/golden_v2.jsonl\n"
    "INPUT split=all\nINPUT repetitions=1\nINPUT max_usd=1.00"
)


def runs_world(extra=RUNS_VERDICT, status="completed"):
    branch = "night/2026-10-28-x"
    gh = FakeGh(
        gets={
            f"repos/{R}/actions/workflows/eval.yml/runs?branch={branch}"
            "&event=workflow_dispatch&per_page=20": {
                "workflow_runs": [
                    {"id": i, "created_at": "2099-01-01T00:00:00Z"} for i in (101, 102, 103)
                ]
            },
            **{
                f"repos/{R}/actions/runs/{i}": {"status": status, "conclusion": "success"}
                for i in (101, 102, 103)
            },
        },
        lists={
            f"repos/{R}/pulls?state=open&per_page=100": [pull(labels=("night", "waiting-runs"))],
            f"repos/{R}/issues/7/comments": [comment(verdict(kind="dispatch-runs", extra=extra))],
        },
    )
    return gh


def test_starts_the_runs_once_counts_them_and_reports_in_the_inbox(tmp_path):
    gh = runs_world()
    _, state = run(gh, tmp_path)
    starts = [args for args, _ in gh.writes if args[:2] == ["workflow", "run"]]
    assert len(starts) == 3
    assert starts[0][starts[0].index("--ref") + 1] == "night/2026-10-28-x"
    assert "max_usd=1.00" in starts[0] and "golden=evals/golden_v2.jsonl" in starts[0]
    assert state.dispatched == {f"7@{HEAD}": [101, 102, 103]}
    assert state.spent(ex.month_now()) == 3.0
    inbox = [body for args, body in gh.writes if f"issues/{ex.INBOX}/comments" in args[3:4][0]]
    assert len(inbox) == 1 and "Runs done for #7" in inbox[0]["body"]
    before = len(gh.writes)
    run(gh, tmp_path, ex.State.load(tmp_path / "state.json"))
    assert len(gh.writes) == before  # nothing started or reported twice


def test_running_runs_are_followed_not_reported(tmp_path):
    gh = runs_world(status="in_progress")
    run(gh, tmp_path)
    assert all(f"issues/{ex.INBOX}/" not in " ".join(args) for args, _ in gh.writes)


@pytest.mark.parametrize(
    "extra, reason",
    [
        (RUNS_VERDICT.replace("RUNS: 3", "RUNS: 4"), "RUNS must be"),
        (RUNS_VERDICT.replace("max_usd=1.00", "max_usd=2.50"), "max_usd must be"),
        (RUNS_VERDICT + "\nINPUT only_errors=evals/x.json", "not allowed"),
        (RUNS_VERDICT.replace("variant=baseline", "variant=a;rm -rf /"), "does not accept"),
        (RUNS_VERDICT.replace("INPUT variant=baseline\n", ""), "variant is required"),
    ],
)
def test_refuses_runs_it_does_not_accept(tmp_path, extra, reason):
    gh = runs_world(extra=extra)
    run(gh, tmp_path)
    assert commands(gh) == [["api", "-X"]]
    assert reason in gh.writes[0][1]["body"]


def test_refuses_runs_past_the_cap(tmp_path):
    gh = runs_world()
    state = ex.State(tmp_path / "state.json")
    state.spend.append({"month": ex.month_now(), "usd": 8.0, "what": "earlier"})
    run(gh, tmp_path, state)
    assert all(args[:2] != ["workflow", "run"] for args, _ in gh.writes)
    assert "monthly cap" in gh.writes[0][1]["body"]


def test_state_round_trips(tmp_path):
    state = ex.State(tmp_path / "s" / "state.json")
    state.spend.append({"month": "2026-10", "usd": 1.5, "what": "x"})
    state.dispatched["7@" + HEAD] = [1]
    state.done.append("k")
    state.save()
    again = ex.State.load(tmp_path / "s" / "state.json")
    assert (again.spend, again.dispatched, again.done) == (state.spend, state.dispatched, ["k"])
    assert again.spent("2026-10") == 1.5 and again.spent("2026-11") == 0
