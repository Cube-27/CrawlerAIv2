"""`markdown_fit` (`content.fit`): the page's content pruned of furniture by structure, and kept to the blocks relevant
to a query. Synthetic pages under RFC 2606 names."""

from crawlerai.content.fit import FitOptions, markdown_fit
from crawlerai.content.page import ParsedPage

URL = "https://site.example.test/guide"
PROSE = "Bees keep a colony through the winter by clustering around the queen and sharing the warmth they make."


def _fit(html: str, options: FitOptions | None = None) -> str:
    return markdown_fit(ParsedPage(html), URL, None, options)


def test_a_menu_of_links_in_a_div_is_pruned_but_prose_with_a_link_is_kept() -> None:
    html = (
        "<html><body><div><h1>Guide</h1>"
        f'<p>{PROSE} See <a href="/more">the colony notes</a> for more.</p>'
        '<div><a href="/a">Shop</a> <a href="/b">Blog</a> <a href="/c">Contact us</a></div>'
        "<p>A second paragraph of prose follows, long enough to be read as content and not as a caption.</p>"
        "</div></body></html>"
    )
    fit = _fit(html)
    assert "the colony notes" in fit
    assert "second paragraph" in fit
    assert "Contact us" not in fit


def test_a_block_that_repeats_on_the_page_is_dropped_everywhere() -> None:
    html = (
        "<html><body><div>"
        f"<p>{PROSE}</p>"
        "<p>Add this beehive to your basket and continue to checkout today.</p>"
        "<p>Another colony fact stated here, once, with enough words to read as an ordinary paragraph.</p>"
        "<p>Add this beehive to your basket and continue to checkout today.</p>"
        "</div></body></html>"
    )
    fit = _fit(html)
    assert "basket" not in fit
    assert "Another colony fact" in fit


PAGE_ABOUT_BEES = (
    "<html><body><article>"
    "<p>Notes from a season in the apiary, written down as the work was done.</p>"
    "<h2>Smoke</h2><p>A smoker calms the colony before the hive is opened, and a little smoke is enough.</p>"
    "<h2>Honey</h2><p>Honey is taken in late summer once the combs are capped, leaving stores for winter.</p>"
    "<h2>Frames</h2><p>Frames hold the comb and let the beekeeper lift it out without crushing the brood.</p>"
    "</article></body></html>"
)


def test_a_query_keeps_the_blocks_that_match_it_and_the_headings_above_them() -> None:
    fit = _fit(PAGE_ABOUT_BEES, FitOptions(query="honey capped combs"))
    assert fit.splitlines()[0] == "## Honey"
    assert "late summer" in fit
    assert "smoker" not in fit
    assert "Frames" not in fit
