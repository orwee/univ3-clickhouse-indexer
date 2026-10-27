"""The failure alert of univ3_daily (airflow/dags/pipeline_alert.py), without Airflow.

The module is standard library only, so these run in `make test`. A fake post stands in for
GitHub: no network, and no token but an obviously fake one.
"""

import json
import logging
import sys
import types

import pytest

from univ3_indexer import config

sys.path.insert(0, str(config.REPO_ROOT / "airflow" / "dags"))
import pipeline_alert  # noqa: E402

FAKE_TOKEN = "github_pat_fake_0000"


class FakePost:
    def __init__(self, status=201, error=None):
        self.status, self.error, self.calls = status, error, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.error is not None:
            raise self.error
        return self.status


def context(**extra):
    ti = types.SimpleNamespace(
        dag_id="univ3_daily",
        task_id="fetch_day",
        run_id="scheduled__2026-10-26T00:30",
        try_number=3,
    )
    return {"ti": ti, "ds": "2026-10-26", "exception": RuntimeError("never shown"), **extra}


ENV = {"GITHUB_ALERT_TOKEN": FAKE_TOKEN, "GITHUB_ALERT_ISSUE": "101"}


def test_it_posts_one_comment_on_the_issue_the_environment_names():
    post = FakePost()
    assert pipeline_alert.on_failure(context(), environ=ENV, post=post) is True
    [(url, headers, body, timeout)] = post.calls
    assert url == (
        "https://api.github.com/repos/orwee/univ3-clickhouse-indexer/issues/101/comments"
    )
    assert headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert timeout == pipeline_alert.TIMEOUT_SECONDS
    text = body["body"]
    for part in ("`univ3_daily` failed", "`fetch_day`", "`2026-10-26`", "Try: 3", "`RuntimeError`"):
        assert part in text, part


def test_the_comment_carries_no_error_message_and_no_token():
    """An error message can carry an RPC URL, and the URL the key: only the type is sent."""
    post = FakePost()
    leaky = RuntimeError("https://eth-mainnet.example/v2/SECRETKEY failed")
    pipeline_alert.on_failure(context(exception=leaky), environ=ENV, post=post)
    text = post.calls[0][2]["body"]
    assert "SECRETKEY" not in text and "example" not in text and FAKE_TOKEN not in text


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"GITHUB_ALERT_ISSUE": "101"},
        {"GITHUB_ALERT_TOKEN": "CHANGE_ME", "GITHUB_ALERT_ISSUE": "101"},
        {"GITHUB_ALERT_TOKEN": FAKE_TOKEN},
        {"GITHUB_ALERT_TOKEN": FAKE_TOKEN, "GITHUB_ALERT_ISSUE": "#101"},
    ],
)
def test_without_a_token_or_an_issue_it_logs_and_sends_nothing(environ, caplog):
    post = FakePost()
    with caplog.at_level(logging.WARNING, logger="pipeline_alert"):
        assert pipeline_alert.on_failure(context(), environ=environ, post=post) is False
    assert post.calls == []
    assert "No alert sent" in caplog.text


@pytest.mark.parametrize(
    "post", [FakePost(status=401), FakePost(status=404), FakePost(error=OSError("unreachable"))]
)
def test_a_failed_post_is_logged_and_never_raised(post, caplog):
    with caplog.at_level(logging.WARNING, logger="pipeline_alert"):
        assert pipeline_alert.on_failure(context(), environ=ENV, post=post) is False
    assert "No alert sent" in caplog.text
    assert FAKE_TOKEN not in caplog.text


def test_a_context_with_almost_nothing_still_gives_a_comment():
    post = FakePost()
    assert pipeline_alert.on_failure({}, environ=ENV, post=post) is True
    assert "Error: none given" in post.calls[0][2]["body"]


def test_the_real_post_refuses_anything_but_the_github_api():
    with pytest.raises(ValueError):
        pipeline_alert.post_with_urllib("file:///etc/passwd", {}, b"", 1)
