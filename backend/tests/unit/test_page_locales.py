"""The one page-locale derivation: the page's own declarations count together;
the request's locale only when the page declares none, and only for a reader that takes it."""

from datetime import UTC, datetime

import pytest

from snowcrawl.normalize import locales
from snowcrawl.normalize.base import Context

AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("declared", "with_request", "page_only"),
    [
        ({}, (), ()),
        ({"request_locale": "de-CH"}, ("de-CH",), ()),
        ({"html_lang": "fr-CA", "request_locale": "de-CH"}, ("fr-CA",), ("fr-CA",)),
        (
            {"html_lang": "en", "og_locale": "en_GB", "in_language": ("es",), "content_language": ("pt-BR",)},
            ("en", "en_GB", "es", "pt-BR"),
            ("en", "en_GB", "es", "pt-BR"),
        ),
        ({"hreflang": ("x-default", "it"), "request_locale": "de"}, ("it",), ("it",)),
        ({"html_lang": " ", "content_language": ("und", "x-private")}, (), ()),
        ({"html_lang": "en-US", "content_language": ("en-US",)}, ("en-US",), ("en-US",)),
    ],
)
def test_the_page_declarations_come_before_the_request_locale(
    declared: dict[str, object], with_request: tuple[str, ...], page_only: tuple[str, ...]
) -> None:
    ctx = Context(captured_at=AT, **declared)  # type: ignore[arg-type]

    assert locales.page_locales(ctx, request=True) == with_request
    assert locales.page_locales(ctx, request=False) == page_only
    assert locales.page_languages(ctx, request=True) == {locales.primary_language(t) for t in with_request}
