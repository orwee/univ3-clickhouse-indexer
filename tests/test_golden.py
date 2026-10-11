"""The golden set: evals/golden.jsonl, and the generator that computes it.

Most of this needs no server: it reads the committed file and redraws the cases, which only
needs the fixture files. The last tests run every reference query on the fixture loaded
into a throw-away `test_*` database. No expected answer is written in this file: where a
value is compared, the other side is the fixture, the reconciliation CSV or a query.
"""

import csv
import datetime
import re
from collections import Counter
from decimal import Decimal

import pytest

from evalkit import fixture, golden
from univ3_indexer import clickhouse as ch
from univ3_indexer import config

EVALS = config.REPO_ROOT / "evals"
GOLDEN = EVALS / "golden.jsonl"
TEMPLATES = EVALS / "golden_templates.py"
HAND = EVALS / "hand_cases.yml"
RECONCILIATION = config.REPO_ROOT / "docs" / "evidence" / "2026-09-25" / "reconciliation.csv"
EVALKIT_DIR = config.REPO_ROOT / "src" / "evalkit"
DOMAIN_WORDS = ("uniswap", "swap", "pool", "usdc", "weth")

# What changes from one draw to the next: digits, months, symbols and fee tiers.
VARIABLE_PARTS = re.compile(
    r"\d|January|February|March|April|May|June|July|August|September|October|November"
    r"|December|wstETH|WETH|USDC|/| 0\.\d+%"
)

templates = golden.load_module(TEMPLATES)


def hand_file():
    return HAND if HAND.exists() else None


@pytest.fixture(scope="module")
def cases():
    return golden.load(GOLDEN)


@pytest.fixture(scope="module")
def specs():
    return golden.collect(TEMPLATES, hand_file(), golden.DEFAULT_SEED)


def template_cases(cases):
    return [case for case in cases if case["kind"] == "template"]


# --- src/evalkit/ is generic ---------------------------------------------------------------


def test_nothing_under_src_evalkit_names_a_table_a_column_or_a_token_of_this_warehouse():
    """The twin of the test that keeps src/agent/ generic.

    No domain word in any case, and no table or column of the fixture as a whole word.
    Everything that names something of this warehouse lives under evals/.
    """
    names = set(fixture.TABLES)
    for table in fixture.TABLES:
        names.update(fixture.read_table(table).columns)
    tokens = set()
    for row in fixture.read_table("dim_pools").rows:
        tokens.update(cell for cell in row if re.fullmatch(r"[A-Za-z]{3,8}", cell or ""))
    assert {"volume_usd", "block_date", "fct_pool_daily"} <= names and "wstETH" in tokens
    files = [p for p in EVALKIT_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert any(p.name == "golden.py" for p in files)
    for path in files:
        text = path.read_text(encoding="utf-8")
        found = [word for word in DOMAIN_WORDS if word in text.lower()]
        found += [name for name in sorted(names | tokens) if re.search(rf"\b{name}\b", text)]
        assert not found, f"{path.relative_to(config.REPO_ROOT)} mentions {found}"


# --- the file, read without a server -------------------------------------------------------


def test_ids_are_unique_and_readable(cases):
    ids = [case["id"] for case in cases]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"[a-z]-[a-z0-9-]+-\d{3}", case_id) for case_id in ids)


def test_every_field_is_present_and_of_the_right_type(cases):
    for case in cases:
        golden.validate(case)  # raises with the id of the case
        assert tuple(case) == golden.FIELDS
    numbers = [case for case in cases if case["answer_type"] == "number"]
    assert numbers and all(isinstance(case["expected"], str) for case in numbers)
    assert all(case["unit"] for case in numbers), "every number says what it is in"


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"expected": 12.5}, "is not a number"),
        ({"expected": "1e400000000"}, None),
        ({"tolerance": None}, "needs a tolerance"),
        ({"tolerance": {"abs": "0.01"}}, "needs a tolerance"),
        ({"split": "train"}, "unknown kind or split"),
        ({"kind": "unanswerable"}, "a case with no answer is a refusal"),
        ({"reference_sql": "SELECT 1; SELECT 2"}, "one SELECT statement"),
        ({"reference_sql": "DROP TABLE t"}, "one SELECT statement"),
        ({"question": " "}, "question must be a non-empty text"),
        ({"accepted": None}, "accepted must be a list"),
        ({"accepted": ["twelve"]}, "is not a number"),
    ],
)
def test_a_malformed_case_is_refused(cases, change, says):
    case = {**next(c for c in cases if c["answer_type"] == "number"), **change}
    if says is None:
        golden.validate(case)  # a huge number is still a number
        return
    with pytest.raises(golden.GoldenError, match=says):
        golden.validate(case)
    missing = dict(case)
    missing.pop("notes")
    with pytest.raises(golden.GoldenError, match="the fields must be exactly"):
        golden.validate(missing)


