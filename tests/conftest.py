"""Shared fixtures. Tests that need ClickHouse skip, loudly, when it is not reachable."""

import uuid

import pytest


@pytest.fixture(scope="session")
def clickhouse():
    from univ3_indexer import clickhouse as ch
    from univ3_indexer.config import ConfigError

    try:
        client = ch.connect(database="default")
        client.command("SELECT 1")
    except ConfigError as exc:
        pytest.skip(f"ClickHouse credentials not available: {exc}")
    except Exception as exc:  # noqa: BLE001 - any connection problem means "not available"
        pytest.skip(f"ClickHouse is not reachable: {type(exc).__name__}")
    return client


@pytest.fixture
def temp_database(clickhouse):
    """A throw-away `test_*` database, dropped even when the test fails."""
    name = f"test_{uuid.uuid4().hex[:12]}"
    clickhouse.command(f"CREATE DATABASE {name}")
    try:
        yield name
    finally:
        clickhouse.command(f"DROP DATABASE IF EXISTS {name}")
