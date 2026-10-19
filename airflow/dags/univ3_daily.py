"""univ3_daily: the pipeline as it is today, once per UTC day.

fetch_day -> load_swaps -> dbt_run -> dbt_test -> reconcile

Each task is one command that already exists (see the Makefile). The DAG only decides the
order, the schedule and what to do when a command fails. airflow/README.md explains the
words used here.
"""

from __future__ import annotations

import datetime as dt

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG
from airflow.timetables.interval import CronDataIntervalTimetable

# Where the project lives inside the image (airflow/Dockerfile).
PROJECT = "/opt/project"

# The first full UTC day of the data: the data starts in the middle of 2026-08-09.
START_DATE = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)

# uv must not touch the network or the lock file when a task starts.
RUN = f"cd {PROJECT} && set -euo pipefail && "
DBT = "PYTHONPATH=src uv run --group dbt python scripts/run_dbt.py"

with DAG(
    dag_id="univ3_daily",
    description="Swaps of one UTC day: chain -> landing -> ClickHouse -> dbt -> reconciliation",
    start_date=START_DATE,
    # "@daily" as a data interval: the run for ds=2026-10-01 starts at 2026-10-02 00:00 UTC,
    # when that day is over. (Airflow 3 would otherwise run "@daily" AT the start of the day
    # it names, before there is anything to fetch.)
    schedule=CronDataIntervalTimetable("@daily", timezone="UTC"),
    catchup=False,
    # One run at a time: every run appends to the same landing zone, which has to stay one
    # range without gaps (landing.check_coverage), so two days must not be fetched together.
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": dt.timedelta(minutes=5)},
    tags=["univ3"],
) as dag:
    fetch_day = BashOperator(
        task_id="fetch_day",
        bash_command=RUN + "PYTHONPATH=src uv run python -m univ3_indexer.cli --date {{ ds }}",
    )
    load_swaps = BashOperator(
        task_id="load_swaps",
        bash_command=RUN + "make load",
    )
    # `seed` first: the pools table (from pools.yml) that the models join to.
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=RUN + f"make dbt-seed && {DBT} seed && {DBT} run",
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=RUN + f"{DBT} test",
    )
    reconcile = BashOperator(
        task_id="reconcile",
        bash_command=RUN + "make sanity && make fetch-external && make reconcile",
    )

    fetch_day >> load_swaps >> dbt_run >> dbt_test >> reconcile
