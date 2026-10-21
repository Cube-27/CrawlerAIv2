"""URL canonicalization (jobs spec): the form `map` and the crawl frontier dedup URLs by, and the form every job
kind keys its `url_task` by, so a page's entity key (extraction spec) does not depend on the job that fetched it.

The url type's canonical form (normalization spec: WHATWG parsing, the RFC 3986 §6.2 normalizations, the fragment
removed), with the query's name-value pairs in the order WHATWG `URLSearchParams.sort()` gives them. No parameter is
dropped or rewritten by name: there is no list of parameter names (C4).

The row keys of one listing page drop its session parameters (`session_parameters`): a parameter that every row link
carries with one same value, and that the page's own URLs do not carry, names the visit, not the item (owner #67). It
is read from the page, never from a list, and only dropped, never invented (C7).
"""

from collections import Counter
from collections.abc import Collection, Iterable
from urllib.parse import unquote_plus

from crawlerai.normalize.url import canonical_url


def canonicalize(url: str, base: str | None = None) -> str | None:
    """`url`, resolved against `base` when relative, in canonical form; `None` when it is not an http(s) URL."""
    canonical = canonical_url(url, base)
    if canonical is None:
        return None
    head, mark, query = canonical.partition("?")
    return f"{head}?{_sorted(query)}" if mark else canonical


def _sorted(query: str) -> str:
    # WHATWG URL Standard, application/x-www-form-urlencoded parsing: the query splits on `&`, and empty sequences
    # are skipped. `sort()` orders the pairs by name, stably, so pairs of one name keep their order.
    return "&".join(sorted((pair for pair in query.split("&") if pair), key=_name))


def _name(pair: str) -> bytes:
    # The name as the form parser decodes it (`+` is a space, then percent-decoding as UTF-8), compared by UTF-16
    # code units as `sort()` compares names. The pair itself keeps the url type's bytes.
    return unquote_plus(pair.partition("=")[0]).encode("utf-16-be")


def session_parameters(row_urls: Collection[str], page_urls: Iterable[str]) -> frozenset[str]:
    """The names of the query parameters that carry no item identity on a listing page: each of two or more row URLs
    carries the parameter once and with one same value, and none of the page's own URLs (`collect.run`'s `page_urls`)
    carries it. One distinct value per row is identity and is kept; a single row shows nothing to compare."""
    if len(row_urls) < 2:
        return frozenset()
    shared: Counter[tuple[str, str]] = Counter()
    for url in row_urls:
        pairs = _pairs(url)
        names = [name for name, _ in pairs]
        shared.update(pair for pair in set(pairs) if names.count(pair[0]) == 1)
    on_page = {name for url in page_urls for name, _ in _pairs(url)}
    return frozenset(name for (name, _), n in shared.items() if n == len(row_urls) and name not in on_page)


def without_parameters(url: str, names: Collection[str]) -> str:
    """`url` with the query pairs named in `names` removed; a query left empty loses its `?`."""
    head, mark, query = url.partition("?")
    if not mark or not names:
        return url
    kept = [pair for pair in query.split("&") if pair and _decoded(pair) not in names]
    return f"{head}?{'&'.join(kept)}" if kept else head


def _pairs(url: str) -> list[tuple[str, str]]:
    """The query's (decoded name, pair as written) list, empty sequences skipped as the form parser skips them."""
    _, mark, query = url.partition("?")
    return [(_decoded(pair), pair) for pair in query.split("&") if pair] if mark else []


def _decoded(pair: str) -> str:
    return unquote_plus(pair.partition("=")[0])
