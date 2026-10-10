# A read-only user for readers and agents

`agent_reader` is a second ClickHouse user that can read the five dbt marts and nothing
else. The server enforces it; no rule has to be followed for it to hold.

It is not created with SQL. No account on this server can create a user: `indexer` is the
only one, it has no access management, and that stays so. The user is declared in
[`clickhouse/users.d/agent_reader.xml`](../clickhouse/users.d/agent_reader.xml), mounted
read-only at `/etc/clickhouse-server/users.d/agent_reader.xml`:

- by the demo, always (`docker-compose.demo.yml`): `make demo` exercises the reader every
  time;
- by the real server **only when asked**: `make up-reader`, which adds the override
  `docker-compose.reader.yml`. Plain `make up` does not mount the file and behaves exactly
  as before.

**On the real server the reader is defined, not in force.** On 2026-10-10 the real server
runs without the mount and has no `agent_reader`; the owner has decided not to recreate the
container for now.

| | |
|---|---|
| Can read | `onchain_dbt.dim_pools`, `fct_pool_daily`, `fct_pool_daily_round_trips`, `fct_pool_daily_smart_money`, `fct_round_trip_legs` |
| Cannot read | `stg_swaps`, the `pools` seed, anything in `onchain` |
| Settings | `readonly = 1`, so it cannot write and cannot change a setting |
| Limits | `max_execution_time` 10 s, `max_result_rows` 10,000 with `result_overflow_mode = 'throw'`, `max_memory_usage` 500,000,000 bytes |

The grants are per table and by name. A new mart is invisible to the reader until a line
is added to the file; a mart that is rebuilt under the same name stays readable.

## Read this first: with the mount, the server will not start without the hash

The file takes the password hash from the server's environment:
`AGENT_READER_PASSWORD_SHA256`, in `clickhouse.env`. A server started with the file mounted
and that variable unset does not start at all ("Password hash for the 'SHA256_PASSWORD'
authentication type has length 0", seen on a clean 26.3.33.24 in the review session
described under Results). So the variable goes into `clickhouse.env` **before**
`make up-reader`. It is needed for `make up-reader` only: `make up` neither mounts the file
nor needs the variable.

## What the owner does to turn the reader on, in order

All of it needs Docker, and so root.

1. **`make demo`.** The demo server mounts the same file with a demo password and step 7
   connects as `agent_reader` and tries everything in the table below, the destructive
   statements included. It must end in `DEMO OK`. Nothing real is touched.

2. **Add the hash to `clickhouse.env`, before `make up-reader`.** Run as root. As root
   `~` is `/root`, which is not where these files live, so the paths are written out
   instead of using `~`. `CH_ENV` must be the file compose actually reads:
   `CLICKHOUSE_ENV_FILE` in the repo's `.env` if it is set there, otherwise
   `$HOME/secrets/clickhouse.env` of whoever runs `make up-reader`. A hash appended to any
   other file never reaches the server, and the server then does not start.

   This generates a password, writes its hash where the server reads it and the password
   where the reader reads it, and prints neither:

   ```sh
   CH_ENV=/path/to/clickhouse.env          # the file compose reads, see above
   READER_ENV=/path/to/agent-reader.env    # where the tests will look for it, see below
   TEST_USER=the-user-that-runs-make-test

   umask 077
   pw=$(openssl rand -hex 24)
   # Appending to a file whose last line has no newline would glue the variable onto it.
   [ -z "$(tail -c 1 "$CH_ENV")" ] || echo >> "$CH_ENV"
   printf 'AGENT_READER_PASSWORD_SHA256=%s\n' \
     "$(printf '%s' "$pw" | sha256sum | cut -d' ' -f1)" >> "$CH_ENV"
   printf '%s\n' \
     'AGENT_READER_HOST=127.0.0.1' 'AGENT_READER_PORT=8123' 'AGENT_READER_DB=onchain_dbt' \
     'AGENT_READER_USER=agent_reader' "AGENT_READER_PASSWORD=$pw" > "$READER_ENV"
   chown "$TEST_USER": "$READER_ENV"
   chmod 600 "$READER_ENV"
   unset pw
   ```

   `READER_ENV` is found by `config.py` through `AGENT_READER_ENV_FILE` (environment, then
   the repo's `.env`), and otherwise at `~/secrets/agent-reader.env` of the user running
   the tests, which is that user's home, not root's. Written by root, the file belongs to
   root and nobody else can read it: hence the `chown` to the user that runs `make test`.
   `clickhouse.env` only ever holds the hash.

3. **`make up-reader`.** Compose recreates the container with the mount and the new
   variable; the named volume, and so the data, is kept. If it does not come up healthy,
   `make logs`: the message quoted above means step 2 did not reach the file compose reads.

4. **`make test`**, as the user that can read `agent-reader.env`. The server tests in
   `tests/test_agent_reader.py` stop skipping and run as the reader.

Once the reader is on, keep starting the server with `make up-reader`: a plain `make up`
recreates the container without the mount, and the reader is gone until the next
`make up-reader`. `make down` is the same for both.

To change the password later: repeat step 2 with the old line removed from
`clickhouse.env`, then `make up-reader`.

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
one `scripts/run_dbt.py` and `demo/demo.env` build into, the demo and the opt-in override
mount the same file at the same path read-only, `docker-compose.yml` and `make up` do not
mount it, the file holds no password, and `max_result_rows` is at least 10,000.

That floor is not arbitrary. clickhouse-connect reads `system.settings` while connecting,
1,550 rows on 26.3.33.24, and the limit throws: at 1,000 the client cannot connect at all.
10,000 also covers the largest mart (`fct_round_trip_legs`, 9,549 rows on 2026-10-10); a
mart that outgrows the limit can still be queried, but not fetched whole.

## Results

Three parties, kept apart: what the session that wrote this saw, what a separate review
session saw, and what nobody has run yet.

**2026-10-10, the session that wrote the code.** It ran as root, with Docker available, and
did not use Docker: no container was started, recreated or touched, and `make demo` was not
run. Against the real server:

- The checks that need no server: pass (`make test`).
- `system.settings` has 1,550 rows on this server, below the limit: pass.
- As `indexer`, with the same limits written into the statement: 396 for a result over
  10,000 rows, 159 for a query past its time limit.
- The server tests as the reader: **skipped, not run.** `agent-reader.env` does not exist
  and the real server has no `agent_reader`.

**A separate review session, on a clean 26.3.33.24, without Docker.** Not this session's
result, recorded here as reported:

- The expected results and error codes in the table above were observed there, with the
  package's default `config.xml` and the user layout the image's entrypoint writes. So was
  the failure to start without the hash, and the failure of clickhouse-connect 1.8.0 to
  connect with `max_result_rows` at 1,000.
- `scripts/demo.py` from commit `418987c` was run there and ended in `DEMO OK`, with all 32
  lines of step 7 `ok`.

**Not run by anyone yet.**

- `make demo` under Docker: the compose mount, the image's entrypoint and the runner
  container together.
- `make up-reader` on the real server, and with it the server tests as the reader.

**To be filled in by the owner after steps 1 to 4:** the date, the last lines of
`make demo`, and the `make test` summary line.
