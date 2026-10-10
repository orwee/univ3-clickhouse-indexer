"""evals/fixture/: the five dbt marts as committed files.

Most of this needs no server: it reads the files. The last test loads them into a throw-away
`test_*` database and compares that, and the files, with the live marts; it skips when
ClickHouse is not reachable or holds no marts.

The smart-money mart is in the fixture as a schema and no rows (`fixture.SCHEMA_ONLY` says
why). Several tests here exist only to fail if a row of it ever reaches a committed file.
"""

import csv
import re
from decimal import Decimal

import pytest

from evalkit import fixture
from univ3_indexer import config

RECONCILIATION = config.REPO_ROOT / "docs" / "evidence" / "2026-09-25" / "reconciliation.csv"
SMART_MONEY = "fct_pool_daily_smart_money"
WITH_ROWS = tuple(t for t in fixture.TABLES if t not in fixture.SCHEMA_ONLY)
HEX = re.compile(r"0x[0-9a-fA-F]+")

# --- no server needed ------------------------------------------------------------------


@pytest.mark.parametrize("name", fixture.TABLES)
def test_every_file_parses_and_matches_its_create_table(name):
    table = fixture.read_table(name)
    assert bool(table.rows) == (name in WITH_ROWS)
    declared = re.findall(r"^\s+`(\w+)` (.+?),?$", fixture.statements()[name], flags=re.MULTILINE)
    assert [(c, t) for c, t in zip(table.columns, table.types, strict=True)] == declared


def test_the_schema_holds_exactly_the_five_marts_with_unqualified_names():
    assert tuple(fixture.statements()) == fixture.TABLES
    assert fixture.read_fingerprint()["source_database"] not in "".join(
        fixture.statements().values()
    )


@pytest.mark.parametrize("name", fixture.TABLES)
def test_the_fingerprint_matches_the_files(name):
    recorded = dict(fixture.read_fingerprint()["tables"][name])
    recorded.pop("order_by")
    if name in fixture.SCHEMA_ONLY:
        assert recorded.pop("schema_only") is True
        assert recorded.pop("why") == fixture.SCHEMA_ONLY[name]
        assert recorded == {"rows": 0}
    assert recorded == fixture.fingerprint_of(fixture.read_table(name))


