"""The normalization context of a page: what the page states, and nothing else (C7)."""

from datetime import UTC, datetime

from snowcrawl.content.context import page_context
from snowcrawl.content.page import ParsedPage
from snowcrawl.normalize.base import Context, Ok
from snowcrawl.normalize.dispatch import normalize
from snowcrawl.schemas.types import FieldSpec, FieldType

FINAL_URL = "https://shop.example.test/p/1?colour=red"
AT = datetime(2026, 10, 1, tzinfo=UTC)


def test_the_context_holds_the_languages_and_urls_the_page_states() -> None:
    page = ParsedPage(
        '<html lang=" de-DE "><head><base href="/shop/">'
        '<meta property="og:locale" content="de_DE">'
        f'<link rel="alternate" hreflang="fr-CH" href="{FINAL_URL}">'
        '<link rel="Alternate x" hreflang="it" href="/p/1?colour=red">'
        '<link rel="alternate" hreflang="fr-CH" href="/fr2/"><link rel="stylesheet" hreflang="en" href="/s.css">'
        '<meta http-equiv="Content-Language" content="de-AT">'
        "</head><body></body></html>"
    )
    headers = (("Content-Type", "text/html"), ("content-language", "de-DE, de-AT"))
    assert page_context(page, FINAL_URL, AT, request_locale="de-CH", headers=headers) == Context(
        html_lang="de-DE",
        og_locale="de_DE",
        hreflang=("fr-CH", "it"),
        content_language=("de-DE", "de-AT"),
        request_locale="de-CH",
        captured_at=AT,
        base_url="https://shop.example.test/shop/",
        page_url=FINAL_URL,
    )


def test_a_dollar_on_a_page_in_one_territory_with_alternates_in_others_is_that_territorys() -> None:
    # The alternates name other pages' languages, so they do not make the page's `$` ambiguous (CLDR en_US: USD).
    page = ParsedPage(
        '<html lang="en-US"><head><link rel="alternate" hreflang="en-AU" href="https://shop.example.test/au/p/1">'
        '<link rel="alternate" hreflang="en-CA" href="https://shop.example.test/ca/p/1"></head></html>'
    )
    ctx = page_context(page, FINAL_URL, AT)
    # Owner decision 2026-10-18: a currency only the locale settles is noted (`basis`), for a lower confidence.
    expected = Ok({"amount": "10", "currency": "USD"}, basis="locale")
    assert normalize("$10", FieldSpec(type=FieldType.MONEY), ctx) == expected
