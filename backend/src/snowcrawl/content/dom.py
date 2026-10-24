"""Document-level facts the content formats share: HTML's token and whitespace rules and the
document base URL."""

import re

from snowcrawl.content.page import ParsedPage
from snowcrawl.normalize.url import canonical_url

# HTML Living Standard §2.3.1: ASCII whitespace is tab, LF, FF, CR and space.
_ASCII_WHITESPACE_CHARS = "\t\n\f\r "
_ASCII_WHITESPACE = re.compile(r"[\t\n\f\r ]+")
# The parts of a class or id: split at `-`, `_` and camelCase boundaries (`apphub_HeaderTop`, `siteHeader`).
_PARTS = re.compile(r"[-_]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def strip(value: str | None) -> str | None:
    """`value` without leading and trailing ASCII whitespace (HTML §2.3.1); `None` when nothing is left."""
    return (value or "").strip(_ASCII_WHITESPACE_CHARS) or None


def tokens(value: str | None) -> list[str]:
    """HTML Living Standard §2.3.2: the tokens of a set of space-separated tokens, in order."""
    return [token for token in _ASCII_WHITESPACE.split(value or "") if token]


def name_parts(name: str) -> list[str]:
    """The lowercased parts of a class, id or other name token (`_PARTS`)."""
    return [part.lower() for part in _PARTS.split(name) if part]


def document_base_url(page: ParsedPage, final_url: str) -> str:
    """HTML Living Standard §2.4.1, document base URL: the `href` of the first `base` element that has one, resolved
    against the document's URL; the document's URL when there is none or it does not parse."""
    base = page.tree.css_first("base[href]")
    href = base.attributes.get("href") if base is not None else None
    return (canonical_url(href, final_url) if href is not None else None) or final_url