def test_twelve_families_of_ten_template_cases(cases):
    counted = Counter(case["family"] for case in template_cases(cases))
    assert len(counted) == 12 and set(counted.values()) == {10}
    assert list(counted) == list(templates.FAMILIES)


def test_the_split_is_stratified_one_third_dev_two_thirds_test(cases):
    by_family = Counter((case["kind"], case["family"], case["split"]) for case in cases)
    families = {(kind, family) for kind, family, _ in by_family}
    for kind, family in families:
        dev, test = by_family[(kind, family, "dev")], by_family[(kind, family, "test")]
        assert dev == round((dev + test) / 3), (kind, family, dev, test)
    of_templates = Counter(case["split"] for case in template_cases(cases))
    assert of_templates == {"dev": 36, "test": 84}


def test_the_committed_cases_are_the_ones_the_seed_draws(cases, specs):
    """Everything but the answer can be redrawn without a server, and it is the same."""
    assert [spec.id for spec in specs] == [case["id"] for case in cases]
    splits = golden.assign_splits(specs)
    for spec, case in zip(specs, cases, strict=True):
        assert (spec.question, spec.kind, spec.family, spec.answer_type, spec.unit) == (
            case["question"], case["kind"], case["family"], case["answer_type"], case["unit"],
        )  # fmt: skip
        assert spec.reference_sql == case["reference_sql"] and spec.notes == case["notes"]
        assert golden.tolerance_of(spec) == case["tolerance"]
        assert splits[spec.id] == case["split"]


def test_the_default_tolerances(cases):
    assert golden.TOLERANCES == {
        "count": {"abs": "0", "rel": "0"},
        "sum": {"abs": "0.01", "rel": "0.001"},
        "ratio": {"abs": "0", "rel": "0.005"},
    }
    by_family = {}
    for case in template_cases(cases):
        if case["answer_type"] == "number":
            by_family.setdefault(case["family"], set()).add(
                tuple(sorted(case["tolerance"].items()))
            )
        else:
            assert case["tolerance"] is None
    exact = (("abs", "0"), ("rel", "0"))
    assert by_family["swaps-day"] == by_family["swaps-all-range"] == {exact}
    assert by_family["vwap-day"] == {(("abs", "0"), ("rel", "0.005"))}
    assert by_family["volume-day"] == {(("abs", "0.01"), ("rel", "0.001"))}


def test_two_or_three_wordings_per_family_and_every_question_states_its_unit(cases):
    for family in templates.FAMILIES:
        mine = [case for case in cases if case["family"] == family]
        shapes = {VARIABLE_PARTS.sub("", case["question"]) for case in mine}
        assert len(shapes) >= 2, family
    said = {
        "USD": ("US dollars", "USD"),
        "percent": ("percent", "percentage"),
        "swaps": ("swaps", "swap"),
    }
    for case in template_cases(cases):
        if case["answer_type"] != "number":
            assert re.search(r"label|date|day|name the|which one", case["question"]), case["id"]
            continue
        words = said.get(case["unit"], tuple(case["unit"].split(" per ")))
        assert any(word in case["question"] for word in words), case["id"]


def test_the_complete_days_are_the_ones_the_reconciliation_did_not_mark_partial():
    with RECONCILIATION.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    partial = {row["date"] for row in rows if row["partial_day"] == "1"}
    whole = {row["date"] for row in rows if row["partial_day"] == "0"}
    assert min(whole) == templates.FIRST_COMPLETE_DAY.isoformat()
    assert max(whole) == templates.LAST_COMPLETE_DAY.isoformat()
    days = fixture.read_table("fct_pool_daily").column("block_date")
    assert partial == {min(days), max(days)} and not partial & whole


def _days_named(params: dict) -> list[datetime.date]:
    if "day" in params:
        return [params["day"]]
    if "days" in params:
        return list(params["days"])
    span = (params["end"] - params["start"]).days
    return [params["start"] + datetime.timedelta(days=k) for k in range(span + 1)]


