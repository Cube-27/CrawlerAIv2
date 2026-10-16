"""The page content formats (SPEC-07 §4.5, ARCHITECTURE §8.5): markdown, cleaned html, links and metadata, each
read from the shared `ParsedPage`."""

import re

import pytest
import trafilatura
from lxml import etree

from crawlerai.content.html import cleaned_html, is_javascript_url
from crawlerai.content.links import links
from crawlerai.content.markdown import markdown
from crawlerai.content.metadata import PageMetadata, metadata
from crawlerai.content.page import ParsedPage

FINAL_URL = "https://shop.example.test/catalog/chairs?page=2"

ARTICLE = (
    '<!doctype html><html lang="en"><head><title>Chairs</title></head><body>'
    '<nav><a href="/">Home</a> <a href="/shop">Shop</a></nav>'
    "<article><h1>Folding chairs for small rooms</h1>"
    '<p>A folding chair saves space when it is not in use. This guide compares <a href="/guide/frames">frame'
    " materials</a> and seat widths across common designs.</p>"
    "<p>Steel frames carry more weight, while beech frames are lighter and quieter on wooden floors. Both fold flat"
    " to under five centimetres.</p>"
    '<img src="/img/chair.png" alt="A folded chair">'
    "<p>Seat widths range from forty to fifty centimetres; wider seats need a larger storage gap.</p></article>"
    "<footer>Copyright notice and terms of use.</footer></body></html>"
)


def test_markdown_is_the_main_content_with_its_links_and_images() -> None:
    assert markdown(ParsedPage(ARTICLE), FINAL_URL) == (
        "# Folding chairs for small rooms\n\n"
        "A folding chair saves space when it is not in use. This guide compares"
        " [frame materials](https://shop.example.test/guide/frames) and seat widths across common designs.\n\n"
        "Steel frames carry more weight, while beech frames are lighter and quieter on wooden floors. Both fold flat"
        " to under five centimetres.\n\n"
        "![A folded chair](https://shop.example.test/img/chair.png)\n\n"
        "Seat widths range from forty to fifty centimetres; wider seats need a larger storage gap."
    )


def _tile(i: int) -> str:
    return (
        f'<li class="tile"><a href="/p/{i}"><img src="/i/{i}.jpg" alt="Chair {i} photo"></a>'
        f'<h3><a href="/p/{i}" title="Chair {i}">Chair {i}</a></h3><p class="price">{i}9.90 EUR</p>'
        "<button>Add to basket</button></li>"
    )


LISTING = (
    '<!doctype html><html lang="en"><head><title>Chairs</title></head><body>'
    "<header><nav><ul>"
    + "".join(f'<li><a href="/c/{i}">Section {i}</a></li>' for i in range(6))
    + "</ul></nav></header>"
    "<main><h1>Folding chairs</h1><p>Chairs that fold flat, for rooms where space is short and guests are many.</p>"
    '<ol class="grid">' + "".join(_tile(i) for i in range(1, 13)) + "</ol></main>"
    "<footer>Copyright notice and terms of use.</footer></body></html>"
)


def test_listing_markdown_keeps_every_item_with_its_link_image_and_text() -> None:
    made = markdown(ParsedPage(LISTING), FINAL_URL, page_kind="listing")

    assert made.startswith("# Folding chairs\n\nChairs that fold flat")
    items = [line for line in made.splitlines() if line.startswith("- ")]
    assert items[0] == (
        "- [![Chair 1 photo](https://shop.example.test/i/1.jpg)](https://shop.example.test/p/1)"
        " [Chair 1](https://shop.example.test/p/1) 19.90 EUR"
    )
    assert len(items) == 12
    assert all(f"[Chair {i}](https://shop.example.test/p/{i}) {i}9.90 EUR" in items[i - 1] for i in range(1, 13))
    # Buttons are controls, not content (HTML Standard §4.10.6); the site's navigation is not an item.
    assert "basket" not in made
    assert "Section" not in made


def test_markdown_of_a_page_not_fetched_as_a_listing_is_unchanged() -> None:
    page = ParsedPage(LISTING)
    trafilatura_only = markdown(page, FINAL_URL)

    assert markdown(page, FINAL_URL, page_kind="detail") == trafilatura_only
    assert markdown(ParsedPage(ARTICLE), FINAL_URL, page_kind="listing") == markdown(ParsedPage(ARTICLE), FINAL_URL)


def test_markdown_of_a_page_without_content_is_empty() -> None:
    assert markdown(ParsedPage(""), FINAL_URL) == ""


