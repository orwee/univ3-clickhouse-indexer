"""The read-only user: what its definition says, and whether the server enforces it.

Two groups. The first needs no server: it reads clickhouse/users.d/agent_reader.xml, the two
compose files and demo/demo.env. The second connects to the configured server AS the reader
and tries only statements that would change nothing if the server accepted them; it skips,
saying why, when agent-reader.env is missing or the server does not know the user yet.
Everything destructive is tried in `make demo` only (scripts/demo.py, step 7).
"""

import hashlib
import re
import sys
import xml.etree.ElementTree as ET  # noqa: S405 - parses one file of this repository

import pytest
import yaml
from clickhouse_connect.driver.exceptions import DatabaseError
from dotenv import dotenv_values

from univ3_indexer import agent_reader, config

sys.path.insert(0, str(config.REPO_ROOT / "scripts"))
import run_dbt  # noqa: E402

MARTS = (
    "dim_pools",
    "fct_pool_daily",
    "fct_pool_daily_round_trips",
    "fct_pool_daily_smart_money",
    "fct_round_trip_legs",
)
# clickhouse-connect reads system.settings while connecting (1,550 rows on 26.3.33.24) and
# the largest mart has 9,549 rows. With the limit at 1,000 the client cannot even connect.
RESULT_ROWS_FLOOR = 10_000
DEMO_ENV = config.REPO_ROOT / "demo" / "demo.env"


# --- no server needed ------------------------------------------------------------------


def test_the_users_file_parses_and_defines_one_user_and_one_profile():
    root = ET.parse(agent_reader.USERS_FILE).getroot()  # noqa: S314
    assert root.tag == "clickhouse"
    assert [u.tag for u in root.find("users")] == [agent_reader.USER]
    assert [p.tag for p in root.find("profiles")] == [agent_reader.USER]
    assert root.findtext(f"users/{agent_reader.USER}/profile") == agent_reader.USER


def test_the_grants_are_exactly_the_five_marts():
    d = agent_reader.definition()
    assert d.tables == MARTS
    assert d.grants == tuple(f"GRANT SELECT ON {d.database}.{t}" for t in MARTS)
    for table in d.tables:
        assert (config.REPO_ROOT / "dbt" / "models" / "marts" / f"{table}.sql").exists()


@pytest.mark.parametrize(
    "grant",
    ["GRANT SELECT ON onchain_dbt.*", "GRANT ALL ON onchain_dbt.dim_pools", "GRANT SELECT ON *.*"],
)
def test_a_grant_that_is_not_select_on_one_table_is_rejected(tmp_path, grant):
    text = agent_reader.USERS_FILE.read_text()
    first = f"GRANT SELECT ON onchain_dbt.{MARTS[0]}</query>"
    assert first in text
    path = tmp_path / "agent_reader.xml"
    path.write_text(text.replace(first, f"{grant}</query>"))
    with pytest.raises(ValueError, match="every grant must be"):
        agent_reader.definition(path)


def test_the_database_is_the_one_dbt_writes_to_here_and_in_the_demo():
    demo = dotenv_values(DEMO_ENV)
    database = agent_reader.definition().database
    assert database == run_dbt.DEFAULT_TARGET_DATABASE
    assert database == demo["DBT_TARGET_DATABASE"]
    assert database == demo["AGENT_READER_DB"]
    assert database != demo["CLICKHOUSE_DB"]  # dbt refuses to build into the raw database


def test_the_settings_are_read_only_with_the_three_limits():
    settings = agent_reader.definition().settings
    assert settings["readonly"] == "1"
    assert settings["result_overflow_mode"] == "throw"
    assert set(settings) == {
        "readonly",
        "max_execution_time",
        "max_result_rows",
        "result_overflow_mode",
        "max_memory_usage",
    }
    for name in ("max_execution_time", "max_result_rows", "max_memory_usage"):
        assert int(settings[name]) > 0


def test_the_row_limit_has_a_floor():
    assert int(agent_reader.definition().settings["max_result_rows"]) >= RESULT_ROWS_FLOOR


def test_the_file_holds_no_password():
    text = agent_reader.USERS_FILE.read_text()
    root = ET.fromstring(text)  # noqa: S314
    secrets = [e for e in root.iter() if "password" in e.tag.lower()]
    assert [e.tag for e in secrets] == ["password_sha256_hex"]
    assert secrets[0].attrib == {"from_env": agent_reader.PASSWORD_HASH_VARIABLE}
    assert not (secrets[0].text or "").strip()
    assert not re.search(r"[0-9a-fA-F]{40,}", text)


def _users_mounts(compose_file: str) -> list[tuple[str, str]]:
    """(service, volume) for every volume that lands in the server's users.d directory."""
    services = yaml.safe_load((config.REPO_ROOT / compose_file).read_text())["services"]
    return [
        (name, volume)
        for name, service in services.items()
        for volume in service.get("volumes", [])
        if "/users.d/" in volume
    ]


