"""Content-format properties: `links` are absolute canonical http(s) URLs, cleaned `html` runs no
script, `metadata.language` is `<html lang>`, else `og:locale`, else absent, a wrapper named after furniture that
holds the page's longest block is kept, and so is every slide of a carousel. Examples pin the markdown of an
article, of a page with furniture and of a listing, and that two canonical links name none (RFC 6596 §3); all read
the shared `ParsedPage`."""

from html import escape
from urllib.parse import urlsplit

from hypothesis import given
from hypothesis import strategies as st
from selectolax.lexbor import LexborHTMLParser

from crawlerai.content.fit import markdown_fit
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


def test_markdown_is_the_page_minus_its_furniture() -> None:
    # Landmarks and named furniture go; a wrapper named after furniture that holds the page's title stays.
    page = (
        "<html><body><header><a href='/'>Home</a></header><div class='cookie-consent'>We use cookies.</div>"
        "<div class='drawer modal-wrapper'><h1>Opening hours</h1><p>Open <b>daily</b>from nine.</p>"
        "<ul><li>Mon<ul><li>9-17</li></ul></li></ul><table><tr><th>Day</th><th>Hours</th></tr>"
        "<tr><td>Sat</td><td>10-14</td></tr></table><pre>a  b</pre></div>"
        "<div class='site-footer'>Imprint</div><div hidden>Later</div></body></html>"
    )

    assert markdown(ParsedPage(page), FINAL_URL) == (
        "# Opening hours\n\nOpen **daily**from nine.\n\n- Mon\n  - 9-17\n\n"
        "| Day | Hours |\n| --- | --- |\n| Sat | 10-14 |\n\n```\na  b\n```"
    )


_FURNITURE_WRAPPERS = (
    "div class='has-no-sidebar'",
    "div class='page-with-sidebar'",
    "div class='sidebarContent'",
    "div class='page_menu'",
    "div class='share-panel'",
    "div class='modal'",
    "header class='inner-content'",
)


@given(
    st.sampled_from(_FURNITURE_WRAPPERS),
    st.integers(min_value=12, max_value=40),
    st.lists(st.integers(min_value=1, max_value=11), min_size=1, max_size=6),
)
def test_a_wrapper_named_after_furniture_that_holds_the_longest_block_is_kept(
    wrapper: str, longest: int, others: list[int]
) -> None:
    # Readability: the content is where the longest text runs; a name, or a header's scope, is a weak sign of
    # furniture, measured on what the stated landmarks (here an open cookie dialog with longer text) leave.
    blocks = "".join(f"<p>{'Other words here. ' * n}</p>" for n in others)
    tag = wrapper.split()[0]
    page = (
        f"<html><body><nav>{'Menu entry ' * 5}</nav><dialog open><p>{'Cookie notice. ' * 60}</p></dialog>"
        f"<div>{blocks * 4}</div><{wrapper}><p>{'Long running text. ' * longest}</p></{tag}></body></html>"
    )

    made = markdown(ParsedPage(page), FINAL_URL)

    assert ("Long running text. " * longest).strip() in made
    assert "Menu entry" not in made
    assert "Cookie notice" not in made


def test_a_header_or_footer_in_main_is_the_main_contents_unless_it_holds_navigation() -> None:
    # HTML-AAM §4.1: a `header` or `footer` in `main` is no banner or contentinfo landmark; a page that wraps its whole
    # layout in `main` puts the site's navigation in its own.
    article = (
        "<html><body><header><nav><a href='/'>Home</a></nav></header><main><header><p>Summary of the study.</p>"
        "</header><article><h1>Study</h1><p>Findings.</p></article><footer><p>Cite as: Study, 2026.</p></footer>"
        "</main></body></html>"
    )
    wrapped = (
        "<html><body><main><header><nav><a href='/'>Home</a></nav></header><article><h1>Study</h1>"
        "<p>Findings.</p></article><footer><nav><a href='/imprint'>Imprint</a></nav><p>Street 1, Town.</p></footer>"
        "</main></body></html>"
    )

    assert markdown(ParsedPage(article), FINAL_URL) == (
        "Summary of the study.\n\n# Study\n\nFindings.\n\nCite as: Study, 2026."
    )
    assert markdown(ParsedPage(wrapped), FINAL_URL) == "# Study\n\nFindings."


@given(st.integers(min_value=1, max_value=4), st.sampled_from(["aria-hidden='true'", "hidden"]))
def test_every_slide_of_a_carousel_is_content(shown: int, hiding: str) -> None:
    # WAI-ARIA Authoring Practices, Carousel and Tabs: the panels not shown are hidden, each the page's in its turn.
    slides = "".join(
        f"<div class='slide' {'' if i == shown else hiding}><p>Caption {i}.</p></div>" for i in range(1, 5)
    )
    page = (
        f"<html><body><main><h1>Gallery</h1><div class='slides'>{slides}</div>"
        "<div hidden>Later</div></main></body></html>"
    )

    made = markdown(ParsedPage(page), FINAL_URL)

    assert all(f"Caption {i}." in made for i in range(1, 5))
    assert "Later" not in made


