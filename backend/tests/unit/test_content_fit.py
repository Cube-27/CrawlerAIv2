"""`markdown_fit` (`content.fit`): the page's content pruned of furniture by structure, and kept to the blocks relevant
to a query. Synthetic pages under RFC 2606 names."""

from crawlerai.content import bm25
from crawlerai.content.fit import FitOptions, markdown_fit, prune
from crawlerai.content.md_blocks import parse, render
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


def test_navigation_aside_and_page_header_and_footer_go_but_an_articles_own_header_stays() -> None:
    html = (
        "<html><body><header><p>Site banner</p></header><nav><p>Navigation</p></nav>"
        "<main><header><p>Main header</p></header><article><header><p>Article header</p></header><p>Body</p></article>"
        "</main><aside><p>Related</p></aside><footer><p>Page footer</p></footer></body></html>"
    )
    tree = ParsedPage(html).lxml_tree
    prune(tree)
    assert [p.text for p in tree.iter("p")] == ["Main header", "Article header", "Body"]


def test_aria_landmarks_and_hidden_elements_are_pruned() -> None:
    html = (
        '<html><body><div role="navigation"><p>Landmark navigation prose, long enough to be a paragraph.</p></div>'
        "<div hidden><p>Hidden prose that the page itself does not show, long enough to be a paragraph.</p></div>"
        '<div aria-hidden="true"><p>Decorative prose that screen readers skip, long enough to be a paragraph.</p></div>'
        f'<div role="main"><p>{PROSE}</p></div></body></html>'
    )
    fit = _fit(html)
    assert fit == PROSE


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


def test_code_and_table_cells_are_kept_as_written_even_when_they_repeat() -> None:
    html = (
        "<html><body><div>"
        f"<p>{PROSE}</p>"
        "<table><tr><td>yes</td><td>yes</td></tr><tr><td>no</td><td>yes</td></tr></table>"
        "<pre>x = 1\nx = 1</pre></div></body></html>"
    )
    fit = _fit(html)
    assert "x = 1" in fit
    assert fit.count("yes") == 3


def test_blocks_inside_table_cells_and_code_are_kept_as_written_even_when_they_repeat() -> None:
    html = (
        "<html><body><div>"
        f"<p>{PROSE}</p>"
        "<table><tr><td><p>yes</p></td><td><p>yes</p></td></tr><tr><td><p>no</p></td><td><p>yes</p></td></tr></table>"
        "</div></body></html>"
    )
    fit = _fit(html)
    assert fit.count("yes") == 3


def test_a_heading_whose_section_is_pruned_empty_is_dropped() -> None:
    html = (
        "<html><body><article>"
        f"<p>{PROSE}</p><h2>Overwintering</h2><p>{PROSE} The cluster moves slowly across the comb.</p>"
        '<h2>Elsewhere</h2><div><a href="/a">One</a> <a href="/b">Two</a></div>'
        "</article></body></html>"
    )
    fit = _fit(html)
    assert "## Overwintering" in fit
    assert "Elsewhere" not in fit


def test_a_page_pruning_leaves_nothing_of_is_returned_as_the_plain_markdown() -> None:
    html = f"<html><body><nav><p>{PROSE} {PROSE}</p></nav></body></html>"
    page = ParsedPage(html)
    from crawlerai.content.markdown import markdown

    assert markdown_fit(page, URL) == markdown(page, URL)


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


def test_max_blocks_keeps_the_best_scoring_blocks_in_page_order() -> None:
    fit = _fit(PAGE_ABOUT_BEES, FitOptions(query="the comb honey smoke hive", max_blocks=2))
    blocks = [b.text for b in parse(fit) if b.kind == "text"]
    assert len(blocks) == 2
    assert blocks == sorted(blocks, key=PAGE_TEXT_ORDER.index)


PAGE_TEXT_ORDER = [
    "A smoker calms the colony before the hive is opened, and a little smoke is enough.",
    "Honey is taken in late summer once the combs are capped, leaving stores for winter.",
    "Frames hold the comb and let the beekeeper lift it out without crushing the brood.",
]


def test_a_query_nothing_matches_gives_no_content() -> None:
    assert _fit(PAGE_ABOUT_BEES, FitOptions(query="quantum chromodynamics")) == ""


def test_bm25_scores_a_text_with_a_rarer_query_word_higher() -> None:
    texts = ["bees make honey", "bees make wax", "bees bees bees"]
    scored = bm25.scores("honey", texts)
    assert scored[0] > 0
    assert scored[1:] == [0.0, 0.0]


def test_bm25_ranks_the_shorter_text_first_when_both_hold_the_word_once() -> None:
    scored = bm25.scores("wax", ["wax", "wax and a great many other words that dilute it"])
    assert scored[0] > scored[1] > 0


def test_blocks_render_back_to_the_markdown_they_were_read_from() -> None:
    markdown = (
        "# Title\n\nA paragraph\nover two lines.\n\n- one\n- two\n  - nested\n\n"
        "```python\n# not a heading\n\nx = 1\n```"
        "\n\n| a | b |\n| - | - |\n| 1 | 2 |"
    )
    blocks = parse(markdown)
    assert [b.kind for b in blocks] == ["heading", "text", "list", "list", "code", "text"]
    assert render(blocks) == markdown
