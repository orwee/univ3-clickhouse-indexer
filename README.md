# univ3-clickhouse-indexer

A weekend project for learning ClickHouse hands-on: index Uniswap v3 `Swap`
events straight from an Ethereum JSON-RPC endpoint into a local ClickHouse
server, model them with dbt, and reconcile the result against an independent
source (the Uniswap subgraph) to show the numbers can be trusted. The reasoning
behind each choice, including the ones that turned out wrong, is in
[DECISIONS.md](DECISIONS.md).

**Status:** environment scaffold only. No pipeline code yet.

## How to run

Requirements: Docker with the compose plugin, [uv](https://docs.astral.sh/uv/),
`make`. uv downloads Python 3.12 by itself.

1. Create the secrets files **outside** the repo. `.env.example` lists the
   variable names each one needs.

   ```
   mkdir -m 700 ~/secrets
   touch ~/secrets/clickhouse.env ~/secrets/api-keys.env
   chmod 600 ~/secrets/*.env
   ```

   If they live somewhere else, copy `.env.example` to `.env` and set the two
   path pointers. `.env` holds paths only, never secret values.

2. Start ClickHouse and wait for it to be healthy:

   ```
   make up
   ```

   HTTP is on `127.0.0.1:8123`, the native protocol on `127.0.0.1:9000`.
   Neither is reachable from other machines.

3. Check it:

   ```
   make ch-client     # SQL shell as the indexer user
   make test          # pytest
   make lint          # ruff
   ```

`make down` stops the server and keeps the data: it lives in a named Docker
volume. `make logs` follows the server log.

## Backfill to a raw landing zone

The backfill does not write to ClickHouse. It lands every Swap log as JSONL on
disk, so ClickHouse can be loaded and reloaded as often as the schema changes
without spending another provider call. Each line holds the decoded swap
(integers as strings, because amounts are int256) and the raw log it came from.

It needs `ALCHEMY_API_KEY`, so it runs as a user who can read `api-keys.env`.
Data goes **outside the repo**: `/var/lib/univ3-indexer` when run as root,
`~/.local/share/univ3-indexer` otherwise, or wherever `UNIV3_DATA_DIR` points.

| | 30 days, 4 pools (measured 2026-09-19) |
|---|---|
| Calls | 21,600 (10 blocks each, all pools in one call) |
| Time | ~72 min at the default 5 calls per second |
| Rows | ~881,000 |
| Disk | ~1.3 GB of JSONL (~1,480 bytes per line; gzip shrinks it ~7.7x) |
| Files | ~216, one per 1,000 blocks: `swaps_<from>_<to>.jsonl` |

**See the plan without fetching or writing anything:**

```
PYTHONPATH=src uv run python -m univ3_indexer.cli --days 30 --dry-run
```

**Launch** (detached, so it survives the terminal):

```
tmux new-session -d -s backfill \
  'PYTHONPATH=src .venv/bin/python -m univ3_indexer.cli --days 30 --rps 5 \
     --log-file /var/lib/univ3-indexer/backfill.log'
```

**Watch the progress.** A plain line every 5 batches, no progress bar:

```
tail -f /var/lib/univ3-indexer/backfill.log
# 2026-09-19 12:00:00 INFO block 25801000 |  12.5% | rows this run 110000 | 4.98 calls/s (0 retries) | 50 blocks/s | ETA 1h03m00s
cat /var/lib/univ3-indexer/checkpoint.json     # last block safely on disk
```

**Stop it cleanly:** `tmux send-keys -t backfill C-c` (or `kill -TERM <pid>`).
It exits with code 130. At most the batch in flight is lost: 100 calls.

**Resume:** run exactly the same command again. The block window and the pool
set were saved in `plan.json` on the first run, so `--days 30` does not slide
forward; the run continues from `checkpoint.json`. Re-running a range rewrites
the same file, so resuming never duplicates rows. To backfill a different
window or pool set, use another `--checkpoint` and `--out`.

Exit codes: `0` finished, `2` bad arguments, `3` the provider rejected a
request permanently (for instance `-32600`, range too wide: not retried), `4`
network trouble outlasted the retries, `5` more than 20% of requests needed a
retry (aborted to protect the quota: lower `--rps` and resume), `130`
interrupted. In every case the checkpoint only points at files that are
completely on disk.

**Check what landed:**

```
PYTHONPATH=src uv run python -c "
from univ3_indexer import config, landing
d = config.data_dir() / 'landing'
print(landing.check_coverage(d), sum(1 for _ in landing.read_landing(d)))"
```

`check_coverage` fails on any gap or overlap between files;
`read_landing(d, redecode=True)` decodes again from the raw logs, which is how
a fixed decoder is applied to data already on disk.

## Load, sanity and dbt

```
make load            # landing zone -> onchain.raw_swaps (incremental, idempotent), then verify
make load-full       # truncate and reload everything, then verify
make sanity          # sql/sanity/*.sql -> reports/sanity.md; non-zero exit on a defect
make dbt-build       # seed + models + tests, into the onchain_dbt database
make dbt-test        # only the dbt tests
```

dbt reads `onchain` and writes only into `onchain_dbt`; the launcher refuses to run
otherwise. `dbt/profiles.yml` holds no real value: `scripts/run_dbt.py` loads the
credentials from the secrets file into the environment, without printing them.
`dbt/seeds/pools.csv` is generated from `pools.yml` (`make dbt-seed`), and a test fails
if they diverge.
