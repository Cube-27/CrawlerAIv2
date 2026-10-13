"""robots.txt rules and fetch outcomes (SPEC-02 §4.6, RFC 9309). Synthetic files on RFC 2606 hosts."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

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
        ("https://shop.example.test/", True),
        ("https://shop.example.test/item/1?ref=a", True),
        ("https://shop.example.test/private/", False),
        ("https://shop.example.test/private/x", False),
    ],
)
def test_the_star_group_governs_the_fetcher(url: str, allowed: bool) -> None:
    assert Robots(ROBOTS).allows(url) is allowed


def test_crawl_delay_and_sitemaps_come_from_the_file() -> None:
    robots = Robots(ROBOTS)

    assert robots.crawl_delay == timedelta(seconds=4)
    assert robots.sitemaps == ("https://shop.example.test/sitemap.xml", "https://shop.example.test/sitemap-2.xml")


def test_an_empty_file_allows_everything_and_asks_no_delay() -> None:
    robots = Robots("")

    assert robots.allows("https://shop.example.test/private/x")
    assert (robots.crawl_delay, robots.sitemaps) == (None, ())


def test_a_file_that_disallows_everything_allows_nothing() -> None:
    assert not Robots("User-agent: *\nDisallow: /\n").allows("https://shop.example.test/")


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
    [(404, None), (403, None), (410, None), (301, "too_many_redirects")],
)
def test_an_unavailable_robots_file_allows_everything(status: int, error: str | None) -> None:
    result = _fetched(status, b"<html>nope</html>", error)

    snapshot = snapshot_of(result)

    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (status, "")


@pytest.mark.parametrize(
    ("status", "error"),
    [(500, None), (503, None), (0, "timeout"), (0, "network_error: curl 7"), (200, "body_cap"), (0, "ssrf_rejected")],
)
def test_an_unreachable_robots_file_gives_no_snapshot(status: int, error: str | None) -> None:
    result = _fetched(status, b"", error)

    assert snapshot_of(result) is None
