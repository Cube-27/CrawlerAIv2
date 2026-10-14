"""Which discovered URLs a crawl's frontier takes (SPEC-10 §4.5, §6): the request's scope, never past the start URL's
host and its subdomains (D-0037), and where a page's links and next pages come from."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.content.page import ParsedPage
from crawlerai.crawl.frontier import Frontier, discovered
from crawlerai.crawl.rules import Scope

HOST = "shop.example.test"
PAGE = f"https://{HOST}/c/shoes?page=1"


def _frontier(*, include: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> Frontier:
    return Frontier(Scope(HOST, include, exclude), rules=(), max_depth=3, limit=10)


def test_an_include_glob_admits_the_host_and_its_subdomains_only() -> None:
    frontier = _frontier(include=("https://*",))

    assert frontier.admits(f"https://{HOST}/p/1")
    assert frontier.admits(f"https://img.{HOST}/p/1")
    assert not frontier.admits("https://other.example.test/p/1")
    # A host that only ends with the start host's name is not under it (RFC 1034 §3.1: labels, not characters).
    assert not frontier.admits(f"https://not{HOST}/p/1")


def test_without_include_only_the_exact_host_is_admitted() -> None:
    frontier = _frontier()

    assert frontier.admits(f"https://{HOST}/p/1")
    assert not frontier.admits(f"https://img.{HOST}/p/1")


_paths = st.text(alphabet="abcxyz/-", max_size=12)
_hosts = st.sampled_from([HOST, f"img.{HOST}", "other.example.test", f"x{HOST}"])


@given(host=_hosts, path=_paths, include=st.lists(_paths, max_size=3), exclude=st.lists(_paths, max_size=3))
def test_the_frontier_admits_only_what_the_scope_does_on_the_site(
    host: str, path: str, include: list[str], exclude: list[str]
) -> None:
    url = f"https://{host}/{path}"
    globs = (tuple(f"https://*/{glob}*" for glob in include), tuple(f"*/{glob}" for glob in exclude))
    frontier = _frontier(include=globs[0], exclude=globs[1])

    on_site = host == HOST or host.endswith(f".{HOST}")
    assert frontier.admits(url) == (on_site and frontier.scope.admits(url))


def _parsed(body: str) -> ParsedPage:
    return ParsedPage(f"<!doctype html><html><head>{body}</body></html>")


def test_a_page_contributes_its_links_and_next_pages_canonical_and_once() -> None:
    page = _parsed(
        '<link rel="next" href="/c/shoes?page=2"></head><body>'
        '<a href="/p/1#reviews">One</a><a href="/p/1">One again</a><a href="/c/shoes?z=1&a=2">Sorted</a>'
        '<a href="mailto:shop@example.test">Mail</a>'
    )

    assert discovered(page, PAGE) == (
        f"https://{HOST}/c/shoes?page=2",
        f"https://{HOST}/p/1",
        f"https://{HOST}/c/shoes?a=2&z=1",
    )
