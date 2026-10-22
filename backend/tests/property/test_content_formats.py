"""Content-format properties (rest-api spec): `links` are absolute canonical http(s) URLs, cleaned `html` runs no
script, and `metadata.language` is `<html lang>`, else `og:locale`, else absent. Examples pin the markdown of an
article and of a listing, and that two canonical links name none (RFC 6596 §3); all read the shared `ParsedPage`."""

from html import escape
from urllib.parse import urlsplit

from hypothesis import given
from hypothesis import strategies as st
from selectolax.lexbor import LexborHTMLParser

from crawlerai.content.html import cleaned_html, is_javascript_url
from crawlerai.content.links import links
from crawlerai.content.markdown import markdown
from crawlerai.content.metadata import canonical_link
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Ok
from crawlerai.normalize.url import canonical

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

# References a page carries: relative paths, other schemes, scheme-relative and absolute URLs, and arbitrary text.
_reference = st.one_of(
    st.text(max_size=30),
    st.builds(
        "".join,
        st.lists(
            st.sampled_from(
                [
                    "/",
                    "../",
                    "?",
                    "#",
                    "x",
                    "%zz",
                    "//",
                    "javascript:",
                    "mailto:",
                    "HTTP://",
                    "data:",
                    ":8080",
                    "@",
                    "[::1]",
                ]
            ),
            max_size=8,
        ),
    ),
)


@given(st.lists(_reference, max_size=6), st.lists(_reference, max_size=2))
def test_links_are_absolute_canonical_http_urls(hrefs: list[str], bases: list[str]) -> None:
    # An absolute link reads the same against any base, so it is always found, as its canonical form.
    page = ParsedPage(
        "".join(f'<base href="{escape(b)}">' for b in bases)
        + "".join(f'<a href="{escape(h)}">x</a><link rel="next" href="{escape(h)}">' for h in hrefs)
        + '<a href="HTTPS://Shop.Example.TEST:443/known#top">k</a>'
    )

    found = links(page, FINAL_URL)

    assert "https://shop.example.test/known" in found
    assert len(set(found)) == len(found)
    for url in found:
        assert urlsplit(url).scheme in ("http", "https")
        assert urlsplit(url).hostname
        assert canonical(url, None) == Ok(url)


# Markup that runs script, in the spellings and places a parser accepts, among inert markup.
_fragment = st.one_of(
    st.sampled_from(
        [
            "<script>a()</script>",
            "<SCRIPT type=module>b()</SCRIPT>",
            "<svg><script>c()</script></svg>",
            "<scr<script>ipt>d()</script>",
            "<script>",
            "<style>p{}</style>",
            "<noscript><p>n</p></noscript>",
            "<template><script>e()</script></template>",
            '<img src=x onerror="f()">',
            '<a href=" javascript:g()">',
            '<a HREF="JaVa&#x09;ScRiPt:h()">',
            '<iframe srcdoc="<script>i()</script>"></iframe>',
            "<p>",
            "</p>",
            "<div class=x>",
            "</div>",
            "<table><tr><td>",
            "<!-- <script> -->",
            "<math><mi>",
            "<textarea>",
        ]
    ),
    st.text(max_size=10),
)


@given(st.lists(_fragment, max_size=12))
def test_cleaned_html_runs_no_script(fragments: list[str]) -> None:
    # Inert markup before the fragments is kept, so an empty result cannot pass.
    cleaned = cleaned_html(ParsedPage('<p class="kept">inert text</p>' + "".join(fragments)))
    reparsed = LexborHTMLParser(cleaned)

    assert "inert text" in cleaned
    assert reparsed.css("script, style, noscript, template") == []
    for node in reparsed.root.traverse() if reparsed.root is not None else ():
        for name, value in node.attributes.items():
            assert not name.lower().startswith("on")
            assert not is_javascript_url(value or "")


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


def test_markdown_reads_in_recall_mode_what_precision_mode_drops() -> None:
    # trafilatura's precision mode drops a link-dense paragraph; a page whose only content it is still has content.
    page = (
        "<html><body><div><p><a href='/a'>Deep cleansing facial</a> with steam, <a href='/b'>extraction</a> and a"
        " hydrating mask</p></div></body></html>"
    )

    assert markdown(ParsedPage(page), FINAL_URL) == (
        "[Deep cleansing facial](https://shop.example.test/a) with steam,"
        " [extraction](https://shop.example.test/b) and a hydrating mask"
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


def test_canonical_links_naming_two_urls_name_none() -> None:
    # RFC 6596 §3: one canonical link per resource; a page designating two states no preferred URL.
    link = '<link rel="canonical" href="{}">'
    one = link.format("/catalog/chairs") + link.format("https://shop.example.test/catalog/chairs")
    two = link.format("/catalog/chairs?ref=1") + link.format("/catalog/chairs")

    assert canonical_link(ParsedPage(one), FINAL_URL) == "https://shop.example.test/catalog/chairs"
    assert canonical_link(ParsedPage(two), FINAL_URL) is None
