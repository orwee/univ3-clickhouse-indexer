"""The published page, checked as it is committed.

These tests read `docs/index.html` from the repository, never a freshly generated one: what is
served by GitHub Pages is the committed file, so that is what has to hold. No server, no
network, no ClickHouse. Run `make dashboard` after changing the generator or these fail.
"""

import html.parser
import re
import sys

import pytest

from univ3_indexer import config
from univ3_indexer.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import build_dashboard  # noqa: E402

PAGE = REPO_ROOT / "docs" / "index.html"
NOJEKYLL = REPO_ROOT / "docs" / ".nojekyll"
FINDINGS = REPO_ROOT / "docs" / "RECONCILIATION_FINDINGS.md"
RECONCILIATION = config.newest_snapshot("reconciliation.md")

# Void elements never close; everything else must be matched by the parser below.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}  # fmt: skip

# The only places the page is allowed to point at: its own repository, its own Pages site, and
# the author's own site, which the header credits. Anything else would be a link to a third
# party. None of the three is ever *fetched*: what a self-contained page must not do is load a
# resource at view time, and test_nothing_is_fetched_at_view_time is what holds that line.
ALLOWED_HOSTS = (
    "https://github.com/orwee/univ3-clickhouse-indexer",
    "https://orwee.github.io/univ3-clickhouse-indexer",
    "https://robertofajardoduro.com",
)

# Directories .gitignore keeps out of the repository. A link into one of them resolves on the
# machine that built the page and 404s for everybody else.
IGNORED_DIRS = ("reports/", "data/", "cache/", "labels/", "logs/")

MAX_BYTES = 250 * 1024


@pytest.fixture(scope="module")
def page() -> str:
    assert PAGE.exists(), f"{PAGE} is missing: run `make dashboard`"
    return PAGE.read_text(encoding="utf-8")


