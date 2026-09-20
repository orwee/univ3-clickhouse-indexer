"""Run dbt with the ClickHouse credentials loaded from the secrets file, never printed.

    PYTHONPATH=src uv run --group dbt python scripts/run_dbt.py build
    PYTHONPATH=src uv run --group dbt python scripts/run_dbt.py test

profiles.yml reads everything through env_var(); this launcher is what puts the values
there, using the same config module as the rest of the project. It refuses to start if
dbt's target database is the raw database: dbt owns `onchain_dbt` and only reads `onchain`.
The one thing this launcher does to the raw database is CREATE TABLE IF NOT EXISTS for the
optional Nansen aggregate, empty, so that a build without an API key still works.
"""

from __future__ import annotations

import os
import sys

from univ3_indexer import config

DBT_DIR = config.REPO_ROOT / "dbt"
DEFAULT_TARGET_DATABASE = "onchain_dbt"


def ensure_optional_sources(database: str) -> None:
    """The one source that needs an API key to be filled. Created EMPTY when missing, so that
    `dbt build` works without Nansen: the model on top of it then has no rows. Nothing else
    is ever written to the raw database from here."""
    from univ3_indexer import clickhouse as ch
    from univ3_indexer import nansen

    ch.apply_ddl(ch.connect(database="default"), database, nansen.DAILY_DDL)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    c = config.load_clickhouse_config()
    target = os.environ.get("DBT_TARGET_DATABASE", DEFAULT_TARGET_DATABASE)
    if target == c.database:
        print(
            f"refusing to run: dbt would write into the raw database '{c.database}'",
            file=sys.stderr,
        )  # noqa: E501
        return 2
    ensure_optional_sources(c.database)
    env = dict(os.environ)
    env.update(
        CH_HOST=c.host,
        CH_PORT=str(c.port),
        CLICKHOUSE_USER=c.user,
        CLICKHOUSE_PASSWORD=c.password,
        CLICKHOUSE_DB=c.database,
        DBT_TARGET_DATABASE=target,
        DBT_SEND_ANONYMOUS_USAGE_STATS="false",
    )
    command = ["dbt", *argv, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    os.execvpe(command[0], command, env)  # noqa: S606 - fixed program, arguments from make
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
