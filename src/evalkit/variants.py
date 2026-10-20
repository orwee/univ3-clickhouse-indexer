"""A variant: one file that says what a run changes, and nothing else.

``<directory>/<name>.yml`` may set seven things, all optional:

``model``
    a model id, in place of the default in the code.
``schema_notes``
    a file of table and column descriptions. ``describe_schema`` then returns them next to
    the names and the types.
``prompt_addendum``
    a file of text, appended to the system prompt.
``max_usd_per_question``
    dollars one question may cost, in place of the warehouse file's limit.

``prompt_cache``
    ``true`` to send the part of the prompt that every call repeats as a cached prefix.
    The model is sent the same text; what changes is how it is billed.

``provider``
    where the requests go, in place of the default. A provider is used only when a variant
    names it, and a run talks to that one and to no other.

``docs_tool``
    ``true`` to offer the agent ``search_docs``, a search over the documentation, and to let
    it answer in words with citations. Off unless set.

A file that sets none of them is the baseline. Any other key is refused, so a typo cannot
pass for a setting. The two paths are relative to the variant file's own directory.

What a run used is pinned by content, not by name: ``files`` holds the SHA-256 of the
variant file and of every file it points at, and the runner writes it into the results.

This module reads files and hands plain values on. The agent takes the descriptions and
the addendum as arguments and knows nothing of where they come from.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

FIELDS = (
    "model",
    "schema_notes",
    "prompt_addendum",
    "max_usd_per_question",
    "prompt_cache",
    "provider",
    "docs_tool",
)
PROVIDERS = ("anthropic", "cheaperinference")
DEFAULT_PROVIDER = PROVIDERS[0]
NAME = re.compile(r"[A-Za-z0-9._-]+")  # it becomes part of file names
TABLE_FIELDS = ("description", "columns")


class VariantError(ValueError):
    """The variant file is missing, or holds something that is not one of the seven settings."""


@dataclass(frozen=True)
class Variant:
    name: str
    model: str | None = None
    descriptions: dict | None = None  # {table: {"description": text, "columns": {name: text}}}
    prompt_addendum: str = ""
    max_usd_per_question: Decimal | None = None
    provider: str = DEFAULT_PROVIDER
    prompt_cache: bool = False
    docs_tool: bool = False
    files: dict[str, str] = field(default_factory=dict)  # path -> SHA-256 of its bytes


def _shown(path: Path, root: Path | None) -> str:
    """The path as the results record it: relative to ``root`` when it is inside it."""
    resolved = path.resolve()
    if root is not None and root.resolve() in resolved.parents:
        return resolved.relative_to(root.resolve()).as_posix()
    return resolved.as_posix()


def _text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VariantError(f"{what} must be a non-empty text")
    return " ".join(value.split())


def load_descriptions(path: Path) -> dict:
    """Table and column descriptions from a YAML file.

    ``tables`` maps a table name to ``description`` (a text) and ``columns`` (column name to
    text). Both are optional for a table; anything else is refused.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise VariantError(f"{path}: file not found") from None
    except yaml.YAMLError as problem:
        raise VariantError(f"{path}: not YAML ({type(problem).__name__})") from None
    if not isinstance(raw, dict) or set(raw) != {"tables"} or not isinstance(raw["tables"], dict):
        raise VariantError(f"{path}: expected one key, 'tables', holding a mapping")
    described = {}
    for table, about in raw["tables"].items():
        if not isinstance(table, str) or not isinstance(about, dict):
            raise VariantError(f"{path}: every table is a name with a mapping under it")
        unknown = sorted(set(about) - set(TABLE_FIELDS))
        if unknown:
            raise VariantError(f"{path}: {table}: unknown {unknown}")
        entry: dict = {}
        if "description" in about:
            entry["description"] = _text(about["description"], f"{path}: {table}.description")
        columns = about.get("columns", {})
        if not isinstance(columns, dict):
            raise VariantError(f"{path}: {table}.columns must be a mapping")
        entry["columns"] = {
            str(name): _text(text, f"{path}: {table}.{name}") for name, text in columns.items()
        }
        described[table] = entry
    if not described:
        raise VariantError(f"{path}: no table is described")
    return described


def load(name: str, directory: Path, root: Path | None = None) -> Variant:
    """Read ``<directory>/<name>.yml`` and the files it points at."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise VariantError("a variant name is letters, digits, dot, dash and underscore")
    path = Path(directory) / f"{name}.yml"
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        raise VariantError(
            f"no variant named {name!r}: {_shown(path, root)} does not exist"
        ) from None
    try:
        raw = yaml.safe_load(content.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as problem:
        raise VariantError(f"{path}: not YAML ({type(problem).__name__})") from None
    if raw is None:
        raw = {}  # only comments: the baseline
    if not isinstance(raw, dict):
        raise VariantError(f"{path}: expected a mapping, or nothing at all")
    unknown = sorted(str(key) for key in set(raw) - set(FIELDS))
    if unknown:
        raise VariantError(f"{path}: unknown {unknown}; a variant may set {', '.join(FIELDS)}")
    files = {_shown(path, root): hashlib.sha256(content).hexdigest()}

    def pointed(key: str) -> Path | None:
        if key not in raw:
            return None
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise VariantError(f"{path}: {key} must be the path of a file")
        target = path.parent / raw[key]
        if not target.is_file():
            raise VariantError(f"{path}: {key} points at {raw[key]}, which is not a file")
        files[_shown(target, root)] = hashlib.sha256(target.read_bytes()).hexdigest()
        return target

    model = raw.get("model")
    if "model" in raw and (not isinstance(model, str) or not model.strip()):
        raise VariantError(f"{path}: model must be a model id")
    notes, addendum = pointed("schema_notes"), pointed("prompt_addendum")
    text = addendum.read_text(encoding="utf-8").strip() if addendum is not None else ""
    if addendum is not None and not text:
        raise VariantError(f"{path}: the prompt addendum is empty")
    ceiling = None
    if "max_usd_per_question" in raw:
        try:
            ceiling = Decimal(str(raw["max_usd_per_question"]))
        except InvalidOperation:
            raise VariantError(f"{path}: max_usd_per_question must be a number") from None
        if isinstance(raw["max_usd_per_question"], bool) or not ceiling.is_finite() or ceiling <= 0:
            raise VariantError(f"{path}: max_usd_per_question must be a positive number")
    if not isinstance(raw.get("prompt_cache", False), bool):
        raise VariantError(f"{path}: prompt_cache must be true or false")
    if not isinstance(raw.get("docs_tool", False), bool):
        raise VariantError(f"{path}: docs_tool must be true or false")
    provider = raw.get("provider", DEFAULT_PROVIDER)
    if provider not in PROVIDERS:
        raise VariantError(f"{path}: provider must be one of {', '.join(PROVIDERS)}")
    return Variant(
        name=name,
        provider=provider,
        prompt_cache=raw.get("prompt_cache", False),
        docs_tool=raw.get("docs_tool", False),
        model=model,
        descriptions=load_descriptions(notes) if notes is not None else None,
        prompt_addendum=text,
        max_usd_per_question=ceiling,
        files=files,
    )


def main(argv: list[str] | None = None) -> int:
    """Print the provider a variant names. For a workflow, which has to know it before it
    decides which key the next step is given."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m evalkit.variants")
    parser.add_argument("name")
    parser.add_argument("--directory", type=Path, default=Path("evals/variants"))
    args = parser.parse_args(argv)
    try:
        print(load(args.name, args.directory).provider)
    except VariantError as problem:
        print(str(problem), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
