"""Content-format properties (rest-api spec): `links` are absolute canonical http(s) URLs, cleaned `html` runs no
script, and `metadata.language` is `<html lang>`, else `og:locale`, else absent."""

from html import escape
from urllib.parse import urlsplit

from hypothesis import given
from hypothesis import strategies as st
from selectolax.lexbor import LexborHTMLParser

from crawlerai.content.html import cleaned_html, is_javascript_url
from crawlerai.content.links import links
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Ok
from crawlerai.normalize.url import canonical

FINAL_URL = "https://shop.example.test/a/b?c=1"

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
