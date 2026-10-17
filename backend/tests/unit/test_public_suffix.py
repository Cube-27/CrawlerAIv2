"""Cookie domains against the Public Suffix List (RFC 6265 §5.3 step 5), with a synthetic list of `.test` rules."""

import httpx
import pytest

from crawlerai.acquire import cookies, public_suffix
from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.public_suffix import PublicSuffixes
from tests.unit.test_api_fetch import PAGE, fetch, json_reply

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


def _fetch_with(
    suffixes: PublicSuffixes,
    set_cookie: str,
    monkeypatch: pytest.MonkeyPatch,
    start: str = "https://api.shared.test/v1/all",
    location: str = "https://cdn.shared.test/v1/all",
) -> str | None:
    """The Cookie header the second hop of a fetch carries: from `start`, which sets `set_cookie`, to `location`."""
    monkeypatch.setattr(cookies, "default_suffixes", lambda: suffixes)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            # As the bytes arrive: a Domain may hold any octets.
            return httpx.Response(302, headers=[(b"Location", location.encode()), (b"Set-Cookie", set_cookie.encode())])
        return json_reply()(request)

    hosts = dict.fromkeys(("shared.test", "api.shared.test", "cdn.shared.test"), "93.184.215.14")
    result = fetch(handler, JsonRequest(url=start, page_url=PAGE), dns=hosts)
    assert result.block_class == "ok"
    cookie: str | None = seen[1].headers.get("Cookie")
    return cookie


@pytest.mark.parametrize(
    ("host", "registrable"),
    [
        ("www.site.shared.test", "site.shared.test"),
        ("site.test", "site.test"),
        ("a.b.any.wild.test", "b.any.wild.test"),
        ("www.keep.wild.test", "keep.wild.test"),
        ("Shop.Example.", "shop.example"),
        ("shared.test", None),
        ("test", None),
    ],
)
def test_the_registrable_domain_is_the_public_suffix_and_one_label(host: str, registrable: str | None) -> None:
    assert SUFFIXES.registrable_domain(host) == registrable


def test_a_cookie_for_a_public_suffix_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _fetch_with(SUFFIXES, "track=1; Domain=shared.test", monkeypatch) is None


def test_a_cookie_for_a_registrable_domain_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    suffixes = PublicSuffixes.parse("test\n")

    assert _fetch_with(suffixes, "keep=1; Domain=shared.test", monkeypatch) == "keep=1"


@pytest.mark.parametrize(
    ("location", "sent"),
    [("https://shared.test/v1/next", "own=1"), ("https://cdn.shared.test/v1/all", None)],
    ids=["same_host", "host_under_it"],
)
def test_a_cookie_for_the_setting_host_that_is_a_public_suffix_is_host_only(
    location: str, sent: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RFC 6265 §5.3 step 5: the Domain equals the setting host, so the cookie is kept for that host alone.
    start = "https://shared.test/v1/all"

    assert _fetch_with(SUFFIXES, "own=1; Domain=shared.test", monkeypatch, start, location) == sent


def test_a_domain_that_is_no_idna_name_ignores_its_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    # An IDNA label holds at most 63 octets (RFC 5890 §2.3.2.1), so this Domain names no host.
    too_long = "é" * 64

    assert _fetch_with(SUFFIXES, f"x=1; Domain={too_long}.shared.test", monkeypatch) is None


def test_without_the_list_a_registrable_domain_keeps_its_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _fetch_with(PublicSuffixes.parse(""), "keep=1; Domain=shared.test", monkeypatch) == "keep=1"


def test_a_missing_list_file_is_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public_suffix, "engine_data_dir", lambda: None)
    public_suffix.default_suffixes.cache_clear()
    try:
        suffixes = public_suffix.default_suffixes()
    finally:
        public_suffix.default_suffixes.cache_clear()

    assert (suffixes.is_public_suffix("shared.test"), suffixes.is_public_suffix("test")) == (False, True)
