"""evals/fixture/: the five dbt marts as committed files.

Most of this needs no server: it reads the files. The last test loads them into a throw-away
`test_*` database and compares that, and the files, with the live marts; it skips when
ClickHouse is not reachable or holds no marts.
"""

import csv
import re
from decimal import Decimal

import pytest

from evalkit import fixture
from univ3_indexer import config

RECONCILIATION = config.REPO_ROOT / "docs" / "evidence" / "2026-09-25" / "reconciliation.csv"
SMART_MONEY = "fct_pool_daily_smart_money"
# The mart's own columns (dbt/models/marts/fct_pool_daily_smart_money.sql): the pool-day key,
# the pool's label, our own totals for that day, and aggregates of the classification.
SMART_MONEY_COLUMNS = (
    "pool_address",
    "block_date",
    "pool_label",
    "swaps",
    "volume_usd",
    "smart_money_swaps",
    "smart_money_transactions",
    "smart_money_volume_usd",
    "smart_money_share_of_swaps",
    "smart_money_share_of_volume_usd",
    "fetched_by_token",
    "computed_at",
)
HEX = re.compile(r"0x[0-9a-fA-F]+")

# --- no server needed ------------------------------------------------------------------


@pytest.mark.parametrize("name", fixture.TABLES)
def test_every_file_parses_and_matches_its_create_table(name):
    table = fixture.read_table(name)
    assert table.rows
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


def test_the_smart_money_file_holds_only_aggregates_per_pool_and_day():
    """No hash and no account address: only the four pools' own contract addresses.

    Checked: the columns are exactly the mart's; the only `0x…` strings in the whole file are
    in the `pool_address` column and are the four pools of dim_pools (public contract
    addresses from pools.yml, the key of the row, not something Nansen returned); nothing has
    the length of a transaction hash; one row per pool and day.
    """
    table = fixture.read_table(SMART_MONEY)
    assert table.columns == SMART_MONEY_COLUMNS
    pools = set(fixture.read_table("dim_pools").column("pool_address"))
    assert len(pools) == 4
    address = table.columns.index("pool_address")
    for row in table.rows:
        assert row[address] in pools
        for i, cell in enumerate(row):
            if i != address:
                assert not HEX.search(cell or ""), f"a 0x value in column {table.columns[i]}"
    text = (fixture.FIXTURE_DIR / f"{SMART_MONEY}.tsv").read_text()
    assert {m.lower() for m in HEX.findall(text)} == pools
    assert not re.search(r"[0-9a-fA-F]{41,}", text)
    days = list(zip(table.column("pool_address"), table.column("block_date"), strict=True))
    assert len(set(days)) == len(days)


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
    """Table by table, byte for byte, in both directions.

    The files are loaded into a `test_*` database and dumped again: that must give back the
    files. The live marts dumped the same way must give the files too. If the marts have been
    rebuilt or have grown since the export, this fails: run `make eval-fixture` and commit.
    """
    live = fixture.read_fingerprint()["source_database"]
    present = clickhouse.query(
        "SELECT name FROM system.tables WHERE database = {db:String}", parameters={"db": live}
    ).result_rows
    if not set(fixture.TABLES) <= {row[0] for row in present}:
        pytest.skip(f"the server has no marts in {live}: nothing to compare the fixture with")
    loaded = fixture.load(clickhouse, temp_database)
    for name in fixture.TABLES:
        committed = (fixture.FIXTURE_DIR / f"{name}.tsv").read_bytes()
        assert loaded[name] == fixture.read_fingerprint()["tables"][name]["rows"]
        assert fixture.dump(clickhouse, temp_database, name) == committed, f"{name}: round trip"
        assert fixture.dump(clickhouse, live, name) == committed, f"{name}: live marts differ"
