.DEFAULT_GOAL := help
DEMO = docker compose -f docker-compose.demo.yml

.PHONY: help demo up down logs ch-client test lint load load-full load-verify sanity reconcile fetch-external fetch-external-hourly mv-setup mv-check dbt-seed dbt-build dbt-test

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

demo: ## the whole pipeline on the committed fixtures: only Docker needed, no API key
	$(DEMO) up --build --abort-on-container-exit --exit-code-from demo-runner; \
	  status=$$?; $(DEMO) down --volumes --remove-orphans; exit $$status

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

# Where the backfill landed its JSONL files. Empty = the loader's own default, which is the
# same <data dir>/landing the backfill writes to (config.data_dir(): UNIV3_DATA_DIR, else
# /var/lib/univ3-indexer as root, else ~/.local/share/univ3-indexer).
# Override: make load LANDING=/some/dir
LANDING ?=
LANDING_ARG = $(if $(LANDING),--landing $(LANDING),)

load: ## load what is missing from the landing zone into ClickHouse, then verify
	PYTHONPATH=src uv run python -m univ3_indexer.loader --mode incremental $(LANDING_ARG)

load-full: ## truncate the raw table, reload everything, then verify
	PYTHONPATH=src uv run python -m univ3_indexer.loader --mode full $(LANDING_ARG)

load-verify: ## only compare ClickHouse with the landing zone (non-zero exit on mismatch)
	PYTHONPATH=src uv run python -m univ3_indexer.loader --verify-only $(LANDING_ARG)

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

fetch-external: ## daily volume per pool from the public GeckoTerminal API (no key) into ClickHouse
	PYTHONPATH=src uv run python -m univ3_indexer.external --fetch

fetch-external-hourly: ## the last 1,000 hourly candles per pool: to see in which hours a day differs
	PYTHONPATH=src uv run python -m univ3_indexer.external --fetch-hourly

# B flags a pool-day beyond BOTH: the relative difference and the absolute one, in USD.
# Beyond the relative one only, it is listed apart. Only complete days are compared (ours
# complete, external candle closed when downloaded); the rest are listed with the reason.
# RECONCILE_DAYS=all compares them too.
RECONCILE_THRESHOLD ?= 0.01
RECONCILE_ABS_THRESHOLD ?= 1000
RECONCILE_DAYS ?= complete

reconcile: ## A internal (must be exactly zero) + B external -> reports/reconciliation.{csv,md} + evidence
	PYTHONPATH=src uv run python -m univ3_indexer.reconcile --threshold $(RECONCILE_THRESHOLD) \
		--abs-threshold $(RECONCILE_ABS_THRESHOLD) \
		$(if $(filter all,$(RECONCILE_DAYS)),--include-incomplete-days,) --evidence
