# Airflow: the daily pipeline

`univ3_daily` runs the pipeline of this repository once per UTC day, in order:

```
fetch_day -> load_swaps -> dbt_run -> dbt_test -> reconcile
```

Nothing about the loading or the dbt models changes: each task runs a command that already
exists. Airflow adds the order, the schedule, the retries and a place to see what happened.
Why Airflow, why version 3 and why a compose file of its own: [DECISIONS.md #25](../DECISIONS.md).

**Not tried by the agent that wrote it.** It had no Docker, so `docker compose up` has not run.
What was run: the DAG loaded by Airflow 3.3.2's `DagBag` (`tests/test_airflow_dag.py`, 5 passed)
and the tests of `--date` on a scripted chain.

## Start it

You need Docker, the existing `~/secrets/clickhouse.env`, and a new file with Airflow's secrets.

```bash
# 1. Secrets, outside the repository (names only in airflow/airflow.env.example)
cp airflow/airflow.env.example ~/secrets/airflow.env && chmod 600 ~/secrets/airflow.env
$EDITOR ~/secrets/airflow.env      # replace every CHANGE_ME; the generators are in the file

# 2. A directory OUTSIDE the working copy: landing zone, checkpoints, reports
export AIRFLOW_DATA_DIR=/var/lib/univ3-airflow
sudo mkdir -p "$AIRFLOW_DATA_DIR" && sudo chown "$(id -u)":0 "$AIRFLOW_DATA_DIR"
export AIRFLOW_UID="$(id -u)"

# 3. Build the image and start Airflow and ClickHouse
make airflow-up
docker compose -f docker-compose.yml -f docker-compose.airflow.yml ps
```

`AIRFLOW_DATA_DIR` must be the directory that already holds `landing/` if you have one
(the 1.24 million swaps): the tasks see it as `/data`, which `UNIV3_DATA_DIR` points at, and
`config.data_dir()` is how every command finds it. Open **http://127.0.0.1:8080**, user
`admin`, the password you put in `AIRFLOW_ADMIN_PASSWORD`. The port is bound to loopback only.

`make airflow-down` removes the Airflow containers and keeps ClickHouse, the Postgres volume
and your data directory.

## Run it

- **By hand:** in the UI, DAGs → `univ3_daily` → Trigger. Or
  `docker compose -f docker-compose.yml -f docker-compose.airflow.yml exec airflow-scheduler airflow dags trigger univ3_daily --logical-date 2026-09-26T00:00:00+00:00`
- **Unpause it** (the toggle, or `airflow dags unpause univ3_daily`) and it runs every day at
  00:30 UTC for the day that has just ended.
- **A backfill for a date range** (runs `fetch_day` with `--date` for each day, one at a time):
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.airflow.yml exec airflow-scheduler \
    airflow backfill create --dag-id univ3_daily \
    --from-date 2026-09-26 --to-date 2026-09-30 --max-active-runs 1
  ```
  (Airflow 3 replaced `airflow dags backfill` with `airflow backfill create`; add `--dry-run` to see the runs first, and
  `--help` for the rest.) Days must be consecutive and the
  first must follow the last day already landed, or `fetch_day` refuses: see below.

## What each task does

| Task | Command | What it needs |
|---|---|---|
| `fetch_day` | `python -m univ3_indexer.cli --date {{ ds }}` | `ALCHEMY_API_KEY`. Looks up the day's first and last block, fetches the swaps of the pools in `pools.yml` into `<data dir>/landing`. What is already landed is skipped. Refuses a day whose last block is not finalized yet |
| `load_swaps` | `make load` (`loader --mode incremental`) | ClickHouse. Idempotent; verifies ClickHouse against the landing zone and fails on a mismatch |
| `dbt_run` | `make dbt-seed`, then `run_dbt.py seed` and `run` | ClickHouse. Rebuilds the models in `onchain_dbt` |
| `dbt_test` | `run_dbt.py test` | ClickHouse. A failing dbt test fails the task |
| `reconcile` | `make sanity && make fetch-external && make reconcile` | ClickHouse; the GeckoTerminal API (no key). Any of the three exiting non-zero fails the task |

Every command starts with `set -euo pipefail`, so a task is red exactly when its command is.

**Where things are.** Task logs: the UI (a task instance → Logs), and on disk in the
scheduler container under `/opt/airflow/logs/dag_id=univ3_daily/run_id=…/task_id=…/`
(`docker compose … logs airflow-scheduler` for the scheduler itself). The reports
(`sanity.md`, `reconciliation.md`) land in `$AIRFLOW_DATA_DIR/reports`. The landing zone is
`$AIRFLOW_DATA_DIR/landing`; each day's plan and checkpoint are in
`$AIRFLOW_DATA_DIR/days/<date>/`.

## Airflow in this DAG: the concepts

**DAG.** A *directed acyclic graph*: tasks and the order between them, with no loops.
`airflow/dags/univ3_daily.py` is one: `fetch_day >> load_swaps >> dbt_run >> dbt_test >>
reconcile` means each task starts only when the one before it has succeeded. If `load_swaps`
fails, `dbt_run` does not run (it is marked `upstream_failed`).

**Operator and task.** An operator is a template for one unit of work; a task is an operator
used in a DAG with a `task_id`. `BashOperator` runs a shell command and succeeds when it exits
0: the simplest operator, and enough because each of our steps already is a command. Its
`bash_command` is a Jinja template, which is how `{{ ds }}` gets replaced.

**Scheduler, DAG processor, API server.** The *DAG processor* reads the files in `dags/` and
stores what DAGs exist. The *scheduler* looks at the schedule and at the state of runs and
decides which task instance runs next. The *API server* serves the UI and is where running
tasks report their state (Airflow 3: tasks no longer touch the database themselves). Postgres
is the *metadata database* where all of that state lives. These are the containers in
`docker-compose.airflow.yml`.

**Executor.** The part that actually starts the task. `LocalExecutor` starts each task as a
subprocess on the scheduler's machine: no workers to run, which is right for one machine and
five tasks. `CeleryExecutor` or `KubernetesExecutor` spread tasks over machines when you need to.

**Logical date and `ds`.** Every run is for a *data interval*, a period of time, and has a
*logical date*: the start of that interval. The run for the day 2026-10-01 has
`logical_date = 2026-10-01 00:30 UTC` and `{{ ds }}` = `2026-10-01`, **even though it starts at
2026-10-02 00:30 UTC**, when the day is over. `ds` is the day the data is *about*, not the
day the code *runs*; that is why `fetch_day` passes `--date {{ ds }}` and why a rerun a month
later fetches the same day. We use `CronDataIntervalTimetable("30 0 * * *")` so it works like
this; a plain cron string in Airflow 3 would run *at* the start of the day it names.

**Retries.** `retries=2, retry_delay=5 minutes` in `default_args`: a task that fails is tried
again, up to two more times, five minutes apart, before it is marked failed. It helps with
the transient: a network error, a provider rate limit. Retrying only makes sense because the
tasks are *idempotent*: running `fetch_day`, `load_swaps` or `dbt_run` twice leaves the same
result as once (files named after their block range, a loader that inserts only what is
missing, models rebuilt from scratch).

**Catchup.** If a DAG was off or paused, or has a `start_date` in the past, `catchup=True`
makes the scheduler create a run for every interval it missed. We set `catchup=False`: it
creates the run for the latest interval only. The days we have are already loaded; we do not
want a deploy to start 50 fetches.

**Backfill.** Running a DAG for a *chosen* range of past intervals, on purpose, by hand
(`airflow backfill create`). Catchup is the scheduler doing it by itself; backfill is you
asking. Each run gets its own `ds`, so `fetch_day` fetches that day. `max_active_runs=1`
makes the days go one after the other: they all append to one landing zone that must stay a
single range without gaps (`landing.check_coverage`).

**`start_date`.** 2026-08-10, the first full UTC day of the data (it begins in the middle of
2026-08-09). Airflow does not create runs before it.

## Know before you run it

- **Half past midnight.** The run for day D starts at D+1 00:30 UTC. The last block of D is
  finalized about 13 to 19 minutes after midnight, and `fetch_day` refuses a day beyond the
  finalized block, so at 00:00 it could fail all three tries; the owner chose 00:30 on
  2026-10-27 (ROADMAP R05). A backfill of past days is not affected.
- **Days in order.** `fetch_day` appends to the landing zone. The first day after what is
  landed is fine; a day further on is refused (it would leave a gap).
- **Failure alerts.** A task that fails its last try posts one comment on the issue
  "Pipeline alerts" (`dags/pipeline_alert.py`, its `on_failure_callback`): the task, the day,
  the run, the try and the type of the error, no log line. It needs `GITHUB_ALERT_TOKEN`, a
  fine-grained token with write access to this repository's issues only, and
  `GITHUB_ALERT_ISSUE`, the issue's number, both in your `airflow.env`. Without them the
  task's log says that no alert was sent, and nothing else changes: an alert never fails a
  task. Retries send nothing.
