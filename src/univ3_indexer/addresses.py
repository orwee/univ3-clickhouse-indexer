"""The ONE place where an Ethereum address changes format.

Two formats live in this project, and both are correct where they are:

* ``pools.yml`` keeps the EIP-55 mixed-case form, because that is what a person
  copies from an explorer and the capitalisation is a checksum.
* ClickHouse, the landing zone and the dbt seed keep the lower-case form,
  because that is what the node returns in a log and what gets compared.

Comparing one with the other does not raise anything: it quietly matches zero
rows. So every comparison goes through ``normalize()``, which returns an
``Address``, and an ``Address`` REFUSES to be compared with a string that is a
valid address in a different capitalisation. The mistake becomes an exception
at the line that made it, instead of an empty result three steps later.

Nothing else in ``src/`` or ``scripts/`` may call ``.lower()`` on an address:
``tests/test_addresses.py`` checks the source for it.
"""

from __future__ import annotations

import re

_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")


class MixedAddressFormat(TypeError):
    """A normalised address was compared with a non-normalised one."""


class Address(str):
    """A lower-case ``0x`` address. Build it with ``normalize()``, not directly."""

    __slots__ = ()

    def _check(self, other: object) -> None:
        if (
            isinstance(other, str)
            and not isinstance(other, Address)
            and _ADDRESS.fullmatch(other)
            and other != other.lower()
        ):
            raise MixedAddressFormat(
                f"comparing the normalised address {str(self)!r} with {other!r}, which is not "
                "lower-case: pass it through addresses.normalize() first"
            )

    def __eq__(self, other: object) -> bool:
        self._check(other)
        return str.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        self._check(other)
        return str.__ne__(self, other)

    __hash__ = str.__hash__


def is_address(value: object) -> bool:
    return isinstance(value, str) and bool(_ADDRESS.fullmatch(value))


def normalize(address: str) -> Address:
    """EIP-55, upper-case or lower-case in; the comparable lower-case ``Address`` out."""
    if not is_address(address):
        raise ValueError(f"not an Ethereum address: {address!r}")
    return Address(address.lower())


def same(a: str, b: str) -> bool:
    """Format-insensitive equality, for the rare place that holds two foreign strings."""
    return normalize(a) == normalize(b)