class StrictParser(html.parser.HTMLParser):
    """Fails on a tag that closes something else, or that is never closed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: list[str] = []
        self.counts: dict[str, int] = {}

    def handle_starttag(self, tag, attrs):
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.counts[tag] = self.counts.get(tag, 0) + 1

    def handle_endtag(self, tag):
        if not self.stack:
            self.problems.append(f"</{tag}> with nothing open")
        elif self.stack[-1] != tag:
            self.problems.append(f"expected </{self.stack[-1]}>, found </{tag}>")
        else:
            self.stack.pop()


def parse(page: str) -> StrictParser:
    parser = StrictParser()
    parser.feed(page)
    parser.close()
    return parser


def test_the_page_exists_and_is_not_empty(page):
    assert len(page) > 10_000, "the page is too small to hold what it claims to"
    assert page.startswith("<!doctype html>")


def test_the_page_is_well_formed_html(page):
    parser = parse(page)
    assert not parser.problems, "\n".join(parser.problems)
    assert not parser.stack, f"never closed: {parser.stack}"
    assert parser.counts["html"] == 1
    for tag in ("div", "section", "svg", "table"):
        assert page.count(f"</{tag}>") == parser.counts[tag], f"unbalanced <{tag}>"


def test_the_page_is_small_enough_to_serve(page):
    size = PAGE.stat().st_size
    assert size <= MAX_BYTES, f"{size:,} bytes is over the {MAX_BYTES:,} budget"


def test_no_address_and_no_hash_anywhere(page):
    """Not one identifier of a third party: no wallet, no transaction, no 0x string at all."""
    assert not re.findall(r"0x[0-9a-fA-F]{40}\b", page), "a 40-hex address is on the page"
    assert not re.findall(r"0x[0-9a-fA-F]{64}\b", page), "a 64-hex hash is on the page"
    loose = re.findall(r"0x[0-9a-fA-F]{8,}", page)
    assert not loose, f"0x-prefixed hex on the page: {loose[:3]}"


def test_no_nansen_identifier_is_republished(page):
    """Only the attribution line and aggregates: no label, no address from their responses."""
    assert "Powered by Nansen API" in page
    for forbidden in ("trader_address", "trader_address_label", "tx_hash", "estimated_value_usd"):
        assert forbidden not in page, f"{forbidden} is on the page"


def test_nothing_is_fetched_at_view_time(page):
    assert "<script" not in page, "the page must not carry or load a script"
    assert not re.search(r'<link[^>]+rel=["\']?stylesheet', page), "no external stylesheet"
    assert "<img" not in page, "charts are SVG markup, never an image"
    assert "@import" not in page and "url(" not in page, "no CSS fetch"
    assert "<iframe" not in page and "<object" not in page and "<embed" not in page


def test_every_link_points_at_github_and_nothing_else(page):
    urls = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', page)
    assert urls, "the page has no links at all, which cannot be right"
    external = [u for u in urls if u.startswith(("http://", "https://", "//"))]
    assert external, "the page should link to the repository"
    bad = [u for u in external if not u.startswith(ALLOWED_HOSTS)]
    assert not bad, f"links outside the repository: {bad}"


def test_every_repository_link_points_at_a_file_that_is_really_there(page):
    """A link into `reports/` used to 404 for every reader: the directory is git-ignored, so
    the file exists only on the machine that generated the page."""
    blob = "https://github.com/orwee/univ3-clickhouse-indexer/blob/main/"
    targets = {
        u[len(blob) :].split("#")[0]
        for u in re.findall(r'href="([^"]+)"', page)
        if u.startswith(blob)
    }
    assert targets, "the page should link into the repository"
    missing = [t for t in sorted(targets) if not (REPO_ROOT / t).exists()]
    assert not missing, f"links to files that do not exist: {missing}"
    ignored = [t for t in sorted(targets) if t.startswith(IGNORED_DIRS)]
    assert not ignored, f"links into git-ignored directories, which 404 on GitHub: {ignored}"


def test_the_kpis_are_the_numbers_the_reports_give(page):
    """The two figures the reconciliation report states, as text, on the page."""
    report = RECONCILIATION.read_text(encoding="utf-8")
    compared = re.search(r"(\d+) compared", report)
    beyond = re.search(r"\*\*(\d+) beyond both thresholds\*\*", report)
    assert compared and beyond, "reports/reconciliation.md changed shape"
    assert f"{compared.group(1)} compared" in page
    assert f"{beyond.group(1)} beyond" in page
    assert "exact, 0 differences" in page, "the internal result must be stated"


def test_the_page_says_when_it_was_generated(page):
    assert re.search(r"Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", page)


def test_every_finding_appears_with_the_state_its_document_gives(page):
    """Parsed from the headings, so the page cannot drift away from the document."""
    headings = re.findall(
        r"^### (\d+)\. (.+?) — (EXPLAINED|PARTLY EXPLAINED|UNEXPLAINED)",
        FINDINGS.read_text(encoding="utf-8"),
        re.M,
    )
    assert len(headings) == 10, f"expected ten findings, the document has {len(headings)}"
    for _number, title, _state in headings:
        assert title in page, f"finding missing from the page: {title}"
    for wanted in ("EXPLAINED", "PARTLY EXPLAINED", "UNEXPLAINED"):
        expected = sum(1 for _, _, s in headings if s == wanted)
        found = len(re.findall(rf'class="st [epu]">{wanted}<', page))
        assert found == expected, f"{wanted}: {found} on the page, {expected} in the document"


def test_every_finding_links_to_its_own_section(page):
    """Each of the ten rows links to its own anchor, in order, and the anchor resolves."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    expected = {
        int(m.group(1)): m.group(2)
        for m in re.finditer(r"\[(\d+)\]\(docs/RECONCILIATION_FINDINGS\.md(#[a-z0-9-]+)\)", readme)
    }
    assert sorted(expected) == list(range(1, 11)), "README.md does not link all ten findings"

    rows = re.findall(
        r"<td>(\d+)</td><td><a href=\"[^\"]*RECONCILIATION_FINDINGS\.md(#[a-z0-9-]+)\"", page
    )
    assert len(rows) == 10, f"the page has {len(rows)} linked findings, not ten"
    assert [int(n) for n, _ in rows] == list(range(1, 11)), "the findings are out of order"
    for number, anchor in rows:
        assert anchor == expected[int(number)], f"finding {number} points at {anchor}"

    headings = re.findall(r"^#+ (.+)$", FINDINGS.read_text(encoding="utf-8"), re.M)
    slugs = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in headings}
    used = set(re.findall(r"RECONCILIATION_FINDINGS\.md#([a-z0-9-]+)\"", page))
    assert used, "the page should link into the findings document"
    assert used <= slugs, f"anchors that are not headings of the document: {used - slugs}"


