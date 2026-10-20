"""Golden set v2: evals/golden_v2.jsonl, and what keeps v1 as it was.

v1 (evals/golden.jsonl) is covered by tests/test_golden.py and is not touched. These tests are
about the second file: its shape, its split, that its answers are computed and not written,
that it asks what it says it asks, and, for the ones that need a server, that the committed
answers are the ones the queries give on the fixture.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from decimal import Decimal

import pytest

from evalkit import fixture, golden
from univ3_indexer import clickhouse as ch
from univ3_indexer import config

EVALS = config.REPO_ROOT / "evals"
V1 = EVALS / "golden.jsonl"
GOLDEN = EVALS / "golden_v2.jsonl"
TEMPLATES = EVALS / "golden_v2_templates.py"
HAND = EVALS / "hand_cases_v2.yml"
SEED = 20261019
DEV_FRACTION = 0.3

# v1 as it was when v2 was made. Every earlier result and the regression check depend on it:
# a change to v1 is a decision, and this line is where it has to be made on purpose.
V1_SHA256 = "21f1c675a593eb0ee81afb90376e1a462e5694b305c7e667a1607433d0a2c620"

TEMPLATE_FAMILIES = {
    "partial-day", "absent-poolday", "fee-units", "token-direction", "gross-net",
    "days-above", "pool-ratio", "average", "ranges-edges", "top-range",
}  # fmt: skip
HARD_FAMILIES = {
    "multi-step", "units", "gross-net", "partial-day", "missing-pool-day", "ambiguous",
    "list", "reversed-name", "dates", "period-compare",
}  # fmt: skip
NO_ANSWER_FAMILIES = {
    "intraday", "outside-window", "other-pool", "other-chain", "smart-money", "not-held",
    "forecast", "near-miss", "liquidity", "other-sources",
}  # fmt: skip
# Only these ask about a partial day or an absent pool-day on purpose.
EDGE_FAMILIES = {"partial-day", "absent-poolday", "ranges-edges"}

templates = golden.load_module(TEMPLATES)


@pytest.fixture(scope="module")
def cases():
    return golden.load(GOLDEN)


@pytest.fixture(scope="module")
def specs():
    return golden.collect(TEMPLATES, HAND, SEED)


def test_v1_is_exactly_as_it_was():
    assert hashlib.sha256(V1.read_bytes()).hexdigest() == V1_SHA256


def test_default_split_of_v1_is_unchanged_and_v2_asks_for_its_own(specs):
    ten = [s for s in specs if s.family == "gross-net" and s.kind == "template"]
    assert len(ten) == 10
    assert sum(v == "dev" for v in golden.assign_splits(ten, SEED).values()) == round(10 / 3)
    assert sum(v == "dev" for v in golden.assign_splits(ten, SEED, 0.3).values()) == 3
    six = [s for s in specs if s.kind == "hand" and s.family == "units"]
    assert sum(v == "dev" for v in golden.assign_splits(six, SEED, 0.3).values()) == 2


def test_240_cases_100_template_60_hard_80_with_no_answer(cases):
    assert len(cases) == 240
    assert Counter(case["kind"] for case in cases) == {
        "template": 100, "hand": 60, "unanswerable": 80,
    }  # fmt: skip
    for kind, families, per_family in (
        ("template", TEMPLATE_FAMILIES, 10),
        ("hand", HARD_FAMILIES, 6),
        ("unanswerable", NO_ANSWER_FAMILIES, 8),
    ):
        counts = Counter(case["family"] for case in cases if case["kind"] == kind)
        assert set(counts) == families and set(counts.values()) == {per_family}, kind


def test_ids_start_with_v2_are_unique_and_do_not_collide_with_v1(cases):
    ids = [case["id"] for case in cases]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"v2-[a-z]-[a-z0-9-]+-\d{3}", case_id) for case_id in ids)
    old = golden.load(V1)
    assert not {case["id"] for case in old} & set(ids)
    # No question of v2 is a question of v1 word for word.
    assert not {case["question"] for case in old} & {case["question"] for case in cases}


def test_every_field_is_present_and_of_the_right_type(cases):
    for case in cases:
        golden.validate(case)
        assert tuple(case) == golden.FIELDS


def test_split_is_about_thirty_seventy_stratified_by_kind_and_family(cases):
    by_split = Counter(case["split"] for case in cases)
    assert by_split == {"dev": 70, "test": 170}
    for kind in ("template", "hand", "unanswerable"):
        mine = [case for case in cases if case["kind"] == kind]
        dev = sum(case["split"] == "dev" for case in mine)
        assert abs(dev / len(mine) - 0.3) < 0.05, kind
        for family in {case["family"] for case in mine}:
            group = [case for case in mine if case["family"] == family]
            assert sum(c["split"] == "dev" for c in group) == round(len(group) * DEV_FRACTION)
    # The test split has enough questions with no answer to say something about refusals.
    assert sum(c["split"] == "test" and c["kind"] == "unanswerable" for c in cases) == 60


def test_the_committed_cases_are_the_ones_the_seed_draws(cases, specs):
    assert [spec.id for spec in specs] == [case["id"] for case in cases]
    splits = golden.assign_splits(specs, SEED, DEV_FRACTION)
    for spec, case in zip(specs, cases, strict=True):
        assert spec.question == case["question"]
        assert (spec.kind, spec.family) == (case["kind"], case["family"])
        assert spec.reference_sql == case["reference_sql"] and spec.notes == case["notes"]
        assert splits[spec.id] == case["split"]
        assert golden.tolerance_of(spec) == case["tolerance"]


def test_no_answer_is_written_in_the_hand_file_or_the_templates():
    text = HAND.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(expected|accepted|split)\s*:", text, re.MULTILINE)
    assert not re.search(r"0x[0-9a-fA-F]{40}", text + TEMPLATES.read_text(encoding="utf-8"))
    assert not re.search(r"0x[0-9a-fA-F]{40}", GOLDEN.read_text(encoding="utf-8"))


def test_a_case_with_no_answer_is_a_refusal_and_says_what_a_wrong_answer_looks_like(cases):
    refusals = [case for case in cases if case["kind"] == "unanswerable"]
    assert len(refusals) == 80
    for case in refusals:
        assert case["answer_type"] == "refusal" and case["expected"] is None
        assert case["reference_sql"] is None and case["accepted"] == []
        assert "wrong answer" in case["notes"].lower(), case["id"]
    # None of the answerable cases is a refusal.
    assert all(c["answer_type"] != "refusal" for c in cases if c["kind"] != "unanswerable")


def test_the_questions_with_no_answer_ask_about_what_the_data_lacks(cases):
    """Spot checks that the near misses are near: each category names its subject."""
    by_family: dict[str, list[str]] = {}
    for case in cases:
        if case["kind"] == "unanswerable":
            by_family.setdefault(case["family"], []).append(case["question"])
    smart = by_family["smart-money"]
    assert all("smart" in q.lower() for q in smart)
    chain = by_family["other-chain"]
    assert all(
        re.search(r"Arbitrum|Base|Polygon|Optimism|BNB|Uniswap v[24]|SushiSwap", q) for q in chain
    )
    outside = by_family["outside-window"]
    for question in outside:
        dates = re.findall(r"\d{4}-\d\d-\d\d|July 2026|August 2026", question)
        assert dates, question
        for date in re.findall(r"\d{4}-\d\d-\d\d", question):
            assert date < "2026-08-09" or date > "2026-09-25", question
    # The pools named in other-pool are not in the pool table.
    labels = set(fixture.read_table("dim_pools").column("pool_label"))
    for question in by_family["other-pool"]:
        assert not any(label in question for label in labels), question


def test_the_tolerances_follow_the_rules_of_v1(cases):
    assert golden.TOLERANCES["quantity"]["abs"] == "0"
    for case in cases:
        tolerance = case["tolerance"]
        if case["answer_type"] != "number":
            assert tolerance is None
            continue
        is_token = case["unit"] in {"WETH", "USDC", "wstETH"}
        if is_token and case["id"].startswith("v2-t-"):
            assert Decimal(tolerance["abs"]) == 0, case["id"]  # a token amount: relative only
        expected = Decimal(case["expected"])
        if expected != 0 and Decimal(tolerance["abs"]) > 0:
            bound = abs(expected) / 1000
            explained = "tolerance" in case["notes"].lower()
            assert Decimal(tolerance["abs"]) <= bound or explained, case["id"]
    # A count is exact.
    for case in cases:
        if case["unit"] in ("swaps", "days", "pools", "pool-days", "round trips"):
            assert case["tolerance"] == {"abs": "0", "rel": "0"}, case["id"]


def test_the_templates_stay_on_complete_days_except_the_edge_families(specs):
    first, last = templates.FIRST_COMPLETE_DAY.isoformat(), templates.LAST_COMPLETE_DAY.isoformat()
    for spec in specs:
        if spec.kind != "template" or spec.family in EDGE_FAMILIES:
            continue
        for day in re.findall(r"\d{4}-\d\d-\d\d", spec.reference_sql):
            assert first <= day <= last, f"{spec.id}: {day}"


def test_the_edge_families_ask_about_partial_and_absent_days(cases):
    facts = templates.Facts()
    absent = {(label, day.isoformat()) for label, day in facts.absent()}
    assert len(absent) == 4
    asked = 0
    for case in cases:
        if case["family"] == "absent-poolday" and case["kind"] == "template":
            label = re.search(r"'([^']+)' AND block_date = '([^']+)'", case["reference_sql"])
            assert (label.group(1), label.group(2)) in absent, case["id"]
            assert case["expected"] == "0", case["id"]  # nothing happened, so 0; not a refusal
            asked += 1
        if case["family"] == "partial-day" and case["kind"] == "template":
            day = re.search(r"block_date = '([^']+)'", case["reference_sql"]).group(1)
            assert day in ("2026-08-09", "2026-09-25"), case["id"]
            assert case["answer_type"] == "number" and Decimal(case["expected"]) > 0
            asked += 1
    assert asked == 20


def test_a_zero_on_a_day_the_data_covers_only_in_part_says_so_in_the_question(cases):
    """No row on the first or the last day means no swap in the part of the day the data
    holds, not on the whole day. Those questions say "as far as the data goes", as the
    partial-day ones do; a zero on a whole day does not need it."""
    edge, whole = 0, 0
    for case in cases:
        if case["family"] != "absent-poolday" or case["kind"] != "template":
            continue
        day = re.search(r"block_date = '([^']+)'", case["reference_sql"]).group(1)
        said = "as far as the data goes" in case["question"]
        if day in ("2026-08-09", "2026-09-25"):
            assert said, case["id"]
            edge += 1
        else:
            assert not said, case["id"]
            whole += 1
        assert "no swap in the part covered" in case["notes"]
        assert "because it had no swap" not in case["notes"]
    assert (edge, whole) == (7, 3)


def test_the_fee_cases_use_the_units_the_question_names(cases):
    units = {c["unit"] for c in cases if c["family"] == "fee-units" and c["kind"] == "template"}
    assert units == {"hundredths of a basis point", "basis points", "percent", "fraction"}
    for case in cases:
        if case["family"] == "fee-units" and case["kind"] == "template":
            if case["unit"] == "hundredths of a basis point":
                assert case["expected"] in {"100", "500", "3000"}
            if case["unit"] == "basis points":
                assert case["expected"] in {"1", "5", "30", "1.0", "5.0", "30.0"}


def test_a_reversed_name_does_not_appear_as_a_label_in_the_data(cases):
    labels = set(fixture.read_table("dim_pools").column("pool_label"))
    reversed_cases = [c for c in cases if c["family"] == "reversed-name"]
    assert len(reversed_cases) == 6
    for case in reversed_cases:
        named = set(re.findall(r"(?:WETH/USDC|USDC/wstETH)(?: \d\.\d+%)?", case["question"]))
        assert named and not named & labels, case["id"]


def test_the_ambiguous_cases_show_their_readings(cases, specs):
    by_id = {spec.id: spec for spec in specs}
    ambiguous = [c for c in cases if c["family"] == "ambiguous"]
    assert len(ambiguous) == 6
    assert all(by_id[c["id"]].accepted_sql for c in ambiguous)
    assert sum(bool(c["accepted"]) for c in ambiguous) >= 5  # most readings give another value


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
    assert ran == 160


def test_regenerating_gives_the_same_bytes(clickhouse):
    count = "SELECT count() FROM system.databases WHERE name LIKE 'test_%'"
    before = clickhouse.query(count).result_rows
    text = golden.generate(clickhouse, TEMPLATES, HAND, SEED, DEV_FRACTION)
    assert text.encode() == GOLDEN.read_bytes()
    assert clickhouse.query(count).result_rows == before  # its database is gone again


def test_every_label_and_date_answer_of_a_template_is_a_unique_maximum(on_fixture, specs):
    asked = 0
    for spec in specs:
        if spec.kind == "template" and spec.answer_type in ("label", "date"):
            assert spec.unique_sql, spec.id
            assert on_fixture.query(spec.unique_sql).result_rows == [(1,)], spec.id
            asked += 1
    assert asked == 10
