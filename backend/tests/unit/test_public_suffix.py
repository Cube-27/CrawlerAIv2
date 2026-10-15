"""Cookie domains against the Public Suffix List (RFC 6265 §5.3 step 5), with a synthetic list of `.test` rules."""

import httpx
import pytest

from crawlerai.acquire import api, public_suffix
from crawlerai.acquire.public_suffix import PublicSuffixes
from crawlerai.acquire.types import FetchPolicy
from tests.unit.test_api_fetch import fetch, json_reply

LIST = """// a synthetic list in the file's format
test
shared.test
*.wild.test
!keep.wild.test

// ===END PRIVATE DOMAINS===
"""
SUFFIXES = PublicSuffixes.parse(LIST)


@pytest.mark.parametrize(
    ("domain", "public"),
    [
        ("test", True),
        ("shared.test", True),
        (".Shared.Test", True),
        ("any.wild.test", True),
        ("keep.wild.test", False),
        ("site.shared.test", False),
        ("wild.test", False),
        ("site.example", False),
        ("example", True),  # a single label, by the list's implicit `*` rule
        ("", False),
    ],
)
def test_a_domain_is_a_public_suffix_by_the_list_s_rules(domain: str, public: bool) -> None:
    assert SUFFIXES.is_public_suffix(domain) is public


def _fetch_with(suffixes: PublicSuffixes | None, set_cookie: str, monkeypatch: pytest.MonkeyPatch) -> str | None:
    """The Cookie header the second hop of a fetch from `api.shared.test` to `cdn.shared.test` carries."""
    monkeypatch.setattr(api, "default_suffixes", lambda: suffixes)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            headers = [("Location", "https://cdn.shared.test/v1/all"), ("Set-Cookie", set_cookie)]
            return httpx.Response(302, headers=headers)
        return json_reply()(request)

    hosts = {host: "93.184.215.14" for host in ("api.shared.test", "cdn.shared.test")}
    fetch(handler, FetchPolicy(), dns=hosts, url="https://api.shared.test/v1/all")
    cookie: str | None = seen[1].headers.get("Cookie")
    return cookie


def test_a_cookie_for_a_public_suffix_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _fetch_with(SUFFIXES, "track=1; Domain=shared.test", monkeypatch) is None


def test_a_cookie_for_a_registrable_domain_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    suffixes = PublicSuffixes.parse("test\n")

    assert _fetch_with(suffixes, "keep=1; Domain=shared.test", monkeypatch) == "keep=1"


def test_without_the_list_the_standard_policy_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _fetch_with(None, "keep=1; Domain=shared.test", monkeypatch) == "keep=1"


def test_a_missing_list_file_is_no_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public_suffix, "engine_dir", lambda _module: None)
    public_suffix.default_suffixes.cache_clear()
    try:
        assert public_suffix.default_suffixes() is None
    finally:
        public_suffix.default_suffixes.cache_clear()
