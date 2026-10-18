"""Which discovered URLs a request keeps (SPEC-10 §4.4, §6, D-0037): the start URL's exact host unless `include`
says otherwise, `include` globs over the canonical URL, and `exclude`, which wins."""

import pytest

from crawlerai.crawl.rules import PageKindRule, Scope, UrlGlob, located, page_kind_for, url_glob

HOST = "shop.example.test"


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("https://shop.example.test/p/1", True),
        ("http://shop.example.test:8080/p/1", True),
        ("https://sub.shop.example.test/p/1", False),
    ],
)
def test_without_include_the_scope_is_the_exact_host(url: str, kept: bool) -> None:
    assert Scope(HOST).admits(url) is kept


def test_exclude_wins_over_include() -> None:
    scope = Scope(HOST, include=("https://shop.example.test/*",), exclude=("*/private/*",))

    assert not scope.admits("https://shop.example.test/private/1")
    assert not Scope(HOST, exclude=("*?*",)).admits("https://shop.example.test/p?q=1")
    assert scope.admits("https://shop.example.test/public/1")


# Page-kind rules (SPEC-10 §4.5, ARCHITECTURE §13.2).


def test_the_first_rule_whose_pattern_matches_gives_the_page_kind() -> None:
    rules = (
        PageKindRule(pattern="https://shop.example.test/p/sale/*", page_kind="listing"),
        PageKindRule(pattern="https://shop.example.test/p/*", page_kind="detail"),
    )

    assert page_kind_for("https://shop.example.test/p/sale/1", rules) == "listing"
    assert page_kind_for("https://shop.example.test/p/2", rules) == "detail"


# The URL globs of `extract` (SPEC-10 §4.6).


@pytest.mark.parametrize(
    ("pattern", "origin", "canonical"),
    [
        ("https://Shop.Example.test/p/*", "https://shop.example.test/", "https://shop.example.test/p/*"),
        (
            "https://shop.example.test:443/p/*?c=[ab]",
            "https://shop.example.test/",
            "https://shop.example.test/p/*?c=[ab]",
        ),
        ("http://shop.example.test:8080/*", "http://shop.example.test:8080/", "http://shop.example.test:8080/*"),
    ],
)
def test_a_glob_is_expanded_on_its_canonical_origin(pattern: str, origin: str, canonical: str) -> None:
    assert url_glob(pattern) == UrlGlob(origin=origin, pattern=canonical)


@pytest.mark.parametrize(
    ("capture", "expected"),
    [
        # RFC 9110 §15.4: the site's redirect names where the start page is; that URL is taken in canonical form.
        (("http", "HTTPS://www.Example.test/home#top"), "https://www.example.test/home"),
        (("browser", "https://www.example.test/"), "https://www.example.test/"),
        (("http", "https://example.test/en/"), "https://example.test/en/"),
        # Off the start URL's site (a sibling or an unrelated host, D-0672), no capture, or an API recipe's, whose
        # final URL is its endpoint: the start URL.
        (("http", "https://shop.test/"), "https://example.test/"),
        (("http", "https://login.idp.test/"), "https://example.test/"),
        (None, "https://example.test/"),
        (("api", "https://api.example.test/v1/items"), "https://example.test/"),
    ],
)
def test_the_start_page_is_where_its_capture_s_redirects_ended_on_its_site(
    capture: tuple[str, str] | None, expected: str
) -> None:
    assert located("https://example.test/", capture) == expected
