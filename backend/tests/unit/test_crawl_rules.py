"""Which discovered URLs a request keeps (SPEC-10 §4.4, §6, D-0037): the start URL's exact host unless `include`
says otherwise, `include` globs over the canonical URL, and `exclude`, which wins."""

import pytest

from crawlerai.crawl.rules import PageKindRule, Scope, UrlGlob, is_glob, page_kind_for, url_glob

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


def test_include_keeps_only_what_it_matches_on_any_host() -> None:
    scope = Scope(HOST, include=("https://shop.example.test/p/*", "https://*.shop.example.test/*"))

    assert scope.admits("https://shop.example.test/p/1/a?x=1")
    assert scope.admits("https://sub.shop.example.test/c/1")
    assert not scope.admits("https://shop.example.test/c/1")


def test_exclude_wins_over_include() -> None:
    scope = Scope(HOST, include=("https://shop.example.test/*",), exclude=("*/private/*",))

    assert not scope.admits("https://shop.example.test/private/1")
    assert not Scope(HOST, exclude=("*?*",)).admits("https://shop.example.test/p?q=1")
    assert scope.admits("https://shop.example.test/public/1")


def test_globs_match_case_sensitively_on_every_platform() -> None:
    # A path is case-sensitive (RFC 3986 §6.2.2.1); `fnmatch.fnmatch` would fold case on Windows.
    assert not Scope(HOST, include=("https://shop.example.test/P/*",)).admits("https://shop.example.test/p/1")


def test_a_glob_character_class_matches_one_character() -> None:
    scope = Scope(HOST, include=("https://shop.example.test/p/[0-9]",))

    assert scope.admits("https://shop.example.test/p/7")
    assert not scope.admits("https://shop.example.test/p/77")


# Page-kind rules (SPEC-10 §4.5, ARCHITECTURE §13.2).


def test_the_first_rule_whose_pattern_matches_gives_the_page_kind() -> None:
    rules = (
        PageKindRule(pattern="https://shop.example.test/p/sale/*", page_kind="listing"),
        PageKindRule(pattern="https://shop.example.test/p/*", page_kind="detail"),
    )

    assert page_kind_for("https://shop.example.test/p/sale/1", rules) == "listing"
    assert page_kind_for("https://shop.example.test/p/2", rules) == "detail"


def test_a_url_no_rule_matches_has_no_page_kind() -> None:
    rules = (PageKindRule(pattern="https://shop.example.test/p/*", page_kind="detail"),)

    assert page_kind_for("https://shop.example.test/c/1", rules) is None
    assert page_kind_for("https://shop.example.test/P/1", rules) is None
    assert page_kind_for("https://shop.example.test/p/1", ()) is None


# The URL globs of `extract` (SPEC-10 §4.6).


@pytest.mark.parametrize(
    ("url", "glob"),
    [
        ("https://shop.example.test/p/*", True),
        ("https://shop.example.test/p/1?size=m", False),
        ("https://[2001:db8::1]/p/1", False),
    ],
)
def test_a_url_is_a_glob_when_it_has_a_star(url: str, glob: bool) -> None:
    assert is_glob(url) is glob


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
    "pattern",
    [
        "https://*.example.test/p/*",
        "ftp://shop.example.test/p/*",
        "/p/*",
    ],
)
def test_a_glob_without_one_literal_http_host_has_no_origin(pattern: str) -> None:
    assert url_glob(pattern) is None


def test_a_glob_matches_the_canonical_urls_of_its_host_only() -> None:
    glob = url_glob("https://SHOP.example.test/p/*")
    assert glob is not None

    assert Scope(HOST, include=(glob.pattern,)).admits("https://shop.example.test/p/1")
    assert not Scope(HOST, include=(glob.pattern,)).admits("https://shop.example.test.other.test/p/1")
