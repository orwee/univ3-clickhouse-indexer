"""The executor: the one piece that acts as `orwee`, on the owner's server, from cron.

What it does, each pass, and nothing else (ops/README.md has the setup):

1. **Merge.** For every open pull request labelled `night` and not `waiting-runs`, it reads
   the latest verdict of the review routine (a comment with the marker below). If the
   verdict is `merge` for the pull request's current head commit, the pull request touches
   no protected path, every check on that commit has passed and GitHub says it can be
   merged, it approves the pull request and merges it, pinned to that commit
   (`--match-head-commit`). If the regression check of the agent is waiting for an
   approval, it gives that approval first and merges on a later pass.
2. **Paid runs.** For every open pull request labelled `waiting-runs` whose verdict is
   `dispatch-runs` for its head commit, it starts the evaluation runs the verdict names
   (once per commit), approves their deployment, and when they have all finished posts one
   comment in the Inbox saying so, with their numbers, so that the next night fetches the
   results and applies the pre-registered rule.

Limits it keeps whatever a verdict says:

- **Spend.** A monthly cap (`MONTHLY_CAP_USD`) on what it lets the model key spend: the
  `max_usd` of every run it starts, and `REGRESSION_CHECK_USD` for every regression check it
  approves. Past the cap it does nothing paid and says so on the pull request.
- **Protected paths.** A pull request that changes the rules, the workflows, the
  dependencies, the deployment or this directory is never merged here: that stays the
  owner's merge (`PROTECTED`).
- **Closed lists.** Two verdicts act (`merge`, `dispatch-runs`); one workflow can be
  started (`eval.yml`), with the inputs in `INPUTS` only, each checked by a pattern.
- **One commit.** Everything is tied to the head commit the verdict names. A pull request
  that moved since its verdict is left alone until a new verdict names the new head.

What it is not: a barrier against the review routine itself. The verdict is a comment, and
the night and the review routine use the same GitHub account. What protects `main` is the
list above, the green checks and the review routine's own rules (AGENTS.md, section 9).

Standard library only, plus the `gh` command logged in as `orwee`. Every action is written
to the pull request or the Inbox, so the repository keeps the record; the state file only
remembers what was already done, so that a pass repeated is a pass with nothing to do.

    python3 executor.py              # one pass
    python3 executor.py --dry-run    # reads everything, changes nothing, prints what it would do
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY = "orwee/univ3-clickhouse-indexer"
EXPECTED_LOGIN = "orwee"
REVIEWERS = frozenset({"robertofd31", "orwee"})
INBOX = 94
MARKER = "<!-- univ3-review -->"

MONTHLY_CAP_USD = 10.0
REGRESSION_CHECK_USD = 0.10
REGRESSION_CHECK = "the regression check"
MAX_RUNS = 3
MAX_USD_PER_RUN = 2.0

# A change to any of these is merged by the owner, never here.
PROTECTED = (
    ".github/",
    "ops/",
    "AGENTS.md",
    "CLAUDE.md",
    "GOAL.md",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "pools.yml",
    "clickhouse/",
    "airflow/Dockerfile",
    "docker-compose",
    ".env",
)

WORKFLOW = "eval.yml"
INPUTS = {
    "variant": re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$"),
    "split": re.compile(r"^(dev|test|all)$"),
    "model": re.compile(r"^[a-z0-9.-]{0,64}$"),
    "repetitions": re.compile(r"^[1-3]$"),
    "max_usd": re.compile(r"^\d{1,2}(\.\d{1,2})?$"),
    "golden": re.compile(r"^evals/[A-Za-z0-9_./-]{1,80}\.jsonl$"),
    "suite": re.compile(r"^(sql|docs)$"),
    "limit": re.compile(r"^\d{0,4}$"),
}
BRANCH = re.compile(r"^night/[A-Za-z0-9._-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
PASSED = frozenset({"success", "skipped", "neutral"})


class Refused(Exception):
    """A verdict or a state this executor will not act on; the message says why."""


# --------------------------------------------------------------------------- GitHub


class Gh:
    """`gh`, as the owner's server has it. Reads always run; writes are skipped in a dry run."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def _run(self, args: list[str], stdin: str | None = None) -> str:
        done = subprocess.run(  # noqa: S603 - a fixed program, arguments built here
            ["gh", *args],  # noqa: S607 - gh from the PATH the README sets
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if done.returncode != 0:
            what = " ".join(args[:2])
            raise RuntimeError(f"gh {what} failed: {done.stderr.strip()[:300]}")
        return done.stdout

    def get(self, path: str) -> object:
        return json.loads(self._run(["api", path]) or "null")

    def get_all(self, path: str) -> list:
        out = self._run(["api", "--paginate", path, "--jq", ".[]"])
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def write(self, what: str, args: list[str], stdin: str | None = None) -> str:
        if self.dry_run:
            print(f"  dry run, not done: {what}")
            return ""
        return self._run(args, stdin)

    def post(self, what: str, path: str, body: dict, method: str = "POST") -> str:
        return self.write(what, ["api", "-X", method, path, "--input", "-"], json.dumps(body))


# --------------------------------------------------------------------------- state


@dataclass
class State:
    """What earlier passes did: the month's spend, the runs started, the one-off actions.

    Keep it. Losing it means repeated comments and a month's count that starts again from
    zero; the API's own monthly limit on the key is then the only cap left."""

    path: Path
    spend: list = field(default_factory=list)  # {"month", "usd", "what"}
    dispatched: dict = field(default_factory=dict)  # "pr@sha" -> [run ids]
    done: list = field(default_factory=list)  # keys of one-off actions and notes

    @classmethod
    def load(cls, path: Path) -> State:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                path, data.get("spend", []), data.get("dispatched", {}), data.get("done", [])
            )
        return cls(path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"spend": self.spend, "dispatched": self.dispatched, "done": self.done}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def spent(self, month: str) -> float:
        return round(sum(s["usd"] for s in self.spend if s["month"] == month), 2)


