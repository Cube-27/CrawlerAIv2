"""The normalization context of a page (SPEC-04 §4.3, ARCHITECTURE §9): what the page states, and nothing else (C7)."""

from datetime import UTC, datetime

from crawlerai.content.context import page_context
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context

FINAL_URL = "https://shop.example.test/p/1?colour=red"
AT = datetime(2026, 10, 1, tzinfo=UTC)


def test_the_context_holds_the_languages_and_urls_the_page_states() -> None:
    page = ParsedPage(
        '<html lang=" de-DE "><head><base href="/shop/">'
        '<meta property="og:locale" content="de_DE">'
        '<link rel="alternate" hreflang="fr-CH" href="/fr/"><link rel="Alternate x" hreflang="it" href="/it/">'
        '<link rel="alternate" hreflang="fr-CH" href="/fr2/"><link rel="stylesheet" hreflang="en" href="/s.css">'
        "</head><body></body></html>"
    )
    assert page_context(page, FINAL_URL, AT, request_locale="de-CH") == Context(
        html_lang="de-DE",
        og_locale="de_DE",
        hreflang=("fr-CH", "it"),
        request_locale="de-CH",
        captured_at=AT,
        base_url="https://shop.example.test/shop/",
        page_url=FINAL_URL,
    )


def test_a_page_that_states_nothing_gives_only_its_urls_and_time() -> None:
    # No currency, territory or language is inferred from the host or the URL (C7).
    assert page_context(ParsedPage("<p>x</p>"), FINAL_URL, AT) == Context(
        captured_at=AT, base_url=FINAL_URL, page_url=FINAL_URL
    )