def test_markdown_leaves_the_shared_lxml_tree_as_parsed() -> None:
    page = ParsedPage(ARTICLE)
    before = etree.tostring(page.lxml_tree)

    markdown(page, FINAL_URL)

    assert etree.tostring(page.lxml_tree) == before


# Main content whose source carries layout whitespace (indented blocks, line breaks and blank-line runs, as templates
# write them), a nested list, a `pre` block whose whitespace is content, and a `<base href>`.
LAYOUT = (
    '<html lang="en"><head><base href="https://cdn.example.test/site/"></head><body><article>'
    "<h1>Notes on folding chairs</h1>"
    "<div>\n        <span>A folding chair saves space when it is not in use, and this note says why.</span>\n"
    "        <span>by <small>A. Writer</small>\n        </span>\n"
    "\n\n\n    </div>"
    "<p>Steel frames carry more weight, while beech frames are lighter and quieter on wooden floors, as the"
    '\n        <a href="about/a-writer">writer</a>\n        explains.</p>'
    "<ul><li>Steel<ul><li>Powder coated</li><li>Chromed</li></ul></li><li>Beech</li></ul>"
    "<pre>fold()\n    lock()</pre>"
    '<p>Seat widths range from forty to fifty centimetres. <img src="img/seat.png" alt="A seat"></p>'
    "</article></body></html>"
)
LIST_ITEM = re.compile(r"\s*(?:[-+*]|\d+[.)])\s")


def _outside_fences(text: str) -> list[str]:
    lines: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            lines.append(line)
    return lines


def test_markdown_targets_resolve_against_the_document_base_url() -> None:
    # HTML Living Standard §2.4.1: `<base href>` sets the base; RFC 3986 §5.2 resolves against it.
    text = markdown(ParsedPage(LAYOUT), FINAL_URL)

    assert "](https://cdn.example.test/site/about/a-writer)" in text
    assert "](https://cdn.example.test/site/img/seat.png)" in text
    assert not re.search(r"\]\((?!https?://)", text)


def test_markdown_drops_layout_whitespace_but_keeps_list_nesting_and_code() -> None:
    text = markdown(ParsedPage(LAYOUT), FINAL_URL)

    # CommonMark §4.4: no line outside code starts a code block by its indentation, unless it nests a list item.
    assert all(not line.startswith("    ") for line in _outside_fences(text) if not LIST_ITEM.match(line))
    # CommonMark §4.9: one blank line separates blocks.
    assert "\n\n\n" not in text
    assert "  - Powder coated" in text
    assert "fold()\n    lock()" in text


def test_html_drops_script_style_noscript_and_template_and_keeps_the_rest() -> None:
    page = ParsedPage(
        "<!doctype html><html><head><style>p{}</style><script>a()</script></head><body>"
        "<p class=x>One<script>b()</script> two</p><noscript><img src=t.gif></noscript>"
        "<template><p>later</p></template><svg><script>c()</script><circle r=1></circle></svg>"
        "<!-- note --><table><tr><td>cell</td></tr></table></body></html>"
    )

    assert cleaned_html(page) == (
        '<!DOCTYPE html><html><head></head><body><p class="x">One two</p>'
        '<svg><circle r="1"></circle></svg><!-- note --><table><tbody><tr><td>cell</td></tr></tbody></table>'
        "</body></html>"
    )


def test_html_drops_event_handlers_and_javascript_urls() -> None:
    page = ParsedPage(
        '<a href="/p" onclick="x()" OnMouseOver="y()" title="t">p</a>'
        '<a href=" JavaScript:go()">q</a><a href="java\tscript:go()">r</a>'
        '<form action="javascript:go()"><button formaction="/send">s</button></form>'
    )

    assert cleaned_html(page) == (
        '<html><head></head><body><a href="/p" title="t">p</a><a>q</a><a>r</a>'
        '<form><button formaction="/send">s</button></form></body></html>'
    )


def test_html_leaves_the_shared_tree_as_parsed() -> None:
    page = ParsedPage("<p onclick=x()>a<script>b()</script></p>")

    cleaned_html(page)

    assert page.tree.html == '<html><head></head><body><p onclick="x()">a<script>b()</script></p></body></html>'


def test_a_javascript_url_is_read_as_the_url_parser_reads_it() -> None:
    assert [is_javascript_url(v) for v in ("\x01 javascript:x", "JAVA\nSCRIPT:x", "/javascript:x", "javascripts:")] == [
        True,
        True,
        False,
        False,
    ]


