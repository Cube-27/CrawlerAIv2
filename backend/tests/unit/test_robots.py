"""robots.txt rules and fetch outcomes (acquisition spec, RFC 9309). Synthetic files on RFC 2606 hosts."""

import uuid
from datetime import UTC, datetime

import pytest

from crawlerai.acquire.robots import Robots, snapshot_of
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/robots.txt"


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
    ("status", "error"),
    [(404, None), (403, None), (401, None), (301, "too_many_redirects")],
)
def test_an_unavailable_robots_file_allows_everything(status: int, error: str | None) -> None:
    result = _fetched(status, b"<html>nope</html>", error)

    snapshot = snapshot_of(result)

    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (status, "")
