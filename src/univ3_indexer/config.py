"""Configuration loading.

Secrets live in two files OUTSIDE the repo (see .env.example and DECISIONS.md):

* ``clickhouse.env``  database credentials. Required by anything that touches
  ClickHouse, including the tests.
* ``api-keys.env``    Alchemy / Nansen keys. Optional: it is only read when a
  caller asks for a key, so a process that has no business with the APIs (and
  no permission to read the file) can still import this module and run.

Where each file lives is resolved in this order:

1. the pointer variable in the process environment
   (``CLICKHOUSE_ENV_FILE`` / ``API_KEYS_ENV_FILE``),
2. the same pointer in the git-ignored ``.env`` at the repo root,
3. ``~/secrets/<file name>``.

A variable already present in the process environment wins over the file, so
CI can inject values without any file at all.

Every failure raises ``ConfigError`` naming the variable and the file that was
consulted. Values are never included in an error message or in a ``repr``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "REPLACE_ME"

REPORTS_DIR = REPO_ROOT / "reports"
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"


def newest_snapshot(name: str) -> Path:
    """The newest committed copy of a report, under ``docs/evidence/<date>/``.

    ``reports/`` is git-ignored, so anything that has to resolve for a reader on GitHub — a
    link, a caption — must name the snapshot and not the working copy.
    """
    snapshots = sorted(d for d in EVIDENCE_DIR.glob("*/") if (d / name).exists())
    if not snapshots:
        raise FileNotFoundError(f"no committed snapshot of {name} under {EVIDENCE_DIR}")
    return snapshots[-1] / name


def report_or_snapshot(name: str) -> Path:
    """Where to read a report from: ``reports/<name>`` when a run of the pipeline has left
    one there, otherwise the newest committed snapshot in ``docs/evidence/<date>/``.

    ``reports/`` is git-ignored, so a fresh clone has none of it. Without this, the page
    could not be rebuilt and its tests could not run without first running the whole
    pipeline. The snapshots are committed, dated, and are the files the published page was
    built from, so a clean clone rebuilds exactly what is published.
    """
    live = REPORTS_DIR / name
    if live.exists():
        return live
    try:
        return newest_snapshot(name)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"no {name}: neither {live} nor a snapshot of it under {EVIDENCE_DIR}"
        ) from None

CLICKHOUSE_POINTER = "CLICKHOUSE_ENV_FILE"
CLICKHOUSE_DEFAULT = "~/secrets/clickhouse.env"
API_KEYS_POINTER = "API_KEYS_ENV_FILE"
API_KEYS_DEFAULT = "~/secrets/api-keys.env"

API_KEY_NAMES = ("ALCHEMY_API_KEY", "NANSEN_API_KEY")


class ConfigError(RuntimeError):
    """A required setting is missing, empty, a placeholder or malformed."""


@dataclass(frozen=True)
class ClickHouseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)


def _read_env_file(path: Path) -> tuple[dict[str, str], str | None]:
    """Return (values, problem). ``problem`` explains why the file gave nothing."""
    try:
        with path.open(encoding="utf-8") as fh:
            values = dotenv_values(stream=fh)
    except FileNotFoundError:
        return {}, "file not found"
    except PermissionError:
        return {}, "permission denied"
    return {k: v for k, v in values.items() if v is not None}, None


def _resolve_path(pointer: str, default: str) -> Path:
    raw = os.environ.get(pointer)
    if not raw:
        repo_env, _ = _read_env_file(REPO_ROOT / ".env")
        raw = repo_env.get(pointer)
    return Path(raw or default).expanduser()


def _require(name: str, file_values: dict[str, str], path: Path, problem: str | None) -> str:
    value = (os.environ.get(name) or file_values.get(name) or "").strip()
    source = f"{path} ({problem})" if problem else str(path)
    if not value:
        raise ConfigError(f"{name} is not set: not in the environment and not in {source}")
    if value == PLACEHOLDER:
        raise ConfigError(f"{name} is still the {PLACEHOLDER} placeholder in {source}")
    return value


def load_clickhouse_config() -> ClickHouseConfig:
    path = _resolve_path(CLICKHOUSE_POINTER, CLICKHOUSE_DEFAULT)
    values, problem = _read_env_file(path)

    def req(name: str) -> str:
        return _require(name, values, path, problem)

    port = req("CH_PORT")
    if not port.isdigit():
        raise ConfigError(f"CH_PORT must be an integer (set in {path})")
    return ClickHouseConfig(
        host=req("CH_HOST"),
        port=int(port),
        database=req("CLICKHOUSE_DB"),
        user=req("CLICKHOUSE_USER"),
        password=req("CLICKHOUSE_PASSWORD"),
    )


def require_api_key(name: str) -> str:
    """Return one API key, reading api-keys.env only now, when it is needed."""
    if name not in API_KEY_NAMES:
        raise ValueError(f"unknown API key name: {name}")
    path = _resolve_path(API_KEYS_POINTER, API_KEYS_DEFAULT)
    values, problem = _read_env_file(path)
    return _require(name, values, path, problem)


DATA_DIR_POINTER = "UNIV3_DATA_DIR"
ROOT_DATA_DIR = "/var/lib/univ3-indexer"


def data_dir() -> Path:
    """Directory for checkpoints and landed data. Always OUTSIDE the working copy.

    The backfill runs as a different user (root) than the one who owns the repo,
    so anything it wrote inside the working copy would leave files there that
    the repo owner cannot modify or clean up.

    Resolution order: ``UNIV3_DATA_DIR`` in the environment, the same pointer in
    the repo ``.env``, then ``/var/lib/univ3-indexer`` when running as root (the
    conventional place for a system service's state), otherwise
    ``$XDG_DATA_HOME/univ3-indexer`` (``~/.local/share/univ3-indexer``).
    """
    raw = os.environ.get(DATA_DIR_POINTER)
    if not raw:
        repo_env, _ = _read_env_file(REPO_ROOT / ".env")
        raw = repo_env.get(DATA_DIR_POINTER)
    if not raw and os.geteuid() == 0:
        raw = ROOT_DATA_DIR
    if not raw:
        xdg = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
        raw = str(Path(xdg) / "univ3-indexer")
    path = Path(raw).expanduser().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise ConfigError(
            f"{DATA_DIR_POINTER} resolves to {path}, inside the working copy {REPO_ROOT}: "
            "choose a directory outside the repo"
        )
    return path
