"""The project overview, docs/overview.html, checked as it is committed.

The page is written by hand, unlike the dashboard, so these tests hold it to the repository:
every link into the repository resolves, every source it names exists, and the figures it
shows are the ones the files give. No server, no network.
"""

import itertools
import re

import pytest

from tests.test_dashboard import parse
from univ3_indexer.config import REPO_ROOT

PAGE = REPO_ROOT / "docs" / "overview.html"
REPO = "https://github.com/orwee/univ3-clickhouse-indexer"

# Where the page may point: the repository, its Pages site, and the author's own pages.
ALLOWED_HOSTS = (
    REPO,
    "https://orwee.github.io/univ3-clickhouse-indexer",
    "https://robertofajardoduro.com",
    "https://www.linkedin.com/in/roberto-fajardo-duro",
)

RESULTS = "evals/results/"

# A figure on the page, the file it comes from, and the text that file gives for it.
FIGURES = [
    ("1,240,618", "README.md", "1,240,618 swaps in 4 pools over 48 days"),
    ("all 188 pool-days", "README.md", "match on all 188 pool-days"),
    (
        "102 of 110",
        RESULTS + "2026-10-20_baseline_golden_v2_spread.md",
        "Right by majority of the runs: 102.",
    ),
    (
        "110 of 110",
        RESULTS + "2026-10-20_zero-day_golden_v2_spread.md",
        "Right by majority of the runs: 110.",
    ),
    (
        "refused 54 of 60",
        RESULTS + "2026-10-20_baseline-coverage_golden_v2_spread.md",
        "By majority of the runs: 54 of 60",
    ),
    ("0.00189 USD", RESULTS + "2026-10-20_baseline_vs_zero-day.md", "| 0.00189 ("),
    ("15 of 15", "evals/calibration/2026-10-13_agree_model-labels.md", "| 15 of 15 |"),
    ("Between 26 and 33", "docs/EVALS.md", "marked 33, 26 and 31 of 180"),
    ("All 39 flagged", "docs/EVALS.md", "Every one of the 39 was a right answer"),
    ("0.173¢", RESULTS + "2026-10-13_cost.md", "| baseline | 3 | 53 | 0.00173"),
    ("0.114¢", RESULTS + "2026-10-13_cost.md", "| cache | 3 | 53 | 0.00114"),
    ("2.540¢", RESULTS + "2026-10-13_cost.md", "| 1 | 53 | 0.02540"),
    ("17 of 21", "README.md", "**Baseline: 17 of 21"),
    ("8 of 53", RESULTS + "2026-10-13_cost.md", "8 of 53 ended in an error"),
    ("15.3 s against 5.6 s", RESULTS + "2026-10-13_cost.md", "| 15.32 |"),
    ("29 dbt tests", "README.md", "each of the 29 dbt tests"),
    ("28 recorded decisions", "DECISIONS.md", "\n## 28. "),
]


@pytest.fixture(scope="module")
def page() -> str:
    assert PAGE.exists(), f"{PAGE} is missing"
    return PAGE.read_text(encoding="utf-8")


def test_the_page_is_well_formed_html(page):
    assert page.startswith("<!doctype html>")
    parser = parse(page)
    assert not parser.problems, parser.problems
    assert not parser.stack, f"never closed: {parser.stack}"
    assert parser.counts.get("h1") == 1


def test_nothing_is_loaded_from_anywhere(page):
    """One self-contained file: no script, no stylesheet, no font, no image fetched."""
    assert "<script" not in page
    assert "<link" not in page
    assert "@import" not in page and "url(" not in page and "@font-face" not in page
    for tag in ("<iframe", "<object", "<embed", "<img"):
        assert tag not in page, tag
    assert not re.findall(r'\ssrc\s*=\s*"', page)


def test_every_link_points_at_the_project_or_its_author(page):
    urls = re.findall(r'href="([^"]+)"', page)
    external = [u for u in urls if not u.startswith("#")]
    bad = [u for u in external if not u.startswith(ALLOWED_HOSTS)]
    assert not bad, f"links outside the project: {bad}"
    anchors = {u[1:] for u in urls if u.startswith("#")}
    ids = set(re.findall(r'\sid="([^"]+)"', page))
    assert anchors <= ids, f"in-page links to nothing: {anchors - ids}"


def test_every_repository_link_and_every_source_is_a_file_that_is_really_there(page):
    targets = {
        u.split("#")[0]
        for u in re.findall(rf'href="{re.escape(REPO)}/(?:blob|tree)/main/([^"]+)"', page)
    }
    assert len(targets) >= 10, "the page should point into the repository"
    missing = [t for t in sorted(targets) if not (REPO_ROOT / t).exists()]
    assert not missing, f"links to files that do not exist: {missing}"

    captions = re.findall(r'<figcaption class="src">(.*?)</figcaption>', page, re.S)
    assert len(captions) == 3, "every chart names its source"
    for caption in captions:
        for name in re.findall(r">([^<>]+)</a>", caption):
            assert (REPO_ROOT / name).is_file(), f"source {name} does not exist"


@pytest.mark.parametrize("shown, path, said", FIGURES, ids=[f[0] for f in FIGURES])
def test_every_key_figure_is_the_one_its_file_gives(page, shown, path, said):
    assert shown in page, f"the page no longer shows {shown!r}: update FIGURES"
    assert said in (REPO_ROOT / path).read_text(encoding="utf-8"), f"{path} does not say {said!r}"


def test_what_is_opt_in_or_not_adopted_says_so(page):
    """The page must not overstate: the fix is not the default, Airflow and the read-only
    user are opt-in, the judge's labels were written by a model."""
    text = re.sub(r"<[^>]+>", " ", page)
    for said in (
        "Not the default.",
        "opt-in, no day added yet",
        "opt-in on the real server",
        "labels written by a model",
        "not yet checked against a person",
        "one run, not a comparison",
    ):
        assert said in re.sub(r"\s+", " ", text), said


def test_both_colour_schemes_are_defined_and_the_page_scales(page):
    assert "@media (prefers-color-scheme:dark)" in page
    assert ':root[data-theme="dark"]' in page
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in page
    assert "@media (max-width:480px)" in page


def test_headings_never_skip_a_level(page):
    levels = [int(n) for n in re.findall(r"<h([1-6])[\s>]", page)]
    assert levels[0] == 1
    jumps = [(a, b) for a, b in itertools.pairwise(levels) if b > a + 1]
    assert not jumps, f"heading levels skipped: {jumps}"


def test_every_section_is_labelled_by_its_heading(page):
    labelled = re.findall(r'<section[^>]*aria-labelledby="([^"]+)"', page)
    assert len(labelled) == len(re.findall(r"<section", page))
    for label in labelled:
        assert re.search(rf'<h2[^>]*id="{label}"', page), f"{label} is not a heading"


def test_every_drawing_is_hidden_from_screen_readers_or_described(page):
    for svg in re.findall(r"<svg[^>]*>", page):
        assert 'aria-hidden="true"' in svg or "aria-label=" in svg, svg
    for track in re.findall(r'<div class="track"[^>]*>', page):
        assert 'aria-hidden="true"' in track, "a bar's value is in its label; the bar is decoration"


def test_no_em_dash(page):
    assert "—" not in page and "&mdash;" not in page
