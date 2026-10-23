"""Robots.txt rules and fetch outcomes (RFC 9309). Synthetic files on RFC 2606 hosts."""

import pytest

from crawlerai.acquire.robots import Robots, snapshot_of
from crawlerai.acquire.types import FetchResult
from tests.support.captures import fetched

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
    return fetched(URL, status, body, block_class="error" if error else "ok", error=error)


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, None), (403, None), (401, None), (301, "too_many_redirects")],
)
def test_an_unavailable_robots_file_allows_everything(status: int, error: str | None) -> None:
    result = _fetched(status, b"<html>nope</html>", error)

    snapshot = snapshot_of(result)

    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (status, "")