def test_both_colour_schemes_are_defined(page):
    # Dark is the default here, as it is on the author's site, so the media query the page
    # carries is the one for light. Only this string changed; the check below did not.
    assert "prefers-color-scheme:light" in page.replace(" ", "")
    assert page.count("--s1:") == 2, "each categorical slot needs a light and a dark value"


def test_the_page_scales_on_a_phone(page):
    assert '<meta name="viewport" content="width=device-width,initial-scale=1">' in page
    charts = re.findall(r"<svg [^>]*>", page)
    assert len(charts) >= 6, "the page should carry the charts the sections describe"
    for chart in charts:
        assert "viewBox=" in chart, "a chart without a viewBox cannot scale"
    assert "svg{width:100%;height:auto" in page.replace(" ", "")


def test_the_sections_are_numbered_from_one_and_the_header_is_not_one(page):
    ids = [int(n) for n in re.findall(r'<section id="s(\d+)">', page)]
    chips = [int(n) for n in re.findall(r'<span class="sn">(\d+)</span>', page)]
    assert ids == list(range(1, len(ids) + 1)), f"sections are numbered {ids}"
    assert chips == ids, "the number printed on a section is not the number of its anchor"
    assert "<header" in page and '<span class="sn">' not in page.split("</header>")[0]


def test_no_table_can_grow_past_its_card(page):
    """Every table states its column widths and the page never lets one scroll sideways: that
    is what keeps a table inside its card at 390 px, where a phone reads it."""
    tables = re.findall(r"<table.*?</table>", page, re.S)
    assert tables, "the page has no table at all, which cannot be right"
    for t in tables:
        widths = re.findall(r'<col style="width:(\d+)%">', t)
        columns = len(re.findall(r"<th[ >]", t))
        assert len(widths) == columns, f"a table declares {len(widths)} widths for {columns}"
        assert 97 <= sum(int(w) for w in widths) <= 100, "the widths do not add up to the table"
    flat = page.replace(" ", "").replace("\n", "")
    assert "table{border-collapse:collapse;width:100%;table-layout:fixed" in flat
    assert "overflow-x:auto" not in flat, "a card that scrolls sideways hides what it holds"


def test_the_summary_and_the_closing_block_say_what_they_promise(page):
    """Four takeaways under the header, before the numbers, and a closing block with the three
    ways in and the attribution line."""
    head, _, rest = page.partition("</header>")
    assert head, "no header"
    take = re.search(r'<div class="take"><h2>Key takeaways</h2>.*?</ul></div>', rest, re.S)
    assert take, "the key takeaways are missing"
    assert rest.index(take.group(0)) < rest.index('<section id="s1">'), "takeaways after the KPIs"
    assert len(re.findall(r"<li>", take.group(0))) == 4, "four takeaways, one line each"

    start = re.search(r'<div class="start">.*?</ol></div>', page, re.S)
    assert start, "the closing block is missing"
    assert page.index(start.group(0)) > page.index('<section id="s1">'), "closing block too early"
    for link in ("docs/WALKTHROUGH.md", "DECISIONS.md", "orwee/univ3-clickhouse-indexer"):
        assert link in start.group(0), f"the closing block does not point at {link}"
    assert (
        "Independent project. Smart-money data: Powered by Nansen API. "
        "Not affiliated with any company mentioned." in page
    )