def test_links_are_absolute_canonical_deduplicated_and_in_document_order() -> None:
    page = ParsedPage(
        '<html><head><link rel="stylesheet" href="/s.css"><link rel="Canonical" href="/catalog/chairs">'
        '<link rel="alternate\tnext" href="?page=3"><link rel="icon prev" href="?page=1"></head><body>'
        '<a href="b">B</a><a href="mailto:a@example.test">mail</a><a href="javascript:x()">js</a>'
        '<a href="HTTPS://SHOP.example.test:443/catalog/b#top">B again</a><a>no href</a>'
        '<a href="//cdn.example.test/x/../y">cdn</a><area href="/map"></body></html>'
    )

    assert links(page, FINAL_URL) == (
        "https://shop.example.test/catalog/chairs",
        "https://shop.example.test/catalog/chairs?page=3",
        "https://shop.example.test/catalog/chairs?page=1",
        "https://shop.example.test/catalog/b",
        "https://cdn.example.test/y",
    )


def test_links_resolve_against_the_first_base_href() -> None:
    page = ParsedPage('<base target=_top><base href="/files/"><base href="/other/"><a href="a.pdf">a</a>')

    assert links(page, FINAL_URL) == ("https://shop.example.test/files/a.pdf",)


METADATA_PAGE = """<!doctype html><html lang=" de-CH "><head>
<title>
  Folding   chair
  oak </title>
<META NAME="Description" content=" A chair that folds. ">
<meta name="description" content="second">
<link rel="canonical" href="/p/1?ref=x#reviews">
<meta property="og:title" content="Folding chair"><meta property="og:image" content="/1.jpg">
<meta property="og:image" content="/2.jpg"><meta name="product:price:amount" content="19.90">
<meta property="twitter:card" content="summary"><meta property="og:locale" content="de_CH">
<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
  {"@type": "Product", "offers": {"@type": ["Offer", "https://schema.org/Demand"]}},
  {"@type": "BreadcrumbList"}]}</script>
<script type="application/ld+json">{not json</script>
<script type="application/json">{"@type": "NotLinkedData"}</script>
</head><body><div itemscope itemtype=" https://schema.org/Product  https://schema.org/IndividualProduct">
<span itemprop="offers" itemscope itemtype="https://schema.org/Offer"></span></div>
<div itemtype="https://schema.org/Place">no itemscope</div></body></html>"""


def test_metadata_reads_what_the_page_states() -> None:
    assert metadata(ParsedPage(METADATA_PAGE), FINAL_URL) == PageMetadata(
        title="Folding chair oak",
        description="A chair that folds.",
        language="de-CH",
        canonical="https://shop.example.test/p/1?ref=x",
        og={
            "og:title": "Folding chair",
            "og:image": "/1.jpg",
            "product:price:amount": "19.90",
            "og:locale": "de_CH",
        },
        structured_data_types=("Product", "Offer", "Demand", "BreadcrumbList", "IndividualProduct"),
    )


def test_metadata_language_falls_back_to_og_locale() -> None:
    page = ParsedPage('<html lang=" "><head><meta property="og:locale" content="fr_FR"></head></html>')

    assert metadata(page, FINAL_URL).language == "fr_FR"


def test_metadata_of_a_page_that_states_nothing_is_empty() -> None:
    assert metadata(ParsedPage("<p>text</p>"), FINAL_URL) == PageMetadata()


def test_structured_data_types_skip_context_term_definitions_and_value_objects() -> None:
    page = ParsedPage(
        '<script type="application/ld+json">{"@context": {"image": {"@type": "@id"}}, "@type": "Product",'
        ' "releaseDate": {"@value": "2020-01-01", "@type": "http://www.w3.org/2001/XMLSchema#date"}}</script>'
    )

    assert metadata(page, FINAL_URL).structured_data_types == ("Product",)


def test_markdown_keeps_a_list_item_s_continuation_inside_the_item(monkeypatch: pytest.MonkeyPatch) -> None:
    # CommonMark §5.2: a paragraph indented to an item's content column, after a blank line, is part of that item; its
    # layout indentation beyond that column is dropped, as it would start a code block (§4.4).
    extracted = (
        "Intro.\n\n"
        "- Steel\n\n  Louder on wooden floors.\n\n"
        "  1.  Chromed\n\n          Rusts less.\n"
        "Lazily continued.\n\n      Still the item.\n\n"
        "Outside the list.\n\n    Not code."
    )
    monkeypatch.setattr(trafilatura, "extract", lambda *_, **__: extracted)

    assert markdown(ParsedPage(ARTICLE), FINAL_URL) == (
        "Intro.\n\n"
        "- Steel\n\n  Louder on wooden floors.\n\n"
        "  1.  Chromed\n\n      Rusts less.\n"
        "Lazily continued.\n\n      Still the item.\n\n"
        "Outside the list.\n\nNot code."
    )
