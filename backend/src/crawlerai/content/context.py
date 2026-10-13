"""The normalization context of a captured page (SPEC-04 §4.3, ARCHITECTURE §9): what the page states about its
language and URLs, and when it was fetched.

Only evidence the page or the request states is read (C7): `<html lang>`, `og:locale`, the `hreflang` of alternate
links, the document base URL and the final URL. `page_currencies` and `cctld_territory` are left empty, so a value
that needs them declines rather than guesses.
"""

from datetime import datetime

from crawlerai.content.dom import document_base_url, strip, tokens
from crawlerai.content.metadata import html_lang, open_graph
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context


def page_context(
    page: ParsedPage, final_url: str, captured_at: datetime, *, request_locale: str | None = None
) -> Context:
    return Context(
        html_lang=strip(html_lang(page)),
        og_locale=strip(open_graph(page).get("og:locale")),
        hreflang=hreflang(page),
        request_locale=request_locale,
        captured_at=captured_at,
        base_url=document_base_url(page, final_url),
        page_url=final_url,
    )


def hreflang(page: ParsedPage) -> tuple[str, ...]:
    """HTML Living Standard §4.6.2 and §4.6.7.1: the `hreflang` of each `link` whose `rel` has `alternate`, the
    languages the page says it is also served in; each once, in document order."""
    found: dict[str, None] = {}
    for node in page.tree.css("link[hreflang]"):
        language = strip(node.attributes.get("hreflang"))
        if language and "alternate" in tokens((node.attributes.get("rel") or "").lower()):
            found.setdefault(language)
    return tuple(found)
