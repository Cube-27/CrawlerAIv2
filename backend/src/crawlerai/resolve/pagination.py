"""Pagination (SPEC-05 §4.12, ARCHITECTURE §8.6): the URLs that may be the next page of a listing, in order.

First the page's `rel=next` links (HTML Living Standard §4.6.7: `next` names the next document of a series). Then the
structural numbered links: a link to the same origin that differs from the page URL only in one integer path segment
or one integer query parameter, whatever its name (C4), and whose integer is the page's plus one. When the page URL
carries no such integer, which number its link would carry is not stated, so no structural link is taken (C7). A
learned config's next-page step is SPEC-08's; infinite scroll is §7.2's.
"""

import re
from dataclasses import dataclass
from urllib.parse import SplitResult, parse_qsl, urlsplit

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate
from crawlerai.content.dom import document_base_url, tokens
from crawlerai.content.page import ParsedPage, node_xpath
from crawlerai.normalize.base import Context
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.types import NEXT_PAGE_FIELD, FieldType, SchemaDef

# A page number: ASCII digits (without re.ASCII, `\d` would also take other scripts' digits).
_INTEGER = re.compile(r"\d+", re.ASCII)


@dataclass(frozen=True, slots=True)
class NextLink:
    """One next-page candidate: its canonical URL, the `href` as written, the XPath of its element, and whether it is
    a `rel=next` link (else a numbered one)."""

    url: str
    href: str
    xpath: str
    rel_next: bool


def next_page_candidates(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The candidates (module docstring), canonical (SPEC-04 §4.4), each once; `final_url` is the capture's."""
    return tuple(link.url for link in next_page_links(page, final_url))


def next_page_links(page: ParsedPage, final_url: str) -> tuple[NextLink, ...]:
    """The candidates with their elements: the first element of each URL, `rel=next` ones first."""
    base_url = document_base_url(page, final_url)
    current = canonical_url(final_url, None)
    rel_next: list[NextLink] = []
    numbered: list[NextLink] = []
    for node in page.tree.css("a[href], link[href]"):
        href = node.attributes.get("href") or ""
        if (url := canonical_url(href, base_url)) is None:
            continue
        # HTML §4.6.1: `rel` is a set of space-separated tokens, compared ASCII case-insensitively.
        if "next" in tokens((node.attributes.get("rel") or "").lower()):
            rel_next.append(NextLink(url, href, node_xpath(node), rel_next=True))
        elif current is not None and _is_next_number(url, current):
            numbered.append(NextLink(url, href, node_xpath(node), rel_next=False))
    first: dict[str, NextLink] = {}
    for link in (*rel_next, *numbered):
        first.setdefault(link.url, link)
    return tuple(first.values())


def next_page_candidate(
    links: tuple[NextLink, ...], schema: SchemaDef, ctx: Context, diagnostics: list[str]
) -> Candidate | None:
    """The first `rel=next` link as the page's `dom` candidate of a listing schema's page-level `next_page_url`
    (D-1226): the page states its next document in HTML's own terms (§4.6.7), so the value is read, not inferred; a
    numbered link is only inferred to be the next page, so it fills no field (C7). Its `href` as written, at its
    element's locator, normalized as a URL against the page; None without such a field or link."""
    spec = schema.fields.get(NEXT_PAGE_FIELD)
    first = next((link for link in links if link.rel_next), None)
    if first is None or spec is None or spec.scope != "page" or spec.type is not FieldType.URL:
        return None
    return candidate(
        NEXT_PAGE_FIELD, spec, PAGE, "dom", first.href, format_locator("dom", first.xpath), ctx, diagnostics
    )


def _is_next_number(url: str, current: str) -> bool:
    link, page = urlsplit(url), urlsplit(current)
    if (link.scheme, link.netloc) != (page.scheme, page.netloc):
        return False
    if link.query == page.query:
        return _one_higher(link.path.split("/"), page.path.split("/"))
    if link.path == page.path:
        return _one_higher_parameter(link, page)
    return False


def _one_higher_parameter(link: SplitResult, page: SplitResult) -> bool:
    link_params = parse_qsl(link.query, keep_blank_values=True)
    page_params = parse_qsl(page.query, keep_blank_values=True)
    names = [name for name, _ in page_params]
    # A repeated name gives no single value to compare.
    if len(set(names)) != len(names) or sorted(name for name, _ in link_params) != sorted(names):
        return False
    link_values = dict(link_params)
    return _one_higher([link_values[name] for name in names], [value for _, value in page_params])


def _one_higher(link: list[str], page: list[str]) -> bool:
    """Whether the two sequences differ in exactly one place, where both hold integers and the link's is one higher."""
    if len(link) != len(page):
        return False
    differing = [(a, b) for a, b in zip(link, page, strict=True) if a != b]
    if len(differing) != 1:
        return False
    a, b = differing[0]
    return bool(_INTEGER.fullmatch(a) and _INTEGER.fullmatch(b)) and int(a) == int(b) + 1