def test_a_page_that_shows_nothing_with_scripts_is_read_without_them() -> None:
    # HTML Standard §4.12.2: a user agent with scripting disabled renders `noscript` content.
    page = (
        "<html><body><nav>" + "Menu entry " * 50 + "</nav><div id='app'></div>"
        "<noscript><p>Posted answer text.</p></noscript></body></html>"
    )

    assert markdown(ParsedPage(page), FINAL_URL) == "Posted answer text."


def _tile(i: int) -> str:
    return (
        f'<li class="tile"><a href="/p/{i}"><img src="/i/{i}.jpg" alt="Chair {i} photo"></a>'
        f'<h3><a href="/p/{i}" title="Chair {i}">Chair {i}</a></h3><p class="price">{i}9.90 EUR</p></li>'
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
    made = markdown(ParsedPage(LISTING), FINAL_URL)

    assert made.startswith("# Folding chairs\n\nChairs that fold flat")
    assert "1. [![Chair 1 photo](https://shop.example.test/i/1.jpg)](https://shop.example.test/p/1)\n" in made
    assert all(f"[Chair {i}](https://shop.example.test/p/{i})\n" in made for i in range(1, 13))
    assert all(f"{i}9.90 EUR" in made for i in range(1, 13))
    assert "Section" not in made
    assert "Copyright" not in made


def test_canonical_links_naming_two_urls_name_none() -> None:
    # RFC 6596 §3: one canonical link per resource; a page designating two states no preferred URL.
    link = '<link rel="canonical" href="{}">'
    one = link.format("/catalog/chairs") + link.format("https://shop.example.test/catalog/chairs")
    two = link.format("/catalog/chairs?ref=1") + link.format("/catalog/chairs")

    assert canonical_link(ParsedPage(one), FINAL_URL) == "https://shop.example.test/catalog/chairs"
    assert canonical_link(ParsedPage(two), FINAL_URL) is None


# Blocks a page's main content is made of: headings, prose, link menus and repeated lines, so pruning can leave a page
# anything from all of its blocks to only its headings.
_block = st.sampled_from(
    [
        "<h2>Winter care</h2>",
        "<h3>Feeding</h3>",
        "<p>A colony clusters around its queen through the winter and shares the warmth it makes.</p>",
        '<div><a href="/a">Shop</a> <a href="/b">Blog</a> <a href="/c">Contact us</a></div>',
        "<p>Add this hive to your basket today.</p>",
        '<p><a href="/more">Read the full notes on hive frames</a></p>',
    ]
)


@given(st.lists(_block, max_size=8))
def test_markdown_fit_is_part_of_markdown_and_empty_only_when_markdown_is(blocks: list[str]) -> None:
    page = ParsedPage(f"<html><body><article>{''.join(blocks)}</article></body></html>")
    full = markdown(page, FINAL_URL)
    fit = markdown_fit(page, FINAL_URL)

    assert all(block in full for block in fit.split("\n\n"))
    assert bool(fit) == bool(full)


@given(st.sampled_from(["aria-expanded", "aria-selected"]), st.sampled_from(["hidden", "style='display:none'"]))
def test_a_collapsed_disclosure_panel_is_content_but_a_popup_is_not(state: str, hiding: str) -> None:
    # WAI-ARIA 1.2 Disclosure and Tabs patterns: a panel a collapsed control names in `aria-controls` is content;
    # HTML Standard §6.1 `hidden="until-found"` too. A popup a control opens, and an unnamed hidden block, are not.
    page = (
        "<html><body><main><h1>Help</h1>"
        f"<p>{'Visible guidance for readers of this page. ' * 12}</p>"
        f"<button {state}='false' aria-controls='a1'>Question</button><div id='a1' {hiding}><p>Answer one.</p></div>"
        "<div hidden='until-found'><p>Answer two.</p></div>"
        "<button aria-expanded='false' aria-haspopup='dialog' aria-controls='m1'>Open</button>"
        "<div id='m1' hidden><p>Modal text.</p></div>"
        "<div hidden='until-found' role='menu'><p>Menu text.</p></div>"
        "<div hidden><button aria-expanded='false' aria-controls='t1'>More</button></div>"
        "<div id='t1' hidden><p>Orphan text.</p></div><div hidden><p>Template text.</p></div></main></body></html>"
    )

    made = markdown(ParsedPage(page), FINAL_URL)

    assert "Answer one." in made
    assert "Answer two." in made
    assert "Modal text." not in made
    assert "Template text." not in made
    assert "Orphan text." not in made
    assert "Menu text." not in made
