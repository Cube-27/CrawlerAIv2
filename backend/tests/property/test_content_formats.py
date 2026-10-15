"""Content-format properties (SPEC-07 §6): `links` are absolute canonical http(s) URLs, cleaned `html` runs no
script, and `metadata.language` is `<html lang>`, else `og:locale`, else absent."""

from html import escape
from urllib.parse import urlsplit

from hypothesis import given
from hypothesis import strategies as st
from selectolax.lexbor import LexborHTMLParser

from crawlerai.content.html import cleaned_html, is_javascript_url
from crawlerai.content.links import links
from crawlerai.content.metadata import metadata
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
                    "./",
                    "../",
                    "?",
                    "#",
                    "x",
                    "%2e",
                    "%zz",
                    " ",
                    "\t",
                    "//",
                    "javascript:",
                    "mailto:",
                    "HTTP://",
                    "https://",
                    "data:",
                    "h.example.test",
                    ":8080",
                    "@",
                    "[::1]",
                    "é",
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


_language = st.one_of(
    st.none(), st.sampled_from(["", " ", "\t\n"]), st.from_regex(r"[A-Za-z]{2}([-_][A-Za-z]{2})?", fullmatch=True)
)


@given(_language, _language)
def test_metadata_language_is_html_lang_else_og_locale(lang: str | None, og_locale: str | None) -> None:
    html_attribute = "" if lang is None else f' lang="{lang}"'
    og_meta = "" if og_locale is None else f'<meta property="og:locale" content="{og_locale}">'
    page = ParsedPage(f"<html{html_attribute}><head>{og_meta}</head></html>")

    expected = (lang or "").strip() or (og_locale or "").strip() or None
    assert metadata(page, FINAL_URL).language == expected
