"""Pagination (SPEC-05 §4.12, ARCHITECTURE §8.6): the URLs that may be the next page of a listing, in order.

First the page's `rel=next` links (HTML Living Standard §4.6.7: `next` names the next document of a series). Then the
structural numbered links: a link to the same origin that differs from the page URL only in one integer path segment
or one integer query parameter, whatever its name (C4), and whose integer is the page's plus one. When the page URL
carries no such integer, which number its link would carry is not stated, so no structural link is taken (C7). A
learned config's next-page step is SPEC-08's; infinite scroll is §7.2's.
"""

import re
from collections.abc import Iterator
from urllib.parse import SplitResult, parse_qsl, urlsplit

from crawlerai.content.dom import document_base_url, tokens
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.url import canonical_url

# A page number: ASCII digits (str.isdigit would also take other scripts' digits).
_INTEGER = re.compile(r"[0-9]+")


def next_page_candidates(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The candidates (module docstring), canonical (SPEC-04 §4.4), each once; `final_url` is the capture's."""
    base_url = document_base_url(page, final_url)
    current = canonical_url(final_url, None)
    links = [(url, rel) for href, rel in _references(page) if (url := canonical_url(href, base_url)) is not None]
    rel_next = [url for url, rel in links if "next" in rel]
    numbered = [url for url, _ in links if current is not None and _is_next_number(url, current)]
    return tuple(dict.fromkeys((*rel_next, *numbered)))


def _references(page: ParsedPage) -> Iterator[tuple[str, frozenset[str]]]:
    for node in page.tree.css("a[href], link[href]"):
        # HTML §4.6.1: `rel` is a set of space-separated tokens, compared ASCII case-insensitively.
        yield node.attributes.get("href") or "", frozenset(tokens((node.attributes.get("rel") or "").lower()))


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
