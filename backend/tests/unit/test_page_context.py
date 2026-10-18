"""The normalization context of a page (SPEC-04 §4.3, ARCHITECTURE §9): what the page states, and nothing else (C7)."""

from datetime import UTC, datetime

from crawlerai.content.context import page_context
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

FINAL_URL = "https://shop.example.test/p/1?colour=red"
AT = datetime(2026, 10, 1, tzinfo=UTC)


def test_the_context_holds_the_languages_and_urls_the_page_states() -> None:
    page = ParsedPage(
        '<html lang=" de-DE "><head><base href="/shop/">'
        '<meta property="og:locale" content="de_DE">'
        f'<link rel="alternate" hreflang="fr-CH" href="{FINAL_URL}">'
        '<link rel="Alternate x" hreflang="it" href="/p/1?colour=red">'
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


def test_hreflang_counts_only_for_the_alternate_links_to_the_page_itself() -> None:
    # HTML §4.6.7.1, D-1482: an alternate link's hreflang is the language of the page it points to. The page's own
    # (by final URL or canonical link) states this page's language; the others name other pages' languages.
    page = ParsedPage(
        '<html lang="en-US"><head><link rel="canonical" href="https://shop.example.test/p/1">'
        '<link rel="alternate" hreflang="en-US" href="https://shop.example.test/p/1">'
        '<link rel="alternate" hreflang="en-AU" href="https://shop.example.test/au/p/1">'
        '<link rel="alternate" hreflang="x-default" href="/p/1?colour=red">'
        '<link rel="alternate" hreflang="en-NZ" href="https://shop.example.test/nz/p/1"></head></html>'
    )
    assert page_context(page, FINAL_URL, AT).hreflang == ("en-US", "x-default")


def test_a_dollar_on_a_page_in_one_territory_with_alternates_in_others_is_that_territorys() -> None:
    # The alternates name other pages' languages, so they do not make the page's `$` ambiguous (CLDR en_US: USD).
    page = ParsedPage(
        '<html lang="en-US"><head><link rel="alternate" hreflang="en-AU" href="https://shop.example.test/au/p/1">'
        '<link rel="alternate" hreflang="en-CA" href="https://shop.example.test/ca/p/1"></head></html>'
    )
    ctx = page_context(page, FINAL_URL, AT)
    assert normalize("$10", FieldSpec(type=FieldType.MONEY), ctx) == Ok({"amount": "10", "currency": "USD"})
