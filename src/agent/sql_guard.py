"""A first look at the SQL the model wrote, before it is sent.

This is NOT what keeps the warehouse safe. The database does that: the agent connects as a
user that is read-only, that has SELECT on a fixed list of tables and on nothing else, and
whose limits it cannot change. Which tables may be read is decided by those grants, so this
module does not try to work out table names from the text: a query against a table the user
may not read comes back from the server as an error, and the error is what the model learns
from.

What the guard is for: statements that could never be right here are stopped without a
round trip, and the model gets one clear sentence about what to change. It accepts exactly
one statement, a SELECT or a WITH ... SELECT, and rejects several statements, a SETTINGS
clause, INTO OUTFILE, a FORMAT clause and table functions that read from outside the
database (url, file, remote, s3 and the like).

It deliberately does not judge whether the query is correct. A query whose alias shadows a
column, a wrong column name or a type error all pass: rejecting those is the database's job.
"""

from __future__ import annotations

from dataclasses import dataclass

# Table functions that only produce rows out of their own arguments. Everything else the
# server offers as a table function is refused here by name.
SAFE_TABLE_FUNCTIONS = frozenset(
    {
        "format",  # also an ordinary string function; as a table function it parses a literal
        "generateRandom",
        "generateSeries",
        "generate_series",
        "null",
        "numbers",
        "numbers_mt",
        "primes",
        "values",
        "view",
        "viewIfPermitted",
        "zeros",
        "zeros_mt",
    }
)

# `SELECT name FROM system.table_functions` on ClickHouse 26.3.33.24, read on 2026-10-10,
# minus the safe ones above. A test compares both sets with the server it runs against, so a
# table function that appears in a later version has to be put in one of them by hand.
REFUSED_TABLE_FUNCTIONS = frozenset(
    """
    arrowFlight arrowflight azureBlobStorage azureBlobStorageCluster cluster clusterAllReplicas
    cosn deltaLake deltaLakeAzure deltaLakeAzureCluster deltaLakeCluster deltaLakeLocal
    deltaLakeS3 deltaLakeS3Cluster dictionary executable file fileCluster fuzzJSON fuzzQuery
    gcs hdfs hdfsCluster hive hudi hudiCluster iceberg icebergAzure icebergAzureCluster
    icebergCluster icebergHDFS icebergHDFSCluster icebergLocal icebergLocalCluster icebergS3
    icebergS3Cluster input jdbc loop merge mergeTreeAnalyzeIndexes mergeTreeAnalyzeIndexesUUID
    mergeTreeIndex mergeTreeProjection mergeTreeTextIndex mongodb mysql odbc oss paimon
    paimonAzure paimonAzureCluster paimonCluster paimonHDFS paimonHDFSCluster paimonLocal
    paimonS3 paimonS3Cluster postgresql prometheusQuery prometheusQueryRange redis remote
    remoteSecure s3 s3Cluster sqlite timeSeriesData timeSeriesMetrics timeSeriesSelector
    timeSeriesTags url urlCluster viewExplain ytsaurus
    """.split()
)
_REFUSED_UPPER = frozenset(name.upper() for name in REFUSED_TABLE_FUNCTIONS)

PREFIX = "Not sent to the database. "


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    message: str = ""  # written for the model: what was wrong and what to send instead


@dataclass(frozen=True)
class _Token:
    kind: str  # word, quoted (an identifier in backticks or double quotes), string, other
    text: str  # for quoted: the identifier without its quotes


class _Unreadable(ValueError):
    pass


def _closing(sql: str, start: int, quote: str, what: str) -> int:
    """Index just past the closing quote of a literal that opens at ``start``."""
    i = start + 1
    while i < len(sql):
        if sql[i] == "\\":
            i += 2
        elif sql[i] == quote:
            if sql[i + 1 : i + 2] == quote:  # a doubled quote is the quote itself
                i += 2
            else:
                return i + 1
        else:
            i += 1
    raise _Unreadable(f"a {what} is opened and never closed")


def _heredoc_tag(sql: str, start: int) -> str | None:
    """``$tag$`` at ``start``, when the text there opens a dollar-quoted string."""
    end = start + 1
    while end < len(sql) and (sql[end].isalnum() or sql[end] == "_"):
        end += 1
    return sql[start : end + 1] if sql[end : end + 1] == "$" else None