def test_no_template_is_on_a_partial_day_or_on_a_pool_day_without_a_row(specs):
    facts = templates.Facts()
    checked = 0
    for spec in specs:
        if spec.kind != "template":
            continue
        days = _days_named(spec.params)
        assert all(
            templates.FIRST_COMPLETE_DAY <= day <= templates.LAST_COMPLETE_DAY for day in days
        ), spec.id
        # Every date written in the query is one of those days: nothing else slipped in.
        written = set(re.findall(r"\d{4}-\d\d-\d\d", spec.reference_sql))
        assert written <= {day.isoformat() for day in days}, spec.id
        labels = spec.params.get("labels") or (
            [spec.params["label"]] if "label" in spec.params else []
        )
        for label in labels:
            for day in days:
                assert facts.has(label, day), f"{spec.id}: {label} has no row on {day}"
                checked += 1
    assert checked > 300
    # The four pool-days without a row, as the draws see them.
    first, last = min(day for _, day in facts.rows), max(day for _, day in facts.rows)
    absent = [
        (label, day.isoformat())
        for label in facts.labels
        for day in (first + datetime.timedelta(days=k) for k in range((last - first).days + 1))
        if not facts.has(label, day)
    ]
    assert len(absent) == 4 and {label.split()[0] for label, _ in absent} == {"wstETH/USDC"}


def test_families_one_and_two_agree_with_the_reconciliation(cases, specs):
    """The volume and the swaps of one pool on one day, against a file computed by another path.

    docs/evidence/2026-09-25/reconciliation.csv is made by `make reconcile` from the raw
    table, not from the marts. Compared: `expected` of every case of `volume-day` with
    `our_volume_usd` to the decimals the CSV prints, and of every case of `swaps-day` with
    `our_swaps`, exactly.
    """
    with RECONCILIATION.open(newline="") as fh:
        theirs = {(row["pool"], row["date"]): row for row in csv.DictReader(fh)}
    by_id = {case["id"]: case for case in cases}
    compared = Counter()
    for spec in specs:
        if spec.family not in ("volume-day", "swaps-day") or spec.kind != "template":
            continue
        row = theirs[(spec.params["label"], spec.params["day"].isoformat())]
        expected = Decimal(by_id[spec.id]["expected"])
        if spec.family == "swaps-day":
            assert expected == int(row["our_swaps"]), spec.id
        else:
            printed = row["our_volume_usd"]
            assert round(expected, len(printed.partition(".")[2])) == Decimal(printed), spec.id
        compared[spec.family] += 1
    assert compared == {"volume-day": 10, "swaps-day": 10}


# --- the cases written by hand ---------------------------------------------------------------

HARD = {
    "multi-step", "units", "reversed-name", "gross-net", "ambiguous", "ordered-list",
    "missing-row", "dates",
}  # fmt: skip
NO_ANSWER = {
    "not-in-data", "other-chain", "out-of-range", "forecast", "not-in-marts", "smart-money",
    "legs-trap",
}  # fmt: skip


def test_thirty_hard_cases_and_thirty_with_no_answer_at_least_three_per_category(cases):
    hard = Counter(case["family"] for case in cases if case["kind"] == "hand")
    none = Counter(case["family"] for case in cases if case["kind"] == "unanswerable")
    assert sum(hard.values()) == 30 and set(hard) == HARD and min(hard.values()) >= 3
    assert sum(none.values()) == 30 and set(none) == NO_ANSWER and min(none.values()) >= 3
    assert len(cases) == 180
    by_split = Counter((case["kind"], case["split"]) for case in cases)
    assert by_split[("hand", "dev")] + by_split[("hand", "test")] == 30
    assert by_split[("hand", "dev")] > 0 and by_split[("unanswerable", "dev")] > 0


def test_a_case_with_no_answer_is_a_refusal_and_says_what_a_wrong_answer_looks_like(cases):
    for case in cases:
        if case["kind"] != "unanswerable":
            continue
        assert case["answer_type"] == "refusal" and case["expected"] is None
        assert case["reference_sql"] is None and case["accepted"] == []
        assert "wrong answer" in case["notes"], case["id"]


def test_no_answer_is_written_by_hand(tmp_path):
    """The file of hand cases holds questions and queries. A value in it is refused."""
    text = HAND.read_text()
    assert not re.search(r"^\s*(expected|accepted|split)\s*:", text, flags=re.MULTILINE)
    from evalkit import hand_cases

    base = "- {id: h-x-001, kind: hand, family: x, question: q, notes: n, answer_type: number, "
    for extra, says in [
        ("reference_sql: SELECT 1, tolerance: count, expected: '1'}", "cannot be written by hand"),
        (
            "reference_sql: SELECT 1, tolerance: count, accepted: ['2']}",
            "cannot be written by hand",
        ),
        ("tolerance: count}", "needs answer_type and reference_sql"),
        ("reference_sql: SELECT 1, colour: red}", "unknown"),
    ]:
        path = tmp_path / "cases.yml"
        path.write_text(base + extra + "\n")
        with pytest.raises(golden.GoldenError, match=says):
            hand_cases.load(path)
    path.write_text(
        "- {id: u-x-001, kind: unanswerable, family: x, question: q, notes: n, unit: USD}\n"
    )
    with pytest.raises(golden.GoldenError, match="has no unit"):
        hand_cases.load(path)


