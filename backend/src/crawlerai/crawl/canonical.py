"""URL canonicalization (SPEC-10 §4.1): the form `map` and the crawl frontier dedup URLs by, and the form every job
kind keys its `url_task` by, so a page's entity key (SPEC-05 §4.10) does not depend on the job that fetched it.

The url type's canonical form (SPEC-04 §4.4: WHATWG parsing, the RFC 3986 §6.2 normalizations, the fragment
removed), with the query's name-value pairs in the order WHATWG `URLSearchParams.sort()` gives them. No parameter is
dropped or rewritten: there is no list of parameter names (D-0036, C4).
"""

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
