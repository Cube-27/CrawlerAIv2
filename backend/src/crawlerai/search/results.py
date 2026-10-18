"""Reading a search provider's answer without knowing the provider (D-1443).

A JSON answer holds its results as the largest array of objects that carry an absolute http(s) URL (RFC 3986 §4.3, RFC
9110 §4.2.1): the first such string of an object is the result's URL, its title the first other string and its snippet
the longest remaining one. An operator whose provider is read wrongly names the members (`Fields`): then each result's
`url`, `title` and `snippet` are those members. An HTML answer holds them as its anchors with an absolute http(s)
`href` (HTML §4.6) resolved against the answering URL (RFC 3986 §5), in document order, the anchor's text the title.
An anchor on the answering host leads to a result only as a redirect: when a query parameter of its URL is an absolute
http(s) URL on another host, that URL is the result; any other anchor on the answering host is the page's own
navigation. Results come in the answer's order, one per canonical URL.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from crawlerai.core import json_text
from crawlerai.normalize.url_key import canonicalize

_SCHEMES = ("http://", "https://")  # RFC 9110 §4.2: the URI schemes a result is fetched over
_MAX_DEPTH = 6  # nesting a result array is looked for at; deeper is not a result list


@dataclass(frozen=True)
class Hit:
    url: str
    title: str
    snippet: str


def _is_url(value: object) -> bool:
    # RFC 3986 §3.1: a scheme is case-insensitive, so `HTTPS://` names an https URL too.
    return isinstance(value, str) and value[:8].lower().startswith(_SCHEMES) and canonicalize(value) is not None


Fields = Mapping[str, str]  # the JSON members that hold a result's "url", "title" and "snippet"


def _named(item: dict[str, object], member: str | None) -> str:
    value = item.get(member) if member is not None else None
    return value.strip() if isinstance(value, str) else ""


def _hit(item: dict[str, object], fields: Fields) -> Hit | None:
    if "url" in fields:
        named = _named(item, fields["url"])
        if not _is_url(named):
            return None
        return Hit(named, _named(item, fields.get("title")), _named(item, fields.get("snippet")))
    strings = [value.strip() for value in item.values() if isinstance(value, str) and value.strip()]
    url = next((value for value in strings if _is_url(value)), None)
    if url is None:
        return None
    others = [value for value in strings if not _is_url(value)]
    title = others[0] if others else ""
    snippet = max(others[1:], key=len, default="")
    return Hit(url, title, snippet)


def _arrays(node: object, depth: int = 0) -> Iterator[list[dict[str, object]]]:
    if depth > _MAX_DEPTH:
        return
    if isinstance(node, list):
        objects = [item for item in node if isinstance(item, dict)]
        if objects:
            yield objects
        for item in node:
            yield from _arrays(item, depth + 1)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _arrays(value, depth + 1)


def from_json(document: object, fields: Fields | None = None) -> list[Hit]:
    """The results of a decoded JSON answer: its array with the most results."""
    best: list[Hit] = []
    for objects in _arrays(document):
        hits = [hit for item in objects if (hit := _hit(item, fields or {})) is not None]
        if len(hits) > len(best):
            best = hits
    return best


def _outbound(href: str, answered_from: str) -> str | None:
    """The result an anchor's `href` leads to from the answering page, or `None` when it is the page's own."""
    url = urljoin(answered_from, href)
    if not _is_url(url):
        return None
    own = urlsplit(answered_from).hostname
    if urlsplit(url).hostname != own:
        return url
    wrapped = (value for _, value in parse_qsl(urlsplit(url).query) if _is_url(value))
    return next((value for value in wrapped if urlsplit(value).hostname != own), None)


def from_html(body: str, answered_from: str) -> list[Hit]:
    """The results of an HTML answer fetched from `answered_from`: its outbound anchors."""
    hits: list[Hit] = []
    for node in LexborHTMLParser(body).css("a[href]"):
        url = _outbound((node.attributes.get("href") or "").strip(), answered_from)
        if url is not None:
            hits.append(Hit(url, " ".join(node.text(separator=" ").split()), ""))
    return hits


def parse(body: bytes, content_charset: str | None, answered_from: str, fields: Fields | None = None) -> list[Hit]:
    """The results of an answer: JSON when `body` decodes as JSON, else HTML; one per canonical URL, in order."""
    text = _decoded(body, content_charset)
    try:
        hits = from_json(json_text.parse(text), fields)
    except ValueError:
        hits = from_html(text, answered_from)
    return unique(hits)


def _decoded(body: bytes, content_charset: str | None) -> str:
    """`body` in its declared charset, or in UTF-8 (the default of RFC 8259 §8.1 and the WHATWG Encoding Standard) when
    it declares none or one Python has no codec for."""
    try:
        return body.decode(content_charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def unique(hits: list[Hit]) -> list[Hit]:
    """`hits` with the URLs canonical and each given once, the first hit that names it kept."""
    seen: dict[str, Hit] = {}
    for hit in hits:
        url = canonicalize(hit.url)
        if url is not None and url not in seen:
            seen[url] = Hit(url, hit.title, hit.snippet)
    return list(seen.values())
