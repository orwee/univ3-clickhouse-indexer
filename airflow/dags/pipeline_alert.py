"""The failure alert of univ3_daily: one comment on the GitHub issue "Pipeline alerts".

A task that has failed its last try calls `on_failure`, which posts one comment on the issue
named by `GITHUB_ALERT_ISSUE` in this repository, with the token in `GITHUB_ALERT_TOKEN`
(a fine-grained token that can write this repository's issues and nothing else). Both come
from the owner's env file, which docker-compose.airflow.yml passes to the Airflow containers;
airflow/airflow.env.example lists the names.

Without either of them, or when the post fails, it logs that no alert was sent and returns:
an alert never fails a task, and the run stays red in the UI as it would without one.

What the comment says is the DAG, the task, the day, the run, the try and the type of the
error, nothing else: no log line, no command and no error message, which could carry a URL
with a key in it. The token is sent in a header and never logged.

Standard library only: this runs in Airflow's own Python, which does not have the project's
packages (airflow/Dockerfile). Not a DAG: `.airflowignore` keeps the DAG processor out of it.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

REPOSITORY = "orwee/univ3-clickhouse-indexer"
API = "https://api.github.com"
TOKEN_VARIABLE = "GITHUB_ALERT_TOKEN"  # noqa: S105 - the name of a variable, not a value
ISSUE_VARIABLE = "GITHUB_ALERT_ISSUE"
PLACEHOLDERS = {"", "CHANGE_ME"}
TIMEOUT_SECONDS = 20

log = logging.getLogger(__name__)

# (url, headers, body, timeout) -> HTTP status. The tests pass a fake one.
Post = Callable[[str, dict[str, str], bytes, float], int]


def post_with_urllib(url: str, headers: dict[str, str], body: bytes, timeout: float) -> int:
    if not url.startswith(f"{API}/"):
        raise ValueError("an alert goes to the GitHub API only")
    # The scheme is checked above: only https to api.github.com reaches urlopen.
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def message(context: Mapping) -> str:
    """The comment's text, from what Airflow passes a failure callback."""
    ti = context.get("ti") or context.get("task_instance")
    dag_id = getattr(ti, "dag_id", None) or "univ3_daily"
    task_id = getattr(ti, "task_id", None) or "unknown task"
    run_id = getattr(ti, "run_id", None) or context.get("run_id") or "unknown run"
    try_number = getattr(ti, "try_number", None)
    exception = context.get("exception")
    lines = [
        f"**`{dag_id}` failed**: task `{task_id}`, day `{context.get('ds') or 'unknown'}`.",
        "",
        f"- Run: `{run_id}`",
        f"- Try: {try_number if try_number is not None else 'unknown'}",
        f"- Error: `{type(exception).__name__}`"
        if exception is not None
        else "- Error: none given",
        "",
        "The task's log is in the Airflow UI, and in the scheduler container under "
        f"`/opt/airflow/logs/dag_id={dag_id}/run_id={run_id}/task_id={task_id}/`.",
    ]
    return "\n".join(lines)


def on_failure(
    context: Mapping, *, environ: Mapping[str, str] = os.environ, post: Post = post_with_urllib
) -> bool:
    """Post the alert; True if GitHub accepted it. Never raises."""
    try:
        token = environ.get(TOKEN_VARIABLE, "").strip()
        issue = environ.get(ISSUE_VARIABLE, "").strip()
        if token in PLACEHOLDERS:
            log.warning("No alert sent: %s is not set.", TOKEN_VARIABLE)
            return False
        if not issue.isdigit():
            log.warning("No alert sent: %s is not an issue number.", ISSUE_VARIABLE)
            return False
        url = f"{API}/repos/{REPOSITORY}/issues/{int(issue)}/comments"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = json.dumps({"body": message(context)}).encode()
        status = post(url, headers, body, TIMEOUT_SECONDS)
    except Exception as error:  # an alert must never fail the task it reports
        log.warning("No alert sent: %s while posting it.", type(error).__name__)
        return False
    if status != 201:
        log.warning("No alert sent: GitHub answered HTTP %s.", status)
        return False
    log.info("Alert posted on issue #%s.", int(issue))
    return True
