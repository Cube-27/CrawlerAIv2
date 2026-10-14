"""Which discovered URLs a request keeps (SPEC-10 §4.4, §6, D-0037): the start URL's exact host unless `include`
says otherwise, `include` globs over the canonical URL, and `exclude`, which wins."""

import pytest

from crawlerai.crawl.rules import Scope

HOST = "shop.example.test"


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("https://shop.example.test/p/1", True),
        ("http://shop.example.test:8080/p/1", True),
        ("https://sub.shop.example.test/p/1", False),
        ("https://example.test/p/1", False),
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
