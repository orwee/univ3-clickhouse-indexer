"""The config module must fail loudly, name the variable, and never leak a value."""

import os

import pytest

from univ3_indexer import config

CH_VARS = ("CLICKHOUSE_DB", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD", "CH_HOST", "CH_PORT")
FAKE_PASSWORD = "not-a-real-password-0123456789"
FAKE_KEY = "not-a-real-api-key-abcdef"

GOOD_CH = {
    "CLICKHOUSE_DB": "onchain",
    "CLICKHOUSE_USER": "indexer",
    "CLICKHOUSE_PASSWORD": FAKE_PASSWORD,
    "CH_HOST": "127.0.0.1",
    "CH_PORT": "8123",
}


def write_env(path, values):
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return path


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """No test may see the real secrets files or inherited variables."""
    for name in (*CH_VARS, *config.API_KEY_NAMES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(tmp_path / "absent-clickhouse.env"))
    monkeypatch.setenv(config.API_KEYS_POINTER, str(tmp_path / "absent-api-keys.env"))


def test_loads_clickhouse_config(monkeypatch, tmp_path):
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(write_env(tmp_path / "ch.env", GOOD_CH)))
    cfg = config.load_clickhouse_config()
    assert (cfg.host, cfg.port, cfg.database, cfg.user) == ("127.0.0.1", 8123, "onchain", "indexer")
    assert cfg.password == FAKE_PASSWORD


def test_repr_never_shows_the_password(monkeypatch, tmp_path):
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(write_env(tmp_path / "ch.env", GOOD_CH)))
    assert FAKE_PASSWORD not in repr(config.load_clickhouse_config())


@pytest.mark.parametrize("missing", CH_VARS)
def test_missing_variable_is_named(monkeypatch, tmp_path, missing):
    values = {k: v for k, v in GOOD_CH.items() if k != missing}
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(write_env(tmp_path / "ch.env", values)))
    with pytest.raises(config.ConfigError) as err:
        config.load_clickhouse_config()
    assert missing in str(err.value)
    assert FAKE_PASSWORD not in str(err.value)


def test_missing_file_is_reported_with_its_path(tmp_path):
    with pytest.raises(config.ConfigError) as err:
        config.load_clickhouse_config()
    assert "absent-clickhouse.env" in str(err.value)
    assert "file not found" in str(err.value)


def test_placeholder_is_rejected(monkeypatch, tmp_path):
    values = {**GOOD_CH, "CLICKHOUSE_PASSWORD": config.PLACEHOLDER}
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(write_env(tmp_path / "ch.env", values)))
    with pytest.raises(config.ConfigError, match="CLICKHOUSE_PASSWORD"):
        config.load_clickhouse_config()


def test_bad_port_error_does_not_echo_the_value(monkeypatch, tmp_path):
    values = {**GOOD_CH, "CH_PORT": "eight-thousand"}
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(write_env(tmp_path / "ch.env", values)))
    with pytest.raises(config.ConfigError) as err:
        config.load_clickhouse_config()
    assert "CH_PORT" in str(err.value)
    assert "eight-thousand" not in str(err.value)


def test_environment_wins_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(write_env(tmp_path / "ch.env", GOOD_CH)))
    monkeypatch.setenv("CLICKHOUSE_DB", "from_environment")
    assert config.load_clickhouse_config().database == "from_environment"


def test_clickhouse_config_does_not_need_the_api_keys_file(monkeypatch, tmp_path):
    """The split: database access must work with api-keys.env absent or unreadable."""
    monkeypatch.setenv(config.CLICKHOUSE_POINTER, str(write_env(tmp_path / "ch.env", GOOD_CH)))
    assert config.load_clickhouse_config().user == "indexer"


def test_api_key_is_only_required_when_asked_for(tmp_path):
    with pytest.raises(config.ConfigError) as err:
        config.require_api_key("ALCHEMY_API_KEY")
    assert "ALCHEMY_API_KEY" in str(err.value)
    assert "absent-api-keys.env" in str(err.value)


def test_api_key_is_read_from_its_own_file(monkeypatch, tmp_path):
    path = write_env(tmp_path / "keys.env", {"ALCHEMY_API_KEY": FAKE_KEY})
    monkeypatch.setenv(config.API_KEYS_POINTER, str(path))
    assert config.require_api_key("ALCHEMY_API_KEY") == FAKE_KEY
    with pytest.raises(config.ConfigError, match="NANSEN_API_KEY"):
        config.require_api_key("NANSEN_API_KEY")


def test_unreadable_api_keys_file_says_permission_denied(monkeypatch, tmp_path):
    path = write_env(tmp_path / "keys.env", {"ALCHEMY_API_KEY": FAKE_KEY})
    path.chmod(0o000)
    monkeypatch.setenv(config.API_KEYS_POINTER, str(path))
    if os.access(path, os.R_OK):
        pytest.skip("running as a user that ignores file permissions (root)")
    with pytest.raises(config.ConfigError, match="permission denied"):
        config.require_api_key("ALCHEMY_API_KEY")


def test_unknown_api_key_name_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown API key name"):
        config.require_api_key("SOMETHING_ELSE")


def test_data_dir_defaults_to_xdg_data_home_outside_the_repo(monkeypatch, tmp_path):
    monkeypatch.delenv(config.DATA_DIR_POINTER, raising=False)
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path / "repo-without-dotenv")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.data_dir() == (tmp_path / "xdg" / "univ3-indexer").resolve()


def test_data_dir_can_be_pointed_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(tmp_path / "elsewhere"))
    assert config.data_dir() == (tmp_path / "elsewhere").resolve()


@pytest.mark.parametrize("inside", ["", "data", "src/../cache/x"])
def test_data_dir_inside_the_working_copy_is_refused(monkeypatch, inside):
    monkeypatch.setenv(config.DATA_DIR_POINTER, str(config.REPO_ROOT / inside))
    with pytest.raises(config.ConfigError, match="inside the working copy"):
        config.data_dir()
