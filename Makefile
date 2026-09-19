.DEFAULT_GOAL := help
.PHONY: help up down logs ch-client test lint load load-full load-verify sanity mv-setup mv-check dbt-seed dbt-build dbt-test

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

up: ## start ClickHouse and wait until it is healthy
	docker compose up -d --wait

down: ## stop ClickHouse (the named volume, and so the data, is kept)
	docker compose down

logs: ## follow the server log
	docker compose logs -f --tail=100 clickhouse

# clickhouse-client picks CLICKHOUSE_USER / CLICKHOUSE_PASSWORD up from the
# container environment (env_file), so the password never appears in an argv,
# neither on the host nor inside the container.
ch-client: ## open clickhouse-client inside the container as the indexer user
	docker compose exec clickhouse sh -c 'exec clickhouse-client --database "$$CLICKHOUSE_DB"'

test: ## run the test suite
	uv run pytest

lint: ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

# Where the backfill landed its JSONL files. Override: make load LANDING=/some/dir
LANDING ?= /var/lib/univ3-indexer/landing

load: ## load what is missing from the landing zone into ClickHouse, then verify
	PYTHONPATH=src uv run python -m univ3_indexer.loader --mode incremental --landing $(LANDING)

load-full: ## truncate the raw table, reload everything, then verify
	PYTHONPATH=src uv run python -m univ3_indexer.loader --mode full --landing $(LANDING)

load-verify: ## only compare ClickHouse with the landing zone (non-zero exit on mismatch)
	PYTHONPATH=src uv run python -m univ3_indexer.loader --verify-only --landing $(LANDING)

sanity: ## run sql/sanity/*.sql and write reports/sanity.md (non-zero exit on a defect)
	PYTHONPATH=src uv run python -m univ3_indexer.sanity

# dbt reads `onchain` and writes ONLY into its own database (onchain_dbt by default).
DBT = PYTHONPATH=src uv run --group dbt python scripts/run_dbt.py

dbt-seed: ## regenerate dbt/seeds/pools.csv from pools.yml
	PYTHONPATH=src uv run python scripts/generate_pools_seed.py

dbt-build: dbt-seed ## seed, run and test every dbt model against the real data
	$(DBT) build

dbt-test: ## run only the dbt tests
	$(DBT) test

mv-setup: ## create the daily materialized view in the raw database and backfill it, once
	PYTHONPATH=src uv run python -m univ3_indexer.mv --setup

mv-check: ## swaps_daily (through the view) against a direct GROUP BY; non-zero exit on mismatch
	PYTHONPATH=src uv run python -m univ3_indexer.mv --check
