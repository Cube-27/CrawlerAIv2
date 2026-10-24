"""The `metadata` content format: what the page states about itself.

Each member is `None` (or empty) when the page does not state it; nothing is inferred from the URL or the host (C7).
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from pydantic import ConfigDict, JsonValue, with_config

from snowcrawl.content.dom import document_base_url, strip, tokens
from snowcrawl.content.page import ParsedPage
from snowcrawl.normalize.url import canonical_url

# The Open Graph protocol: `og:` properties, and the `product:` namespace of its `product` object type.
_OG_PREFIXES = ("og:", "product:")
# HTML Living Standard §4.6.2: a link's `type` is the MIME type of the resource it references; without one, or as
# an HTML document (`text/html`, `application/xhtml+xml`, RFC 9110 §8.3.1: before parameters, any case), it is a page.
_DOCUMENT_TYPES = frozenset({"", "text/html", "application/xhtml+xml"})
# RFC 3987 §2.2 and RFC 3986 §3: an IRI's last path segment or its fragment follows the last `/` or `#`.
_IRI_SEPARATOR = re.compile(r"[/#]")


# Every member is in the format, absent ones as None or empty, so the API's document lists them all as required.
@with_config(ConfigDict(json_schema_serialization_defaults_required=True))
@dataclass(frozen=True)
class PageMetadata:
    title: str | None = None
    description: str | None = None
    language: str | None = None
    canonical: str | None = None
    og: dict[str, str] = field(default_factory=dict[str, str])
    structured_data_types: tuple[str, ...] = ()


def metadata(page: ParsedPage, final_url: str) -> PageMetadata:
    """`title` (the first `<title>`), `description` (`meta[name=description]`), `language` (`<html lang>`, else
    `og:locale`), `canonical` (`link[rel=canonical]`, absolute), `og` (every `og:*` and `product:*` property, the
    first value of each) and `structured_data_types` (distinct JSON-LD `@type` values, then microdata `itemtype`
    names, in document order)."""
    og = open_graph(page)
    return PageMetadata(
        title=_title(page),
        description=_meta_name(page, "description"),
        language=strip(html_lang(page)) or strip(og.get("og:locale")),
        canonical=canonical_link(page, final_url),
        og=og,
        structured_data_types=tuple(
            dict.fromkeys(name for name in (*_json_ld_types(page), *_microdata_types(page)) if name)
        ),
    )


def _title(page: ParsedPage) -> str | None:
    # HTML Living Standard §3.1.3: `document.title` strips and collapses ASCII whitespace.
    node = page.tree.css_first("title")
    return (" ".join(tokens(node.text(deep=True))) or None) if node is not None else None


def _meta_name(page: ParsedPage, name: str) -> str | None:
    # HTML Living Standard §4.2.5.1: standard metadata names compare ASCII case-insensitively.
    for node in page.tree.css("meta[name][content]"):
        if (node.attributes.get("name") or "").lower() == name:
            return strip(node.attributes.get("content"))
    return None


def html_lang(page: ParsedPage) -> str | None:
    root = page.tree.root
    return root.attributes.get("lang") if root is not None else None


def open_graph(page: ParsedPage) -> dict[str, str]:
    # The Open Graph protocol: properties are `<meta property=… content=…>`; `name` is read too, as the
    # `meta:` locator does. "The first tag (from top to bottom) is given preference during conflicts."
    og: dict[str, str] = {}
    for node in page.tree.css("meta[content]"):
        key = node.attributes.get("property") or node.attributes.get("name") or ""
        content = node.attributes.get("content")
        if key.startswith(_OG_PREFIXES) and content is not None:
            og.setdefault(key, content)
    return og


def canonical_link(page: ParsedPage, final_url: str) -> str | None:
    """RFC 6596: the target of the page's canonical link relation (`canonical_href`), resolved against the document
    base URL and canonicalized."""
    href = canonical_href(page, final_url)
    return None if href is None else canonical_url(href, document_base_url(page, final_url))


def canonical_href(page: ParsedPage, final_url: str) -> str | None:
    """RFC 6596: the `href` of the page's first readable canonical link as the page writes it. RFC 6596 §3 asks for one
    canonical link per resource; links naming more than one URL designate none, an improper declaration an application
    may ignore, so the page then states no canonical URL."""
    base = document_base_url(page, final_url)
    hrefs = [
        node.attributes.get("href") or ""
        for node in page.tree.css("link[href]")
        if "canonical" in tokens((node.attributes.get("rel") or "").lower())
    ]
    # A target no URL parser reads names nothing.
    read = [(href, url) for href in hrefs if (url := canonical_url(href, base)) is not None]
    return read[0][0] if len({url for _, url in read}) == 1 else None


def language_alternates(page: ParsedPage, final_url: str) -> tuple[tuple[str, str], ...]:
    """HTML Living Standard §4.6.7.1: a `link` whose `rel` has `alternate` and that has an `hreflang` names an alternate
    version of this document in that language (a translation, a regional version): each (language, target resolved
    against the document base URL and canonicalized), in document order; a target no URL parser reads names none.
    A link whose `type` names another format than an HTML document (a feed) is another resource, not a version."""
    base = document_base_url(page, final_url)
    found: list[tuple[str, str]] = []
    for node in page.tree.css("link[hreflang]"):
        language = strip(node.attributes.get("hreflang"))
        if not language or "alternate" not in tokens((node.attributes.get("rel") or "").lower()):
            continue
        if _media_type(node.attributes.get("type")) not in _DOCUMENT_TYPES:
            continue
        if (url := canonical_url(node.attributes.get("href") or "", base)) is not None:
            found.append((language, url))
    return tuple(found)


def _json_ld_types(page: ParsedPage) -> Iterator[str]:
    # JSON-LD 1.1 §9.3: a script of type application/ld+json carries JSON-LD (`ParsedPage.json_ld`); §3.5: `@type` is a
    # string or an array of strings, on any node object, nested ones and `@graph` members included.
    for block in page.json_ld:
        if block.error is None:
            yield from map(_type_name, _type_values(block.document))


def _type_values(document: JsonValue) -> Iterator[str]:
    # A stack, not recursion: a document nested as deep as the JSON parser allows must not exhaust Python's stack.
    # JSON-LD 1.1 §4.1: an `@context` holds term definitions, whose `@type` is a type coercion, not a node's type.
    # §4.2.1: a value object (one with `@value`) types a literal (a datatype), not a node.
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            types = None if "@value" in value else value.get("@type")
            yield from (t for t in (types if isinstance(types, list) else [types]) if isinstance(t, str))
            stack.extend(reversed([member for key, member in value.items() if key != "@context"]))
        elif isinstance(value, list):
            stack.extend(reversed(value))


def _microdata_types(page: ParsedPage) -> Iterator[str]:
    # HTML Living Standard §5.2.2: `itemtype`, on an element with `itemscope`, is a set of space-separated absolute
    # URLs.
    for node in page.tree.css("[itemscope][itemtype]"):
        yield from map(_type_name, tokens(node.attributes.get("itemtype")))


def _type_name(value: str) -> str:
    """A type IRI's name, its last path segment or fragment (`https://schema.org/Product` → `Product`); a JSON-LD
    term (`Product`) is already a name."""
    return _IRI_SEPARATOR.split(value)[-1]


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()