def month_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m")


# --------------------------------------------------------------------------- verdicts


@dataclass
class Verdict:
    kind: str
    pr: int
    sha: str
    runs: int = 0
    inputs: dict = field(default_factory=dict)
    url: str = ""


def parse_verdict(body: str) -> Verdict | None:
    """The verdict block of one comment, or None if the comment has none or a malformed one."""
    if MARKER not in body:
        return None
    fields: dict[str, str] = {}
    inputs: dict[str, str] = {}
    for raw in body.split(MARKER, 1)[1].splitlines():
        line = raw.strip().strip("`").strip()
        if line.startswith("INPUT "):
            key, _, value = line[len("INPUT ") :].partition("=")
            inputs[key.strip()] = value.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            if key.strip().isupper():
                fields.setdefault(key.strip(), value.strip())
    kind = fields.get("REVIEW-VERDICT", "")
    try:
        pr = int(fields.get("PR", ""))
        runs = int(fields.get("RUNS", "0") or 0)
    except ValueError:
        return None
    sha = fields.get("SHA", "")
    if not kind or not SHA.match(sha):
        return None
    return Verdict(kind=kind, pr=pr, sha=sha, runs=runs, inputs=inputs)


def latest_verdict(gh: Gh, number: int) -> Verdict | None:
    """The newest verdict comment on the pull request, written by an allowed account."""
    for comment in reversed(gh.get_all(f"repos/{REPOSITORY}/issues/{number}/comments")):
        if (comment.get("user") or {}).get("login") not in REVIEWERS:
            continue
        verdict = parse_verdict(comment.get("body") or "")
        if verdict and verdict.pr == number:
            verdict.url = comment.get("html_url", "")
            return verdict
    return None