def _tokens(sql: str) -> list[_Token]:
    """Cut the text into tokens, dropping comments and whitespace.

    Only as much of the language as the checks need: what is inside a string or a comment
    must not be mistaken for a keyword, and the other way round.
    """
    out: list[_Token] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif sql.startswith("--", i) or (c == "#" and sql[i + 1 : i + 2] in (" ", "!")):
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                raise _Unreadable("a /* comment is opened and never closed")
            i = end + 2
        elif c == "'":
            end = _closing(sql, i, "'", "string")
            out.append(_Token("string", sql[i:end]))
            i = end
        elif c in '`"':
            end = _closing(sql, i, c, "quoted identifier")
            out.append(_Token("quoted", sql[i + 1 : end - 1]))
            i = end
        elif c == "$" and (tag := _heredoc_tag(sql, i)):
            end = sql.find(tag, i + len(tag))
            if end == -1:
                raise _Unreadable(f"a {tag} string is opened and never closed")
            out.append(_Token("string", sql[i : end + len(tag)]))
            i = end + len(tag)
        elif c.isalpha() or c == "_":
            end = i + 1
            while end < n and (sql[end].isalnum() or sql[end] == "_"):
                end += 1
            out.append(_Token("word", sql[i:end]))
            i = end
        else:
            out.append(_Token("other", c))
            i += 1
    return out


def _is(token: _Token | None, word: str) -> bool:
    return token is not None and token.kind == "word" and token.text.upper() == word


# Words after which FORMAT can only be a column that happens to have that name.
_BEFORE_AN_EXPRESSION = frozenset(
    "SELECT DISTINCT BY WHERE PREWHERE HAVING AND OR NOT ON WHEN THEN ELSE CASE".split()
)


def _ends_with_a_format_clause(tokens: list[_Token], i: int) -> bool:
    """``... FORMAT name`` closing the statement, as opposed to a column called format."""
    rest = tokens[i + 1 :]
    if not rest or rest[0].kind != "word":
        return False
    if len(rest) > 1 and not _is(rest[1], "SETTINGS"):
        return False
    previous = tokens[i - 1] if i else None
    if previous is None or (previous.kind == "other" and previous.text in ",(=<>+-/"):
        return False
    return not (previous.kind == "word" and previous.text.upper() in _BEFORE_AN_EXPRESSION)


def check(sql: str) -> Verdict:
    """Whether this text may be sent, and if not, one sentence for the model."""
    try:
        tokens = _tokens(sql)
    except _Unreadable as problem:
        return Verdict(False, f"{PREFIX}The SQL could not be read: {problem}.")
    if not tokens:
        return Verdict(False, f"{PREFIX}The SQL is empty. Send one SELECT statement.")

    separators = [i for i, t in enumerate(tokens) if t.kind == "other" and t.text == ";"]
    if separators:
        if separators[0] != len(tokens) - 1:
            return Verdict(
                False,
                f"{PREFIX}Exactly one statement is accepted and this text has something "
                "after the first ';'. Send a single SELECT; use WITH or subqueries instead "
                "of several statements.",
            )
        tokens = tokens[:-1]
        if not tokens:
            return Verdict(False, f"{PREFIX}The SQL is empty. Send one SELECT statement.")

    first = next((t for t in tokens if not (t.kind == "other" and t.text == "(")), None)
    if not (_is(first, "SELECT") or _is(first, "WITH")):
        seen = first.text if first is not None else "("
        return Verdict(
            False,
            f"{PREFIX}Only SELECT, or WITH ... SELECT, is accepted, and this statement "
            f"starts with {seen[:30]!r}. To see columns and types use the describe_schema "
            "tool, not SQL.",
        )
    if _is(first, "WITH") and not any(_is(t, "SELECT") for t in tokens):
        return Verdict(False, f"{PREFIX}The statement starts with WITH and has no SELECT.")

    for i, token in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        after = tokens[i + 2] if i + 2 < len(tokens) else None
        if (
            _is(token, "SETTINGS")
            and following is not None
            and following.kind in ("word", "quoted")
            and after is not None
            and after.text == "="
        ):
            return Verdict(
                False,
                f"{PREFIX}A SETTINGS clause is not accepted: the limits of this connection "
                "are fixed. Remove the clause; if the query is too slow or returns too "
                "many rows, aggregate or filter more.",
            )
        if _is(token, "INTO") and _is(following, "OUTFILE"):
            return Verdict(
                False, f"{PREFIX}INTO OUTFILE is not accepted. Remove it: rows come back here."
            )
        if _is(token, "FORMAT") and _ends_with_a_format_clause(tokens, i):
            return Verdict(
                False,
                f"{PREFIX}A FORMAT clause is not accepted: rows come back in one fixed "
                "form. Remove the clause.",
            )
        if (
            token.kind in ("word", "quoted")
            and token.text.upper() in _REFUSED_UPPER
            and following is not None
            and following.text == "("
            and following.kind == "other"
        ):
            return Verdict(
                False,
                f"{PREFIX}The table function {token.text}() is not available: nothing "
                "outside the database can be read. Query the tables that describe_schema "
                "lists.",
            )
    return Verdict(True)
