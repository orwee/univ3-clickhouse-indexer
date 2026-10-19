"""The DAG loads and has the shape the brief asks for. Skipped when Airflow is not installed:
it is not a dependency of the project (DECISIONS.md #25); the `airflow` job of
.github/workflows/tests.yml installs it with the official constraints and runs only this."""

import datetime as dt

import pytest

# Not "airflow": the repository's own airflow/ directory is importable as a namespace package.
pytest.importorskip("airflow.models")

from airflow.models import DagBag  # noqa: E402

from univ3_indexer import config  # noqa: E402

DAGS = config.REPO_ROOT / "airflow" / "dags"
ORDER = ["fetch_day", "load_swaps", "dbt_run", "dbt_test", "reconcile"]


@pytest.fixture(scope="module")
def dag():
    bag = DagBag(dag_folder=str(DAGS))
    assert bag.import_errors == {}
    return bag.dags["univ3_daily"]


def test_the_five_tasks_in_order(dag):
    assert sorted(dag.task_ids) == sorted(ORDER)
    for upstream, downstream in zip(ORDER, ORDER[1:], strict=False):
        assert dag.get_task(upstream).downstream_task_ids == {downstream}
    assert dag.get_task("reconcile").downstream_task_ids == set()


def test_retries_catchup_and_one_run_at_a_time(dag):
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    for task in dag.tasks:
        assert task.retries == 2
        assert task.retry_delay == dt.timedelta(minutes=5)


def test_it_is_a_daily_data_interval_that_starts_on_the_first_full_day(dag):
    # "@daily" is "0 0 * * *"; as a data interval, ds is the day that has just ended.
    assert type(dag.timetable).__name__ == "CronDataIntervalTimetable"
    assert dag.timetable.summary == "0 0 * * *"
    assert dag.start_date.date() == dt.date(2026, 8, 10)


def test_fetch_day_is_given_the_logical_day(dag):
    assert "{{ ds }}" in dag.get_task("fetch_day").bash_command
    assert "--date" in dag.get_task("fetch_day").bash_command


def test_every_task_is_one_of_the_commands_the_makefile_runs(dag):
    commands = {t.task_id: t.bash_command for t in dag.tasks}
    assert "make load" in commands["load_swaps"]
    assert "run_dbt.py run" in commands["dbt_run"]
    assert "run_dbt.py test" in commands["dbt_test"]
    for target in ("sanity", "fetch-external", "reconcile"):
        assert f"make {target}" in commands["reconcile"]
    assert all("set -euo pipefail" in command for command in commands.values())
