"""The one file that tells the agent which warehouse it is looking at.

A YAML with the database, the list of tables and the limits. It holds names and numbers
only: what a table means is not written anywhere, the agent reads column names and types
from the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class WarehouseError(ValueError):
    """The YAML is missing something, or holds something that is not a name or a limit."""


@dataclass(frozen=True)
class Warehouse:
    database: str
    tables: tuple[str, ...]
    row_cap: int  # rows of one result handed to the model; more are cut, and flagged
    max_iterations: int  # model calls per question
    max_usd: Decimal  # dollars per question


def _identifier(value: object, what: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise WarehouseError(f"{what} must be a plain SQL identifier, got {value!r}")
    return value


def _positive_int(limits: dict, name: str) -> int:
    value = limits.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WarehouseError(f"limits.{name} must be a positive integer, got {value!r}")
    return value


def load(path: Path) -> Warehouse:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise WarehouseError(f"{path}: file not found") from None
    if not isinstance(raw, dict):
        raise WarehouseError(f"{path}: expected a mapping at the top level")
    tables = raw.get("tables")
    if not isinstance(tables, list) or not tables:
        raise WarehouseError(f"{path}: 'tables' must be a non-empty list")
    names = tuple(_identifier(t, "a table name") for t in tables)
    if len(set(names)) != len(names):
        raise WarehouseError(f"{path}: a table is listed twice")
    limits = raw.get("limits")
    if not isinstance(limits, dict):
        raise WarehouseError(f"{path}: 'limits' must be a mapping")
    try:
        max_usd = Decimal(str(limits.get("max_usd")))
    except InvalidOperation:
        raise WarehouseError(f"{path}: limits.max_usd must be a number") from None
    if not max_usd.is_finite() or max_usd <= 0:
        raise WarehouseError(f"{path}: limits.max_usd must be positive")
    return Warehouse(
        database=_identifier(raw.get("database"), "the database"),
        tables=names,
        row_cap=_positive_int(limits, "row_cap"),
        max_iterations=_positive_int(limits, "max_iterations"),
        max_usd=max_usd,
    )
