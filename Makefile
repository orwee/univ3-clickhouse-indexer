.DEFAULT_GOAL := help
.PHONY: help up down logs ch-client test lint

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