def test_the_spread_between_the_pools_is_one_figure_in_both_places(page):
    """The note under the chart and the summary of the section are generated from the same
    measurement, so the page cannot quote two different spreads for the same pools."""
    said = re.findall(r"about (\d+\.\d+) orders of magnitude", page)
    assert len(said) == 2, f"expected the figure twice, found {said}"
    assert said[0] == said[1], f"two different spreads on the page: {said}"


def test_every_chart_is_described_for_a_reader_who_cannot_see_it(page):
    for chart in re.findall(r"<svg .*?</svg>", page, re.S):
        assert 'role="img"' in chart
        assert "<title>" in chart and "<desc>" in chart


def test_nojekyll_exists_so_pages_serves_underscore_paths(page):
    assert NOJEKYLL.exists(), "docs/.nojekyll is missing"
    assert NOJEKYLL.stat().st_size == 0, "docs/.nojekyll must be empty"


def test_every_section_says_why_it_matters(page):
    """Each section carries both lines: what the picture shows and why it matters to anyone
    who has to trust a number that came off a chain."""
    sections = re.findall(r"<section id=\"s\d+\">.*?</section>", page, re.S)
    assert sections, "no sections on the page"
    for sec in sections:
        number = re.search(r'<span class="sn">(\d+)</span>', sec).group(1)
        assert '<p class="shows"><b>What this shows.</b>' in sec, f"section {number}"
        assert '<p class="why"><b>Why it matters.</b>' in sec, f"section {number}"


def test_the_page_explains_itself_to_someone_who_is_not_in_crypto(page):
    reading = re.search(r'<div class="take"><h2>Reading this page</h2>.*?</div>', page, re.S)
    assert reading, "the reading block is missing"
    for word in ("pool", "swap", "fee tier", "reconcile"):
        assert word in reading.group(0), f"the reading block does not say what a {word} is"
    glossary = re.search(r"<h2>Glossary</h2>.*?</details>", page, re.S)
    assert glossary, "the glossary is missing"
    for term in (
        "MergeTree",
        "Sparse index",
        "Materialized view",
        "FINAL",
        "Round trip",
        "Hold-out",
        "Placebo",
    ):
        assert f"<dt>{term}</dt>" in glossary.group(0), f"the glossary does not define {term}"


def test_the_style_tokens_are_defined_for_both_schemes(page):
    """The palette comes from robertofajardoduro.com and every slot needs a value in each
    scheme: a token that only exists in the dark block is invisible in the light one."""
    dark, _, light = page.partition("@media (prefers-color-scheme:light)")
    assert light, "no light scheme"
    for token in (
        "--plane",
        "--surface",
        "--ink",
        "--ink-2",
        "--muted",
        "--accent",
        "--s1",
        "--s2",
        "--s3",
        "--s4",
        "--good",
        "--critical",
    ):
        assert f"{token}:" in dark, f"{token} is not defined in the dark scheme"
        assert f"{token}:" in light, f"{token} is not defined in the light scheme"
    assert "@font-face" not in page, "a published page must not carry or fetch a font"


def test_the_four_series_are_told_apart_by_more_than_colour(page):
    """Colour-vision deficiency, greyscale printing, a bad projector: the line chart has to
    survive all three, so each line also has its own dash pattern."""
    chart = re.search(r'<svg[^>]*aria-label="Daily USD volume[^"]*".*?</svg>', page, re.S)
    assert chart, "the volume chart is missing"
    lines = re.findall(r'<polyline class="ln" style="([^"]+)"', chart.group(0))
    assert len(lines) == 4, f"{len(lines)} lines, expected four"
    dashes = [re.search(r"stroke-dasharray:([^;\"]+)", s) for s in lines]
    assert sum(1 for d in dashes if d) == 3, "three of the four lines should carry a dash"
    assert len({d.group(1) for d in dashes if d}) == 3, "two lines share a dash pattern"


