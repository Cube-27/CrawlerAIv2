"""robots.txt rules and fetch outcomes (SPEC-02 §4.6, RFC 9309). Synthetic files on RFC 2606 hosts."""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.robots import PARSE_LIMIT_BYTES, Robots, robots_url, snapshot_of
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/robots.txt"

ROBOTS = """\
User-agent: examplebot
Disallow: /

User-agent: *
Disallow: /private/
Allow: /private/open
Crawl-delay: 4
Sitemap: https://shop.example.test/sitemap.xml
Sitemap: https://shop.example.test/sitemap-2.xml
"""


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://shop.example.test/item/1?ref=a", True),
        ("https://shop.example.test/private/x", False),
    ],
)
def test_the_star_group_governs_the_fetcher(url: str, allowed: bool) -> None:
    assert Robots(ROBOTS).allows(url) is allowed


@pytest.mark.parametrize(
    ("rules", "path", "allowed"),
    [
        # RFC 9309 §2.2.2: on a tie between equally long rules, `allow` wins (the general longest match is the
        # property below).
        (["Disallow: /p", "Allow: /p"], "/p", True),
        # RFC 9309 §2.2.3: `*` matches any sequence of characters, `$` ends the pattern.
        (["Disallow: /*.pdf"], "/docs/a.pdf?x=1", False),
        (["Disallow: /*.pdf$"], "/docs/a.pdf?x=1", True),
        (["Disallow: /*.pdf$"], "/docs/a.pdf", False),
        (["Disallow: /a*b"], "/a/x/b/c", False),
        (["Disallow: /a*b"], "/a/x/c", True),
        (["Disallow: /*", "Allow: /*.html$"], "/page.html", True),
        (["Disallow: /*", "Allow: /*.html$"], "/page.htm", False),
        # An empty Disallow disallows nothing.
        (["Disallow:"], "/anything", True),
    ],
)
def test_matching_follows_rfc_9309(rules: list[str], path: str, allowed: bool) -> None:
    body = "\n".join(["User-agent: *", *rules])

    assert Robots(body).allows(f"https://shop.example.test{path}") is allowed


def _longest_match(rules: list[tuple[bool, str]], path: str) -> bool:
    """RFC 9309 §2.2.2 for patterns without wildcards: the longest matching prefix decides, `allow` on a tie."""
    matching = [(len(pattern), allow) for allow, pattern in rules if path.startswith(pattern)]
    return max(matching, default=(0, True))[1]


_PATHS = st.text(alphabet="ab/", max_size=6).map(lambda tail: "/" + tail)


@given(
    rules=st.lists(st.tuples(st.booleans(), _PATHS), min_size=1, max_size=6),
    path=_PATHS,
    order=st.randoms(use_true_random=False),
)
def test_the_longest_match_decides_in_any_rule_order(
    rules: list[tuple[bool, str]], path: str, order: random.Random
) -> None:
    shuffled = rules.copy()
    order.shuffle(shuffled)
    lines = [f"{'Allow' if allow else 'Disallow'}: {pattern}" for allow, pattern in shuffled]

    assert Robots("\n".join(["User-agent: *", *lines])).allows(f"https://shop.example.test{path}") is _longest_match(
        rules, path
    )


def test_crawl_delay_and_sitemaps_come_from_the_file() -> None:
    robots = Robots(ROBOTS)

    assert robots.crawl_delay == timedelta(seconds=4)
    assert robots.sitemaps == ("https://shop.example.test/sitemap.xml", "https://shop.example.test/sitemap-2.xml")


def test_an_empty_file_allows_everything_and_asks_no_delay() -> None:
    robots = Robots("")

    assert robots.allows("https://shop.example.test/private/x")
    assert (robots.crawl_delay, robots.sitemaps) == (None, ())


def _fetched(status: int, body: bytes, error: str | None = None) -> FetchResult:
    block_class: BlockClass = "error" if error else "ok"
    manifest = CaptureManifest(
        capture_id=uuid.UUID("0192f0c8-7b1e-7000-8000-000000000003"),
        url=URL,
        final_url=URL,
        fetched_at=datetime(2026, 10, 13, tzinfo=UTC),
        method="http",
        status_code=status,
        block_class=block_class,
        headers=Headers(request=(), response=()),
        timings_ms={"total": 1},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy=FetchPolicy().model_dump(mode="json"),
        engine_version="test",
    )
    attempt = AttemptRecord(method="http", status=status or None, block_class=block_class, duration_ms=1, error=error)
    bundle = CaptureBundle(manifest=manifest, body=body, network=())
    return FetchResult(bundle=bundle, duration_ms=1, attempts=(attempt,))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://shop.example.test/a/b?q=1#f", "https://shop.example.test/robots.txt"),
        ("http://user:pw@Shop.Example.test:8080/a", "http://shop.example.test:8080/robots.txt"),
        ("https://[2001:db8::1]:8443/a", "https://[2001:db8::1]:8443/robots.txt"),
    ],
)
def test_robots_url_is_at_the_root_of_the_scheme_host_and_port(url: str, expected: str) -> None:
    assert robots_url(url) == expected


def test_a_2xx_robots_file_is_kept() -> None:
    snapshot = snapshot_of(_fetched(200, ROBOTS.encode()))

    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (200, ROBOTS)


def test_only_the_first_500_kib_are_kept() -> None:
    body = b"Disallow: /x\n" * (PARSE_LIMIT_BYTES // 10)

    snapshot = snapshot_of(_fetched(200, body))

    assert snapshot is not None
    assert snapshot.body.encode() == body[:PARSE_LIMIT_BYTES]


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, None), (403, None), (401, None), (301, "too_many_redirects")],
)
def test_an_unavailable_robots_file_allows_everything(status: int, error: str | None) -> None:
    result = _fetched(status, b"<html>nope</html>", error)

    snapshot = snapshot_of(result)

    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (status, "")


@pytest.mark.parametrize(
    ("status", "error"),
    [(500, None), (503, None), (429, None), (0, "timeout"), (200, "body_cap")],
)
def test_an_unreachable_robots_file_gives_no_snapshot(status: int, error: str | None) -> None:
    result = _fetched(status, b"", error)

    assert snapshot_of(result) is None