def test_the_fingerprint_says_where_the_marts_came_from():
    fingerprint = fixture.read_fingerprint()
    assert set(fingerprint["tables"]) == set(fixture.TABLES)
    assert re.fullmatch(r"[0-9a-f]{40}", fingerprint["built_from_commit"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", fingerprint["exported_on"])
    assert fingerprint["format"] == fixture.FORMAT


@pytest.mark.parametrize("name", fixture.TABLES)
def test_rows_are_in_key_order_and_the_key_is_unique(name):
    """What makes two exports of the same data byte-identical: a total order."""
    table = fixture.read_table(name)
    order_by = fixture.read_fingerprint()["tables"][name]["order_by"].split(", ")
    types = dict(zip(table.columns, table.types, strict=True))

    def key(row):
        cells = (row[table.columns.index(c)] for c in order_by)
        return tuple(
            int(v) if "Int" in types[c] else v for v, c in zip(cells, order_by, strict=True)
        )

    keys = [key(row) for row in table.rows]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize("name", [*(f"{t}.tsv" for t in fixture.TABLES), fixture.SCHEMA_FILE])
def test_no_file_is_over_three_megabytes(name):
    assert (fixture.FIXTURE_DIR / name).stat().st_size <= fixture.MAX_FILE_BYTES


def test_the_smart_money_mart_is_schema_only():
    assert tuple(fixture.SCHEMA_ONLY) == (SMART_MONEY,)
    assert "Nansen" in fixture.SCHEMA_ONLY[SMART_MONEY]


def test_the_smart_money_file_has_its_two_header_lines_and_no_data_row():
    """Fails the moment the file gets a row: the per pool-day rows are not published.

    The file is byte for byte the two header lines, the names and the types, of the columns
    in the CREATE TABLE of schema.sql. So nothing else can be in it: no row and no value.
    """
    data = (fixture.FIXTURE_DIR / f"{SMART_MONEY}.tsv").read_bytes()
    assert data.count(b"\n") == 2 and data.endswith(b"\n")
    table = fixture.read_table(SMART_MONEY)
    assert table.rows == ()
    declared = re.findall(r"^\s+`(\w+)` (.+?),?$", fixture.statements()[SMART_MONEY], flags=re.M)
    names = "\t".join(c for c, _ in declared)
    types = "\t".join(t.replace("'", "\\'") for _, t in declared)
    assert data.decode() == f"{names}\n{types}\n"
    assert not HEX.search(data.decode())


def test_no_smart_money_figure_is_anywhere_else_in_the_fixture():
    """No other file may carry a column derived from the classification."""
    for name in WITH_ROWS:
        derived = [c for c in fixture.read_table(name).columns if "smart" in c.lower()]
        assert not derived, f"{name} holds {derived}"
    fingerprint = fixture.read_fingerprint()["tables"][SMART_MONEY]
    assert set(fingerprint) == {"order_by", "rows", "schema_only", "why"}
    assert fingerprint["rows"] == 0


def test_a_schema_only_table_with_a_row_is_caught(tmp_path):
    """The check above is not vacuous: one row in the file, and the same assertions fail."""
    header = (fixture.FIXTURE_DIR / f"{SMART_MONEY}.tsv").read_bytes()
    cells = len(header.split(b"\n")[0].split(b"\t"))
    (tmp_path / f"{SMART_MONEY}.tsv").write_bytes(header + b"\t".join([b"1"] * cells) + b"\n")
    table = fixture.read_table(SMART_MONEY, tmp_path)
    assert table.rows != ()
    assert fixture.fingerprint_of(table) != {"rows": 0}


def test_fct_pool_daily_agrees_with_the_committed_reconciliation():
    """The fixture against docs/evidence/2026-09-25/reconciliation.csv, our side only.

    Compared, for every pool-day present in both: `swaps` with `our_swaps`, exactly, and
    `volume_usd` with `our_volume_usd`, rounded to the number of decimals the CSV prints for
    that row. Also that every row of the fixture is in the CSV.

    Not compared: anything about the external source (`external_volume_usd`, the
    differences, the flags), the CSV rows marked `only_external`, which have no row in the
    mart, the other columns of `fct_pool_daily`, and the other four marts.
    """
    table = fixture.read_table("fct_pool_daily")
    ours = {
        (address, day): (int(swaps), Decimal(volume))
        for address, day, swaps, volume in zip(
            table.column("pool_address"),
            table.column("block_date"),
            table.column("swaps"),
            table.column("volume_usd"),
            strict=True,
        )
    }
    with RECONCILIATION.open(newline="") as fh:
        theirs = {(row["pool_address"], row["date"]): row for row in csv.DictReader(fh)}
    shared = ours.keys() & theirs.keys()
    assert shared == ours.keys()
    assert len(shared) == 188
    assert {theirs[k]["presence"] for k in theirs.keys() - shared} == {"only_external"}
    disagreements = []
    for key in sorted(shared):
        swaps, volume = ours[key]
        printed = theirs[key]["our_volume_usd"]
        decimals = len(printed.partition(".")[2])
        if swaps != int(theirs[key]["our_swaps"]):
            disagreements.append((*key, "swaps", swaps, theirs[key]["our_swaps"]))
        if round(volume, decimals) != Decimal(printed):
            disagreements.append((*key, "volume_usd", str(volume), printed))
    assert not disagreements


def test_parse_refuses_what_it_cannot_read_faithfully():
    good = b"a\tb\nUInt8\tString\n1\tx\n"
    assert fixture.parse("t", good).rows == (("1", "x"),)
    assert fixture.parse("t", b"a\nNullable(UInt8)\n\\N\n").rows == ((None,),)
    for bad in (
        good[:-1],
        b"a\tb\nUInt8\n1\tx\n",
        b"a\tb\nUInt8\tString\n1\n",
        good[:-2] + b"\\t\n",
    ):
        with pytest.raises(ValueError, match="^t: "):
            fixture.parse("t", bad)


def test_load_refuses_a_database_name_that_is_not_an_identifier():
    with pytest.raises(ValueError, match="not a plain SQL identifier"):
        fixture.load(client=None, database="test_x; DROP DATABASE onchain")


# --- against the server ----------------------------------------------------------------


def test_the_fixture_loaded_into_a_test_database_equals_the_live_marts(clickhouse, temp_database):
    """Table by table. Four marts byte for byte, in both directions; one by its schema only.

    The files are loaded into a `test_*` database and dumped again: that must give back the
    files. The live marts dumped the same way must give the files too. If the marts have been
    rebuilt or have grown since the export, this fails: run `make eval-fixture` and commit.

    The smart-money mart has no rows in the fixture, so there is nothing to compare row by
    row and none of its live rows is read here: only its CREATE TABLE is compared, with
    schema.sql and with the table the loader created, which must be empty.
    """
    live = fixture.read_fingerprint()["source_database"]
    present = clickhouse.query(
        "SELECT name FROM system.tables WHERE database = {db:String}", parameters={"db": live}
    ).result_rows
    if not set(fixture.TABLES) <= {row[0] for row in present}:
        pytest.skip(f"the server has no marts in {live}: nothing to compare the fixture with")
    loaded = fixture.load(clickhouse, temp_database)
    for name in WITH_ROWS:
        committed = (fixture.FIXTURE_DIR / f"{name}.tsv").read_bytes()
        assert loaded[name] == fixture.read_fingerprint()["tables"][name]["rows"]
        assert fixture.dump(clickhouse, temp_database, name) == committed, f"{name}: round trip"
        assert fixture.dump(clickhouse, live, name) == committed, f"{name}: live marts differ"
    for name in fixture.SCHEMA_ONLY:
        committed = fixture.statements()[name]
        assert loaded[name] == 0
        assert fixture.create_statement(clickhouse, live, name) == committed
        assert fixture.create_statement(clickhouse, temp_database, name) == committed
        header = (fixture.FIXTURE_DIR / f"{name}.tsv").read_bytes()
        assert fixture.dump(clickhouse, temp_database, name) == header