def test_no_why_it_matters_line_carries_a_file_path(page):
    """The section 5 line once read "Why it matters. sql/reconciliation/17_evidence_hourly.sql
    — re-run against A difference located...": two adjacent string literals in the generator
    had merged the source caption into the prose. A path belongs in the Source line only."""
    for why in re.findall(r'<p class="why"><b>Why it matters.</b>(.*?)</p>', page, re.S):
        assert not re.search(r"\bsql/|\.sql\b|\.md\b|\.py\b", why), why.strip()[:90]


def test_every_source_line_names_a_file_or_a_table(page):
    for src in re.findall(r'<p class="src">Source: <a href="[^"]+">(.*?)</a></p>', page, re.S):
        assert re.search(r"\.(sql|md|csv|py)\b|onchain", src), (
            f"a source caption with no file: {src}"
        )


def test_the_page_uses_the_full_width_and_two_columns_on_a_wide_screen(page):
    """Up to 1600px wide, two columns of sections from 1100px, and grid tracks that cannot
    grow past the screen: minmax(0,1fr), never a bare 1fr, which a long word can stretch."""
    flat = page.replace(" ", "").replace("\n", "")
    assert ".wrap{max-width:1600px" in flat
    assert "@media(min-width:1100px)" in flat
    assert ".grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))" in flat
    tracks = re.findall(r"grid-template-columns:([^;}]+)", flat)
    assert tracks, "no grid at all"
    for t in tracks:
        assert not re.search(r"(?<![,(])1fr", t.replace("minmax(0,1fr)", "")), t
    assert '<main class="grid">' in page and page.count("</main>") == 1


def test_whats_new_is_dated_and_every_line_links_to_what_it_summarises(page):
    new = re.search(
        r'<div class="take new"><h2>What.s new since 21 September</h2>(.*?)</ul>', page, re.S
    )
    assert new, "the What's new block is missing"
    items = re.findall(r"<li>(.*?)</li>", new.group(1), re.S)
    assert 3 <= len(items) <= 5, f"{len(items)} lines; the block is meant to hold three to five"
    for item in items:
        assert re.search(r"<b>\d{4}-\d{2}-\d{2}</b>", item), f"an undated line: {item[:60]}"
        assert re.search(r'<a href="https://github.com/orwee/', item), (
            f"a line with no link: {item[:60]}"
        )
    assert page.index(new.group(0)) < page.index('<section id="s1">')


def test_the_week_two_sections_each_carry_a_chart_and_their_source(page):
    for number, source in ((10, "docs/ROUND_TRIPS.md"), (11, "docs/CROSS_POOL.md"),
                           (12, "receipts_2026-08-19_15h.md")):  # fmt: skip
        sec = re.search(rf'<section id="s{number}">.*?</section>', page, re.S)
        assert sec, f"section {number} is missing"
        assert "<svg " in sec.group(0), f"section {number} has no chart"
        assert source in sec.group(0), f"section {number} does not point at {source}"


def test_every_chart_has_a_phone_drawing_with_the_same_font(page):
    """On a 390 px phone a card leaves about 346 px for a chart (measured in Chromium). Drawn
    680 units wide there, an 18-unit label renders under 9 px; each chart is therefore drawn a
    second time, narrower, and the CSS shows that one on a phone. The font is not touched."""
    wide = re.findall(r'<svg class="wide" viewBox="0 0 (\d+) ', page)
    narrow = re.findall(r'<svg class="narrow" viewBox="0 0 (\d+) ', page)
    assert len(wide) >= 6 and len(wide) == len(narrow), "a chart without its phone drawing"
    assert len(re.findall(r"<svg ", page)) == len(wide) + len(narrow), "a chart drawn once"
    assert set(wide) == {str(build_dashboard.SVG_W)}
    assert set(narrow) == {str(build_dashboard.NARROW_W)}
    assert f"@media (max-width:{build_dashboard.NARROW_MAX_PX}px)" in page
    css = page.replace(" ", "")
    for cls, size in ((".tk", 18), (".lb", 18), (".vl", 17)):
        assert f"{cls}{{fill:" in css and f"font-size:{size}px" in css
        assert size * 346 / build_dashboard.NARROW_W >= 11, f"{cls} under 11 px on a phone"
