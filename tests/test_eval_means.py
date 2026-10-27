"""evalkit.means: guards from per-run means, on small synthetic runs and on the committed ones.

The committed runs are the two comparisons whose one-case guard on a majority failed
(docs/EVALS.md, prompt caching; decision 28). The test asserts what the rule returns for them,
not what anyone would like it to say.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from evalkit import means, runs
from univ3_indexer import config


def run(name, answered_right, answered_refused, refused_due, n_answer=10, n_none=4, **extra):
    """A synthetic results file: cases a0.. have an answer, cases n0.. have none."""
    cases, records = {}, []
    for i in range(n_answer):
        cid = f"a{i}"
        cases[cid] = {"split": "test"}
        refused = i < answered_refused
        right = not refused and i >= answered_refused and i < answered_refused + answered_right
        score = {"should_refuse": False, "refused": refused, "correct": right}
        records.append({"id": cid, "status": "ran", "score": score})
    for i in range(n_none):
        cid = f"n{i}"
        cases[cid] = {"split": "test"}
        refused = i < refused_due
        score = {"should_refuse": True, "refused": refused, "correct": refused}
        records.append({"id": cid, "status": "ran", "score": score})
    base = {"variant": "v", "golden_sha256": "g", "model": "m", "system_prompt_sha256": "p"}
    return name, {**base, "cases": cases, "records": records, **extra}


def side(*counts):
    return [run(f"r{i}.json", *c) for i, c in enumerate(counts)]


def test_a_drop_inside_the_spread_of_the_baseline_holds_even_where_majorities_differ():
    baseline = side((9, 0, 3), (9, 0, 4), (9, 0, 2))  # refusal 3, 4, 2: mean 3, spread 2
    variant = side((9, 0, 2), (9, 0, 2), (9, 0, 2))  # mean 2, each run inside the baseline's
    got = means.compare(baseline, variant)["refusal_recall"]
    assert got["baseline"]["per_run"] == [3, 4, 2] and got["baseline"]["mean"] == 3
    assert got["baseline"]["spread"] == 2 and got["variant"]["spread"] == 0
    assert (got["margin"], got["shortfall"], got["holds"]) == (2, 1, True)


def test_a_real_drop_fails():
    baseline = side((9, 0, 4), (9, 0, 4), (9, 0, 4))
    variant = side((9, 0, 2), (9, 0, 2), (9, 0, 3))
    got = means.compare(baseline, variant)["refusal_recall"]
    assert (got["margin"], round(got["shortfall"], 2), got["holds"]) == (1, 1.67, False)


def test_the_margin_has_a_floor_of_one_case_and_comes_from_the_baseline_alone():
    baseline = side((9, 0, 4), (9, 0, 4))
    wide_variant = side((9, 0, 1), (9, 0, 4))  # its own spread of 3 does not widen the margin
    got = means.compare(baseline, wide_variant)["refusal_recall"]
    assert got["margin"] == 1 and got["variant"]["spread"] == 3 and got["shortfall"] == 1.5
    assert got["holds"] is False
    same = means.compare(baseline, side((9, 0, 3), (9, 0, 4)))["refusal_recall"]
    assert (same["margin"], same["shortfall"], same["holds"]) == (1, 0.5, True)


def test_better_never_fails_and_wrongly_refused_counts_the_other_way():
    baseline = side((6, 2, 4), (6, 2, 4), (6, 2, 4))
    variant = side((9, 0, 4), (9, 0, 4), (9, 0, 4))
    got = means.compare(baseline, variant)
    assert got["right"]["shortfall"] == -3 and got["right"]["holds"]
    assert got["wrongly_refused"]["shortfall"] == -2 and got["wrongly_refused"]["holds"]
    worse = means.compare(variant, baseline)
    assert worse["wrongly_refused"]["shortfall"] == 2 and not worse["wrongly_refused"]["holds"]
    assert worse["right"]["shortfall"] == 3 and not worse["right"]["holds"]


def test_runs_that_are_not_comparable_are_refused():
    ok = side((9, 0, 4), (9, 0, 4))
    partial = run("p.json", 9, 0, 4)
    partial[1]["records"][0] = {**partial[1]["records"][0], "status": "not_run"}
    with pytest.raises(runs.RunsError, match="did not ask every case"):
        means.compare(ok, [partial])
    other = run("o.json", 9, 0, 4)
    other[1]["golden_sha256"] = "h"
    with pytest.raises(runs.RunsError, match="different golden"):
        means.compare(ok, [other])
    with pytest.raises(runs.RunsError, match="no variant runs"):
        means.compare(ok, [])


def load(pattern):
    paths = sorted(glob.glob(str(config.REPO_ROOT / "evals/results" / pattern)))
    return runs.load([Path(p) for p in paths])


def counts(result, measure):
    row = result[measure]
    return row["baseline"]["per_run"], row["variant"]["per_run"], row["margin"], row["holds"]


def test_what_the_rule_says_about_the_cache_runs(capsys):
    baseline = load("2026-10-12_baseline-regrounded_*.json")
    cache = load("2026-10-12_cache_*.json")
    assert len(baseline) == len(cache) == 3
    got = means.compare(baseline, cache, "test")
    with capsys.disabled():
        print("\ncache against the baseline, golden v1, test\n" + means.render(got))
    assert counts(got, "refusal_recall") == ([16, 19, 17], [15, 17, 16], 3, True)
    assert got["refusal_recall"]["shortfall"] == pytest.approx(52 / 3 - 16)
    assert all(row["holds"] for row in got.values())


def test_what_the_rule_says_about_the_coverage_default(capsys):
    zero_day = load("2026-10-20_zero-day_*.json")
    coverage = load("2026-10-20_baseline-coverage_3942*.json")
    assert len(zero_day) == len(coverage) == 3
    got = means.compare(zero_day, coverage, "test")
    with capsys.disabled():
        print("\ncoverage default against zero-day, golden v2, test\n" + means.render(got))
    assert counts(got, "refusal_recall") == ([55, 54, 55], [55, 54, 55], 1, True)
    assert got["refusal_recall"]["shortfall"] == 0
    assert all(row["holds"] for row in got.values())
