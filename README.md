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