def test_the_demo_and_the_opt_in_override_mount_the_same_file_at_the_same_path_read_only():
    source = "./" + str(agent_reader.USERS_FILE.relative_to(config.REPO_ROOT))
    expected = f"{source}:{agent_reader.MOUNT_TARGET}:ro"
    assert _users_mounts("docker-compose.demo.yml") == [("clickhouse-demo", expected)]
    assert _users_mounts("docker-compose.reader.yml") == [("clickhouse", expected)]


def test_plain_make_up_does_not_mount_the_reader():
    """On the real server the reader is opt-in: `make up` must work without the hash."""
    assert _users_mounts("docker-compose.yml") == []
    makefile = (config.REPO_ROOT / "Makefile").read_text()
    recipes = dict(re.findall(r"^([a-z-]+):.*\n\t(.+)$", makefile, flags=re.MULTILINE))
    assert "reader" not in recipes["up"]
    assert recipes["up-reader"].split() == [
        *"docker compose -f docker-compose.yml -f docker-compose.reader.yml".split(),
        *"up -d --wait".split(),
    ]


def test_the_demo_hash_is_the_hash_of_the_demo_password():
    demo = dotenv_values(DEMO_ENV)
    digest = hashlib.sha256(demo["AGENT_READER_PASSWORD"].encode()).hexdigest()
    assert demo[agent_reader.PASSWORD_HASH_VARIABLE] == digest
    assert demo["AGENT_READER_USER"] == agent_reader.USER
    assert set(config.AGENT_READER_NAMES.values()) <= set(demo)


def test_the_hash_variable_is_documented_before_make_up_reader():
    assert agent_reader.PASSWORD_HASH_VARIABLE in (config.REPO_ROOT / ".env.example").read_text()
    doc = (config.REPO_ROOT / "docs" / "AGENT_ACCESS.md").read_text()
    # The warning comes before the steps, and in the steps the hash comes before the start.
    steps = doc.index("## What the owner does")
    assert 0 < doc.index(agent_reader.PASSWORD_HASH_VARIABLE) < steps
    assert steps < doc.index("**Add the hash", steps) < doc.index("**`make up-reader`.**", steps)


def test_run_checks_reports_what_did_not_hold(capsys):
    class Accepts:
        def command(self, sql):
            return 1

    checks = [agent_reader.Check("reads", "SELECT 1", 0), agent_reader.Check("writes", "X", 497)]
    assert agent_reader.run_checks(Accepts(), checks) == ["writes"]
    assert "FAILED writes: refused with 497, got 0" in capsys.readouterr().out


# --- against the configured server, as the reader ---------------------------------------


def test_the_row_limit_lets_clickhouse_connect_connect(clickhouse):
    """The client reads system.settings on connect; the limit must be above its row count."""
    rows = int(clickhouse.command("SELECT count() FROM system.settings"))
    assert rows < int(agent_reader.definition().settings["max_result_rows"])


@pytest.fixture(scope="module")
def reader(clickhouse):
    try:
        client = agent_reader.connect()
    except config.ConfigError as exc:
        pytest.skip(f"agent-reader.env is not available: {exc}")
    except DatabaseError as exc:
        if exc.code != agent_reader.AUTHENTICATION_FAILED:
            raise
        pytest.skip(
            f"the server does not accept {agent_reader.USER}: the user does not exist yet "
            "(docs/AGENT_ACCESS.md), or agent-reader.env holds a password other than the "
            "one whose hash the server has"
        )
    assert client.command("SELECT currentUser()") == agent_reader.USER
    return client


def _checks(new_table: str = "test_placeholder.probe") -> list[agent_reader.Check]:
    raw_database = "raw_placeholder"
    if new_table != "test_placeholder.probe":
        raw_database = config.load_clickhouse_config().database
    return agent_reader.harmless_checks(agent_reader.definition(), raw_database, new_table)


@pytest.fixture(scope="module")
def outcomes(clickhouse, reader):
    """Every harmless statement, run once as the reader: what -> (expected, got)."""
    import uuid

    database = f"test_{uuid.uuid4().hex[:12]}"
    new_table = f"{database}.probe"
    clickhouse.command(f"CREATE DATABASE {database}")
    try:
        results = {
            check.what: (check.expected, agent_reader.error_code(reader, check.sql))
            for check in _checks(new_table)
        }
        # If the server ever accepts the CREATE TABLE, remove it as indexer; the test fails.
        clickhouse.command(f"DROP TABLE IF EXISTS {new_table} SYNC")
    finally:
        clickhouse.command(f"DROP DATABASE IF EXISTS {database}")
    return results


@pytest.mark.parametrize("what", [check.what for check in _checks()])
def test_the_server_enforces_it_for_the_reader(outcomes, what):
    expected, got = outcomes[what]
    assert got == expected, f"{what}: expected {expected or 'success'}, the server answered {got}"
