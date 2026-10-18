"""The normalization context of a captured page (schemas spec): what the page states about its
language and URLs, and when it was fetched.

Only evidence the page or the request states is read (C7): `<html lang>`, `og:locale`, the `hreflang` of the alternate
links to the page itself, the document base URL and the final URL. `cctld_territory` is left empty, so a value that
needs it declines rather than guesses. `page_currencies` comes from the page's structured data, which
`collect.currencies` reads (this module sits below the collectors).
"""

from datetime import datetime

from crawlerai.content.dom import document_base_url, strip, tokens
from crawlerai.content.metadata import canonical_link, html_lang, open_graph
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.normalize.url import canonical_url


def page_context(
    page: ParsedPage, final_url: str, captured_at: datetime, *, request_locale: str | None = None
) -> Context:
    return Context(
        html_lang=strip(html_lang(page)),
        og_locale=strip(open_graph(page).get("og:locale")),
        hreflang=hreflang(page, final_url),
        request_locale=request_locale,
        captured_at=captured_at,
        base_url=document_base_url(page, final_url),
        page_url=final_url,
    )


def hreflang(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The languages the page itself states it is in through `hreflang`: HTML Living Standard §4.6.2 and §4.6.7.1, the
    `hreflang` of a `link` whose `rel` has `alternate` names the language of the document that link points to. Only a
    link to the page itself (its final URL or its canonical link, RFC 6596), resolved against the document base URL,
    states this page's language; the others name the languages of other pages (D-1482). Each once, in document order."""
    base = document_base_url(page, final_url)
    own = {url for url in (canonical_url(final_url, None), canonical_link(page, final_url)) if url is not None}
    found: dict[str, None] = {}
    for node in page.tree.css("link[hreflang]"):
        language = strip(node.attributes.get("hreflang"))
        if not language or "alternate" not in tokens((node.attributes.get("rel") or "").lower()):
            continue
        if canonical_url(node.attributes.get("href") or "", base) in own:
            found.setdefault(language)
    return tuple(found)
