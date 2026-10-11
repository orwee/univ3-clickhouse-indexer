"""A dollar budget for model calls, with a ledger that outlives the process.

The same three steps as the credit budget of the Nansen client in this repository:

1. ``check(worst_case)`` before a call is sent. If the most the call could cost does not
   fit in what is left, it raises and the call is never made.
2. ``record(...)`` after the call, with what it really cost.
3. ``fail(...)`` when the call did not return a usage: it is booked at its worst case,
   because a request that timed out may still have been served and billed.

With a ledger file every booking is appended as one JSON line, and a new instance on the
same file starts from what earlier ones spent in the same scope. Amounts are ``Decimal``
and are written as strings, so a ledger adds up to the cent however many lines it has.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path

from univ3_indexer import config

LEDGER_NAME = "ledger.jsonl"


class BudgetExceeded(RuntimeError):
    """The worst case of the next call does not fit in what is left of the budget."""


def default_ledger() -> Path:
    """``<data dir>/agent/ledger.jsonl``. The data directory is never inside the repository."""
    return config.data_dir() / "agent" / LEDGER_NAME


def _usd(value: Decimal | str | int) -> Decimal:
    if isinstance(value, float):
        raise TypeError("dollar amounts are Decimal or text, never float")
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"not a dollar amount: {value!r}")
    return amount


class DollarBudget:
    """Refuses a call whose worst-case cost does not fit in what is left.

    ``scope`` names what the ceiling applies to (one question, one evaluation run). Lines of
    the ledger with another scope do not count; with no scope every line counts.
    """

    def __init__(
        self, max_usd: Decimal | str | int, ledger: Path | None = None, scope: str | None = None
    ):
        self.max_usd = _usd(max_usd)
        self.spent = Decimal(0)
        self.scope = scope
        self._ledger = ledger
        if ledger is not None and ledger.exists():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                if scope is None or entry["scope"] == scope:
                    self.spent += Decimal(entry["usd"])

    @property
    def remaining(self) -> Decimal:
        return self.max_usd - self.spent

    def check(self, worst_case: Decimal | str | int) -> None:
        cost = _usd(worst_case)
        if self.spent + cost > self.max_usd:
            raise BudgetExceeded(
                f"a call that can cost up to ${cost} does not fit: ${self.spent} of "
                f"${self.max_usd} already spent"
            )

    def record(self, used: Decimal | str | int, note: str = "", **details: object) -> None:
        """Book what a call really cost."""
        self._book(_usd(used), "ok", note, details)

    def fail(self, worst_case: Decimal | str | int, note: str = "", **details: object) -> None:
        """Book a call that failed, at the most it could have cost."""
        self._book(_usd(worst_case), "failed", note, details)

    def _book(self, usd: Decimal, outcome: str, note: str, details: dict) -> None:
        self.spent += usd
        if self._ledger is None:
            return
        self._ledger.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "scope": self.scope,
            "usd": str(usd),
            "outcome": outcome,
            "note": note,
            **({"details": details} if details else {}),
        }
        with self._ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