def test_a_reversed_name_does_not_appear_as_a_label_in_the_data(cases):
    labels = set(fixture.read_table("dim_pools").column("pool_label"))
    for case in cases:
        if case["family"] == "reversed-name":
            asked = re.search(r"\b(\w+/\w+ 0\.\d+%)", case["question"]).group(1)
            assert asked not in labels
            tokens, tier = asked.split()
            assert "/".join(reversed(tokens.split("/"))) + " " + tier in labels


def test_the_ambiguous_cases_show_their_readings(cases, specs):
    by_id = {spec.id: spec for spec in specs}
    listed = {c["id"]: c["accepted"] for c in cases if c["family"] == "ambiguous"}
    assert len(listed) >= 3
    for case_id in listed:
        assert by_id[case_id].accepted_sql, f"{case_id} has no query for its other reading"
    assert sum(1 for values in listed.values() if values) >= 2  # readings that differ
    assert sum(1 for values in listed.values() if not values) >= 1  # readings that agree


def test_plain_number_keeps_every_digit_and_refuses_what_is_not_a_number():
    big = Decimal("1234567890123456789012345678901234567890.123456789012345678")
    assert golden.plain_number(big) == str(big)
    assert golden.plain_number(Decimal("12.500")) == "12.5"
    assert golden.plain_number(7) == "7" and golden.plain_number(0.25) == "0.25"
    for bad in (True, "7", None, float("nan"), Decimal("Infinity")):
        with pytest.raises(golden.GoldenError):
            golden.plain_number(bad)


# --- on the fixture, in a throw-away database -----------------------------------------------


@pytest.fixture(scope="module")
def on_fixture(clickhouse, marts_database):
    return ch.connect(database=marts_database)


def test_every_reference_sql_returns_exactly_the_stored_answer(on_fixture, cases, specs):
    ran = 0
    by_id = {spec.id: spec for spec in specs}
    for case in cases:
        if case["answer_type"] == "refusal":
            continue
        got = golden.answer(on_fixture, case["reference_sql"], case["answer_type"])
        assert got == case["expected"], case["id"]
        also = [
            golden.answer(on_fixture, sql, case["answer_type"])
            for sql in by_id[case["id"]].accepted_sql
        ]
        assert [a for a in dict.fromkeys(also) if a != got] == case["accepted"], case["id"]
        ran += 1
    assert ran >= 120


def test_regenerating_gives_the_same_bytes(clickhouse):
    """The whole generator, in a database of its own: the committed file, byte for byte."""
    count = "SELECT count() FROM system.databases WHERE name LIKE 'test_%'"
    before = clickhouse.query(count).result_rows
    text = golden.generate(clickhouse, TEMPLATES, hand_file())
    assert text.encode() == GOLDEN.read_bytes()
    assert clickhouse.query(count).result_rows == before  # its database is gone again


def test_every_label_and_date_answer_of_a_template_is_a_unique_maximum(on_fixture, specs):
    asked = 0
    for spec in specs:
        if spec.kind == "template" and spec.answer_type in ("label", "date"):
            assert spec.unique_sql, spec.id
            assert on_fixture.query(spec.unique_sql).result_rows == [(1,)], spec.id
            asked += 1
    assert asked == 20


def test_a_query_that_does_not_give_one_answer_is_refused(on_fixture):
    for sql, kind, says in [
        ("SELECT number FROM numbers(2)", "number", "2 rows"),
        ("SELECT 1, 2", "number", "one column"),
        ("SELECT CAST(NULL AS Nullable(UInt8))", "number", "NULL"),
        ("SELECT 'x'", "date", "not a date"),
        ("SELECT 1 WHERE 0", "list", "no rows"),
        ("SELECT 1; SELECT 2", "number", "not one SELECT"),
    ]:
        with pytest.raises(golden.GoldenError, match=says):
            golden.answer(on_fixture, sql, kind)
    assert golden.answer(on_fixture, "SELECT toString(number) FROM numbers(3)", "list") == [
        "0", "1", "2",
    ]  # fmt: skip
    assert golden.answer(on_fixture, "SELECT toDate('2026-08-19')", "date") == "2026-08-19"
