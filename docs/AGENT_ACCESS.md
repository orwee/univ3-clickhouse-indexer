# A read-only user for readers and agents

`agent_reader` is a second ClickHouse user that can read the five dbt marts and nothing
else. The server enforces it; no rule has to be followed for it to hold.

It is not created with SQL. No account on this server can create a user: `indexer` is the
only one, it has no access management, and that stays so. The user is declared in
[`clickhouse/users.d/agent_reader.xml`](../clickhouse/users.d/agent_reader.xml), which both
compose files mount read-only at `/etc/clickhouse-server/users.d/agent_reader.xml`.

| | |
|---|---|
| Can read | `onchain_dbt.dim_pools`, `fct_pool_daily`, `fct_pool_daily_round_trips`, `fct_pool_daily_smart_money`, `fct_round_trip_legs` |
| Cannot read | `stg_swaps`, the `pools` seed, anything in `onchain` |
| Settings | `readonly = 1`, so it cannot write and cannot change a setting |
| Limits | `max_execution_time` 10 s, `max_result_rows` 10,000 with `result_overflow_mode = 'throw'`, `max_memory_usage` 500,000,000 bytes |

The grants are per table and by name. A new mart is invisible to the reader until a line
is added to the file; a mart that is rebuilt under the same name stays readable.

## Read this first: the server will not start without the hash

The file takes the password hash from the server's environment:
`AGENT_READER_PASSWORD_SHA256`, in `clickhouse.env`. Once the file is mounted, a server
started without that variable does not start at all ("Password hash for the
'SHA256_PASSWORD' authentication type has length 0", as the owner saw on a clean
26.3.33.24). From the moment this change is on `main`, **every `make up` needs the variable
in `clickhouse.env`**, including one that has nothing to do with the reader.

## What the owner does, in order

All of it needs Docker, which the agent user does not have.

1. **`make demo`**, as root. The demo server mounts the same file with a demo password and
   step 7 connects as `agent_reader` and tries everything in the table below, the
   destructive statements included. It must end in `DEMO OK`. Nothing real is touched.

2. **Add the hash to `clickhouse.env`, before any `make up`.** This generates a password,
   writes its hash where the server reads it and the password where the reader reads it,
   and prints neither:

   ```sh
   umask 077
   pw=$(openssl rand -hex 24)
   printf 'AGENT_READER_PASSWORD_SHA256=%s\n' \
     "$(printf '%s' "$pw" | sha256sum | cut -d' ' -f1)" >> ~/secrets/clickhouse.env
   printf '%s\n' \
     'AGENT_READER_HOST=127.0.0.1' 'AGENT_READER_PORT=8123' 'AGENT_READER_DB=onchain_dbt' \
     'AGENT_READER_USER=agent_reader' "AGENT_READER_PASSWORD=$pw" > ~/secrets/agent-reader.env
   unset pw
   ```

   Use the real paths if the files live elsewhere (`CLICKHOUSE_ENV_FILE`,
   `AGENT_READER_ENV_FILE` in `.env`). `agent-reader.env` has to be readable by whoever
   runs the tests and by the reader, and by nobody else. `clickhouse.env` only ever holds
   the hash.

3. **`make up`**, as root. Compose recreates the container with the new mount and the new
   variable; the named volume, and so the data, is kept. If it does not come up healthy,
   `make logs`: the message quoted above means step 2 did not reach the file compose reads.

4. **`make test`**, as the user that can read `agent-reader.env`. The server tests in
   `tests/test_agent_reader.py` stop skipping and run as the reader.

To change the password later: repeat step 2 with the old line removed from
`clickhouse.env`, then `make up`.

## What is checked, and where

Every statement and its expected error code is in
[`src/univ3_indexer/agent_reader.py`](../src/univ3_indexer/agent_reader.py). The real server
only ever sees statements that would change nothing if it accepted them. `DROP`, `TRUNCATE`,
`ALTER` and the like are tried against the demo server alone.

| As `agent_reader` | Expected | `make test`, real server | `make demo` |
|---|---|---|---|
| `SELECT` on each of the five marts, `DESCRIBE` on one | works | yes | yes |
| `SELECT` on `stg_swaps`, on the seed, on the raw table | `ACCESS_DENIED` (497) | yes | yes |
| `INSERT … SELECT … WHERE 0` into a mart | `ACCESS_DENIED` (497) | yes | yes |
| `CREATE TABLE` of a `test_*` name | `ACCESS_DENIED` (497) | yes, in a `test_*` database that is dropped either way | yes |
| `SETTINGS max_execution_time = 600` in the statement | `READONLY` (164) | yes | yes |
| A result over the row limit | `TOO_MANY_ROWS_OR_BYTES` (396) | yes | yes |
| `INSERT` of a row, `ALTER … DELETE`, `TRUNCATE`, `DROP TABLE`, `CREATE TEMPORARY TABLE` | `ACCESS_DENIED` (497) | never | yes |
| `url()`, `file()`, `remote()` | `ACCESS_DENIED` (497) | never | yes |
| `max_execution_time` as a URL parameter, `SET readonly = 0` | `READONLY` (164) | no | yes |
| A query that runs past 10 s | `TIMEOUT_EXCEEDED` (159) | no | yes |
| `SHOW TABLES`, `system.columns` | only the granted marts | no | yes |
| A mart after `EXCHANGE TABLES`, and after `DROP` + `CREATE` | still readable | no | yes |
| clickhouse-connect: connects and queries; a per-query setting is refused by the client; an insert is denied | as stated | connects and queries | yes |

Without a server, `make test` also checks the definition itself: the XML parses, the grants
are exactly the five marts and each is `SELECT` on one table, the database they name is the
one `scripts/run_dbt.py` and `demo/demo.env` build into, both compose files mount the same
file at the same path read-only, the file holds no password, and `max_result_rows` is at
least 10,000.

That floor is not arbitrary. clickhouse-connect reads `system.settings` while connecting,
1,550 rows on 26.3.33.24, and the limit throws: at 1,000 the client cannot connect at all.
10,000 also covers the largest mart (`fct_round_trip_legs`, 9,549 rows on 2026-10-10); a
mart that outgrows the limit can still be queried, but not fetched whole.

## Results

**2026-10-10, by the agent, on the real server, without Docker.**

- The checks that need no server: pass (`make test`).
- `system.settings` has 1,550 rows on this server, below the limit: pass.
- The server tests as the reader: **skipped, not run.** `agent-reader.env` does not exist and
  the server has no `agent_reader` user: it is still running without the mount, and
  recreating the container needs Docker.
- `make demo`: **not run.** It needs Docker. Step 7 of `scripts/demo.py` has never been
  executed.

The expected codes in the table above are the ones the owner observed on a clean
26.3.33.24. The agent reproduced two of them on the real server as `indexer`, with the same
settings written into the statement: 396 for a result over 10,000 rows and 159 for a query
past its time limit. Nothing else in the table has been seen by the agent.

**To be filled in by the owner after steps 1 to 4:** the date, the last lines of
`make demo`, and the `make test` summary line.
