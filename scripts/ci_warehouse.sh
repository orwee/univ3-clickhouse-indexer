#!/usr/bin/env bash
# A throw-away warehouse for a CI job: ClickHouse with the read-only user, and the marts
# fixture loaded where that user is allowed to read it.
#
# Meant for GitHub's runner, where Docker is there for the taking. It is not run on the
# server that holds the real data: that one has its own ClickHouse and `make up`.
#
# What it does:
#   1. starts the pinned ClickHouse image with clickhouse/users.d/agent_reader.xml mounted
#      and the values of demo/demo.env, which are not secrets (see that file);
#   2. waits until the server answers, to its own user and to the read-only one;
#   3. loads evals/fixture/ into onchain_dbt, the database the reader's grants name, and
#      creates, empty, the three things the reader must be refused: the staging view, the
#      seed and the raw table. They have to exist: a refusal is only a refusal if there is
#      something to refuse, otherwise the server just says the table is unknown;
#   4. hands the connection to later steps: the variables go to $GITHUB_ENV, or to standard
#      output as `export` lines when there is no $GITHUB_ENV.
#
# Needs: docker, curl, and `uv sync` already done.
set -euo pipefail

IMAGE="clickhouse/clickhouse-server:26.3.33.24"   # the version docker-compose.yml pins
NAME="${CI_WAREHOUSE_NAME:-ci-warehouse}"
PORT="${CI_WAREHOUSE_PORT:-8123}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/demo/demo.env"
USERS_FILE="$ROOT/clickhouse/users.d/agent_reader.xml"

value() {  # one value of demo/demo.env
  local found
  found="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-)"
  if [ -z "$found" ]; then
    echo "ci_warehouse: $1 is not in demo/demo.env" >&2
    exit 1
  fi
  printf '%s' "$found"
}

export CLICKHOUSE_DB CLICKHOUSE_USER CLICKHOUSE_PASSWORD CH_HOST CH_PORT
export AGENT_READER_HOST AGENT_READER_PORT AGENT_READER_DB AGENT_READER_USER AGENT_READER_PASSWORD
CLICKHOUSE_DB="$(value CLICKHOUSE_DB)"
CLICKHOUSE_USER="$(value CLICKHOUSE_USER)"
CLICKHOUSE_PASSWORD="$(value CLICKHOUSE_PASSWORD)"
CH_HOST="127.0.0.1"   # demo.env names the compose service; here the port is published
CH_PORT="$PORT"
AGENT_READER_HOST="127.0.0.1"
AGENT_READER_PORT="$PORT"
AGENT_READER_DB="$(value AGENT_READER_DB)"
AGENT_READER_USER="$(value AGENT_READER_USER)"
AGENT_READER_PASSWORD="$(value AGENT_READER_PASSWORD)"

echo "ci_warehouse: starting $IMAGE as $NAME on 127.0.0.1:$PORT"
docker run --detach --name "$NAME" \
  --env-file "$ENV_FILE" \
  --publish "127.0.0.1:$PORT:8123" \
  --volume "$USERS_FILE:/etc/clickhouse-server/users.d/agent_reader.xml:ro" \
  --ulimit nofile=262144:262144 \
  "$IMAGE" >/dev/null

answers() {  # user, password: does the server run a query for them?
  curl --silent --fail --max-time 5 --user "$1:$2" \
    --data-binary "SELECT 1" "http://127.0.0.1:$PORT/" >/dev/null 2>&1
}

ready=""
for _ in $(seq 1 60); do
  if [ "$(docker inspect --format '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ]; then
    break   # it stopped: with the users file mounted and no hash, it never starts
  fi
  if answers "$CLICKHOUSE_USER" "$CLICKHOUSE_PASSWORD" \
    && answers "$AGENT_READER_USER" "$AGENT_READER_PASSWORD"; then
    ready="yes"
    break
  fi
  sleep 2
done
if [ -z "$ready" ]; then
  echo "ci_warehouse: the server did not answer both users within two minutes" >&2
  docker logs --tail 60 "$NAME" >&2 || true
  exit 1
fi
echo "ci_warehouse: the server answers $CLICKHOUSE_USER and $AGENT_READER_USER"

cd "$ROOT"
PYTHONPATH=src uv run python - <<'PY'
from evalkit import fixture
from univ3_indexer import agent_reader, config
from univ3_indexer import clickhouse as ch

raw = config.load_clickhouse_config().database
marts = agent_reader.definition().database
admin = ch.connect(database="default")
for database in (raw, marts):
    admin.command(f"CREATE DATABASE IF NOT EXISTS {ch.qualified(database).split('.')[0]}")
loaded = fixture.load(admin, marts)
# What the reader must be refused, empty. See the header of this script.
ch.apply_ddl(admin, raw)
admin.command(
    f"CREATE VIEW {ch.qualified(marts, 'stg_swaps')} AS SELECT * FROM {ch.qualified(raw)}"
)
admin.command(
    f"CREATE TABLE {ch.qualified(marts, 'pools')} (pool_address String) "
    "ENGINE = MergeTree ORDER BY pool_address"
)
reader = agent_reader.connect()
seen = sorted(row[0] for row in reader.query(f"SHOW TABLES FROM {marts}").result_rows)
print(f"ci_warehouse: loaded into {marts}: {loaded}")
print(f"ci_warehouse: {reader.command('SELECT currentUser()')} sees {seen}")
if seen != sorted(fixture.TABLES):
    raise SystemExit("ci_warehouse: the reader does not see exactly the five marts")
PY

{
  echo "CLICKHOUSE_DB=$CLICKHOUSE_DB"
  echo "CLICKHOUSE_USER=$CLICKHOUSE_USER"
  echo "CLICKHOUSE_PASSWORD=$CLICKHOUSE_PASSWORD"
  echo "CH_HOST=$CH_HOST"
  echo "CH_PORT=$CH_PORT"
  echo "AGENT_READER_HOST=$AGENT_READER_HOST"
  echo "AGENT_READER_PORT=$AGENT_READER_PORT"
  echo "AGENT_READER_DB=$AGENT_READER_DB"
  echo "AGENT_READER_USER=$AGENT_READER_USER"
  echo "AGENT_READER_PASSWORD=$AGENT_READER_PASSWORD"
} | if [ -n "${GITHUB_ENV:-}" ]; then cat >> "$GITHUB_ENV"; else sed 's/^/export /'; fi
echo "ci_warehouse: ready"