def validate_runs(verdict: Verdict) -> float:
    """The dollars the verdict's runs may spend, or Refused with the reason."""
    if not 1 <= verdict.runs <= MAX_RUNS:
        raise Refused(f"RUNS must be 1 to {MAX_RUNS}, not {verdict.runs}")
    unknown = sorted(set(verdict.inputs) - set(INPUTS))
    if unknown:
        raise Refused(f"inputs not allowed: {', '.join(unknown)}")
    for key, value in verdict.inputs.items():
        if not INPUTS[key].match(value):
            raise Refused(f"input {key} has a value this executor does not accept")
    for key in ("variant", "max_usd"):
        if key not in verdict.inputs:
            raise Refused(f"input {key} is required")
    per_run = float(verdict.inputs["max_usd"])
    if not 0 < per_run <= MAX_USD_PER_RUN:
        raise Refused(f"max_usd must be above 0 and at most {MAX_USD_PER_RUN}")
    return round(per_run * verdict.runs, 2)


# --------------------------------------------------------------------------- actions


class Executor:
    def __init__(self, gh: Gh, state: State, now=time.time, sleep=time.sleep):
        self.gh, self.state, self.now, self.sleep = gh, state, now, sleep

    # -- small helpers

    def say(self, text: str) -> None:
        print(text)

    def comment_once(self, key: str, number: int, body: str) -> None:
        if key in self.state.done:
            return
        self.gh.post(
            f"comment on #{number}: {body.splitlines()[0]}",
            f"repos/{REPOSITORY}/issues/{number}/comments",
            {"body": body},
        )
        if not self.gh.dry_run:
            self.state.done.append(key)

    def can_spend(self, usd: float) -> bool:
        return self.state.spent(month_now()) + usd <= MONTHLY_CAP_USD + 1e-9

    def record_spend(self, usd: float, what: str) -> None:
        if not self.gh.dry_run:
            self.state.spend.append({"month": month_now(), "usd": usd, "what": what})

    def spend_line(self) -> str:
        return (
            f"Spent this month by the executor: ${self.state.spent(month_now()):.2f} "
            f"of ${MONTHLY_CAP_USD:.2f}."
        )

    def approve_waiting(self, run_id: int, environment: str, why: str) -> bool:
        """Approve the run's pending deployment to `environment`. True if one was approved."""
        pending = self.gh.get(f"repos/{REPOSITORY}/actions/runs/{run_id}/pending_deployments")
        ids = [
            p["environment"]["id"]
            for p in pending or []
            if p["environment"].get("name") == environment and p.get("current_user_can_approve")
        ]
        if not ids:
            return False
        self.gh.post(
            f"approve run {run_id} ({environment})",
            f"repos/{REPOSITORY}/actions/runs/{run_id}/pending_deployments",
            {"environment_ids": ids, "state": "approved", "comment": why},
        )
        return True

    # -- one pass

    def run(self) -> int:
        login = (self.gh.get("user") or {}).get("login")
        if login != EXPECTED_LOGIN:
            self.say(f"Refusing to run: gh is logged in as {login!r}, not {EXPECTED_LOGIN!r}.")
            return 2
        pulls = self.gh.get_all(f"repos/{REPOSITORY}/pulls?state=open&per_page=100")
        for pull in sorted(pulls, key=lambda p: p["number"]):
            labels = {label["name"] for label in pull.get("labels", [])}
            if "night" not in labels:
                continue
            try:
                if "waiting-runs" in labels:
                    self.paid_runs(pull)
                else:
                    self.merge(pull)
            except Refused as why:
                sha = pull["head"]["sha"]
                self.say(f"#{pull['number']}: refused: {why}")
                self.comment_once(
                    f"refused:{pull['number']}@{sha}:{why}",
                    pull["number"],
                    f"The executor did not act on `{sha[:7]}`: {why}.",
                )
        if not self.gh.dry_run:
            self.state.save()
        return 0

    def merge(self, pull: dict) -> None:
        number, sha = pull["number"], pull["head"]["sha"]
        verdict = latest_verdict(self.gh, number)
        if verdict is None or verdict.sha != sha:
            self.say(f"#{number}: no verdict for its head {sha[:7]}; waiting.")
            return
        if verdict.kind != "merge":
            self.say(f"#{number}: verdict is {verdict.kind!r}; nothing to do.")
            return
        if pull.get("base", {}).get("ref") != "main":
            raise Refused("its base is not main")
        files = [
            f["filename"]
            for f in self.gh.get_all(f"repos/{REPOSITORY}/pulls/{number}/files?per_page=100")
        ]
        protected = sorted(f for f in files if f.startswith(PROTECTED))
        if protected:
            raise Refused(
                "it changes protected paths, which only the owner merges: "
                + ", ".join(f"`{f}`" for f in protected[:8])
            )
        checks = self.gh.get(f"repos/{REPOSITORY}/commits/{sha}/check-runs?per_page=100")[
            "check_runs"
        ]
        if not any(c["name"] == "make lint, make test" for c in checks):
            self.say(f"#{number}: `make lint, make test` has not reported yet; waiting.")
            return
        waiting = [c for c in checks if c["status"] != "completed"]
        for check in waiting:
            if check["name"] == REGRESSION_CHECK and check["status"] == "waiting":
                self.approve_regression_check(number, sha)
        if waiting:
            self.say(f"#{number}: {len(waiting)} check(s) not finished; waiting.")
            return
        failed = sorted(c["name"] for c in checks if c["conclusion"] not in PASSED)
        if failed:
            raise Refused("checks did not pass: " + ", ".join(failed))
        detail = self.gh.get(f"repos/{REPOSITORY}/pulls/{number}")
        if detail.get("mergeable") is not True:
            self.say(
                f"#{number}: GitHub does not say it can be merged yet "
                f"({detail.get('mergeable_state')}); waiting."
            )
            return
        self.gh.write(
            f"approve #{number} at {sha[:7]}",
            [
                "pr",
                "review",
                str(number),
                "-R",
                REPOSITORY,
                "--approve",
                "--body",
                f"Approved by the executor on the review routine's verdict "
                f"({verdict.url}), at `{sha[:7]}`.",
            ],
        )
        self.gh.write(
            f"merge #{number} at {sha[:7]}",
            ["pr", "merge", str(number), "-R", REPOSITORY, "--merge", "--match-head-commit", sha],
        )
        self.say(f"#{number}: merged at {sha[:7]}.")

    def approve_regression_check(self, number: int, sha: str) -> None:
        key = f"regression:{number}@{sha}"
        if key in self.state.done:
            return
        if not self.can_spend(REGRESSION_CHECK_USD):
            raise Refused(
                f"approving the regression check would pass the monthly cap. {self.spend_line()}"
            )
        runs = self.gh.get(f"repos/{REPOSITORY}/actions/runs?head_sha={sha}&status=waiting")
        approved = 0
        for run in runs.get("workflow_runs", []):
            if run.get("path", "").endswith("eval-pr.yml") and self.approve_waiting(
                run["id"], "agent-eval-pr", f"The review routine said merge at {sha[:7]}."
            ):
                approved += 1
        if approved and not self.gh.dry_run:
            self.record_spend(REGRESSION_CHECK_USD, key)
            self.state.done.append(key)
            self.comment_once(
                f"note:{key}",
                number,
                f"The executor approved the regression check at `{sha[:7]}` "
                f"(counted as ${REGRESSION_CHECK_USD:.2f}). {self.spend_line()}",
            )

    def paid_runs(self, pull: dict) -> None:
        number, sha, branch = pull["number"], pull["head"]["sha"], pull["head"]["ref"]
        key = f"{number}@{sha}"
        if key in self.state.dispatched:
            self.follow_runs(number, sha, self.state.dispatched[key])
            return
        verdict = latest_verdict(self.gh, number)
        if verdict is None or verdict.sha != sha or verdict.kind != "dispatch-runs":
            self.say(f"#{number}: waiting-runs, no dispatch verdict for {sha[:7]}.")
            return
        if not BRANCH.match(branch):
            raise Refused(f"branch {branch!r} is not a night branch")
        usd = validate_runs(verdict)
        if not self.can_spend(usd):
            raise Refused(
                f"{verdict.runs} run(s) at up to ${usd:.2f} would pass the "
                f"monthly cap. {self.spend_line()}"
            )
        started = self.now()
        args = ["workflow", "run", WORKFLOW, "-R", REPOSITORY, "--ref", branch]
        for name, value in sorted(verdict.inputs.items()):
            args += ["-f", f"{name}={value}"]
        for i in range(verdict.runs):
            self.gh.write(f"start {WORKFLOW} on {branch} ({i + 1} of {verdict.runs})", args)
        if self.gh.dry_run:
            return
        ids = self.find_runs(branch, started, verdict.runs)
        if len(ids) != verdict.runs:
            raise Refused(
                f"started {verdict.runs} run(s) but found {len(ids)}; "
                "the owner should look at the Actions tab"
            )
        self.state.dispatched[key] = ids
        self.record_spend(usd, f"runs:{key}")
        self.state.save()
        self.comment_once(
            f"note:runs:{key}",
            number,
            f"The executor started {verdict.runs} run(s) of `{WORKFLOW}` on "
            f"`{sha[:7]}` (up to ${usd:.2f}), on the verdict {verdict.url}: "
            + ", ".join(f"https://github.com/{REPOSITORY}/actions/runs/{i}" for i in ids)
            + f". {self.spend_line()}",
        )
        self.follow_runs(number, sha, ids)

    def find_runs(self, branch: str, started: float, wanted: int) -> list[int]:
        since = dt.datetime.fromtimestamp(started - 60, dt.UTC)
        for _ in range(12):
            runs = self.gh.get(
                f"repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs"
                f"?branch={branch}&event=workflow_dispatch&per_page=20"
            )
            ids = sorted(
                r["id"]
                for r in runs.get("workflow_runs", [])
                if dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= since
            )
            if len(ids) >= wanted:
                return ids[-wanted:]
            self.sleep(10)
        return []

    def follow_runs(self, number: int, sha: str, ids: list[int]) -> None:
        conclusions = {}
        for run_id in ids:
            run = self.gh.get(f"repos/{REPOSITORY}/actions/runs/{run_id}")
            if run["status"] == "waiting":
                self.approve_waiting(
                    run_id,
                    "agent-eval",
                    f"Runs of #{number} at {sha[:7]}, started by the executor.",
                )
            conclusions[run_id] = run.get("conclusion") if run["status"] == "completed" else None
        if any(c is None for c in conclusions.values()):
            self.say(f"#{number}: runs still going: {ids}.")
            return
        lines = "\n".join(
            f"- https://github.com/{REPOSITORY}/actions/runs/{i}: {c}"
            for i, c in conclusions.items()
        )
        self.comment_once(
            f"inbox:runs-done:{number}@{sha}",
            INBOX,
            f"Runs done for #{number} at `{sha[:7]}`, started by the executor:\n{lines}\n\n"
            "Fetch each with `scripts/fetch_eval_results.sh RUN_ID` into that pull request's "
            "branch and apply its pre-registered rule (AGENTS.md, section 9).",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read everything, change nothing, print what would be done",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(
            os.environ.get("UNIV3_OPS_STATE", Path.home() / ".local/state/univ3-ops/state.json")
        ),
    )
    args = parser.parse_args(argv)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"== executor pass, {stamp}{' (dry run)' if args.dry_run else ''}")
    try:
        return Executor(Gh(dry_run=args.dry_run), State.load(args.state)).run()
    except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as problem:
        print(f"Stopped: {type(problem).__name__}: {problem}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
