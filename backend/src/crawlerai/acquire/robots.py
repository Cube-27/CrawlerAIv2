"""robots.txt (acquisition spec, RFC 9309): fetched once per origin per 24 hours, kept in `site.robots_snapshot`, and
read with Protego: RFC 9309 matching (§2.2.2: the longest match wins, `allow` on a tie; §2.2.3: `*` and `$`), plus the
`Crawl-delay` and `Sitemap:` extensions.

Fetches impersonate a browser and announce no product token of their own, so the only group addressed to them is
`*` (RFC 9309 §2.2.1).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from protego import Protego
from pydantic import AwareDatetime, BaseModel, ConfigDict, TypeAdapter, ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import FetchResult
from crawlerai.db.models import Site, SiteId

ROBOTS_TTL: Final = timedelta(hours=24)  # acquisition spec; RFC 9309 §2.4 allows caching for up to 24 hours
PARSE_LIMIT_BYTES: Final = 500 * 1024  # RFC 9309 §2.5: parse at least the first 500 KiB
_USER_AGENT: Final = "*"
_TOO_MANY_REQUESTS: Final = 429  # RFC 6585 §4

Fetch = Callable[[str], Awaitable[FetchResult]]


class RobotsSnapshot(BaseModel):
    """One robots.txt as fetched: the rules in force and when they were fetched. An unavailable robots.txt (RFC 9309
    §2.3.1.3) is kept as an empty body, which allows everything."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fetched_at: AwareDatetime
    status_code: int
    body: str


# What `site.robots_snapshot` holds, as JSON: a snapshot per robots.txt URL (`robots_url`). One site (host) may be
# served on several origins, and each has its own robots.txt (RFC 9309 §2.3: scheme, host and port).
_SNAPSHOTS: Final = TypeAdapter(dict[str, RobotsSnapshot])


class Robots:
    def __init__(self, body: str) -> None:
        self._parser = Protego.parse(body)

    def allows(self, url: str) -> bool:
        return self._parser.can_fetch(url, _USER_AGENT)

    @property
    def crawl_delay(self) -> timedelta | None:
        delay = self._parser.crawl_delay(_USER_AGENT)
        return None if delay is None else timedelta(seconds=delay)

    @property
    def sitemaps(self) -> tuple[str, ...]:
        return tuple(self._parser.sitemaps)


def robots_url(url: str) -> str:
    """The robots.txt that governs `url`: `/robots.txt` at its scheme, host and port (RFC 9309 §2.3)."""
    return at_origin(url, "/robots.txt")


def at_origin(url: str, path: str) -> str:
    """`path` at `url`'s scheme, host and port, without its user information (RFC 3986 §3.2)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def snapshot_of(result: FetchResult) -> RobotsSnapshot | None:
    """The rules a robots.txt fetch yields, or `None` when it was unreachable, which allows nothing (RFC 9309
    §2.3.1.4: a 5xx status or a network error; and a 429, which asks for fewer requests, RFC 6585 §4, rather than
    saying the file is unavailable)."""
    manifest = result.bundle.manifest
    status, error = manifest.status_code, result.attempts[-1].error
    if 200 <= status < 300 and error is None:
        body = result.bundle.body[:PARSE_LIMIT_BYTES].decode("utf-8", errors="replace")  # RFC 9309 §2.3: UTF-8
    # RFC 9309 §2.3.1.3: a 4xx status means unavailable, as do more than five redirects (§2.3.1.2).
    elif (400 <= status < 500 and status != _TOO_MANY_REQUESTS) or error == "too_many_redirects":
        body = ""
    else:
        return None
    return RobotsSnapshot(fetched_at=manifest.fetched_at, status_code=status, body=body)


async def site_robots(
    conn: AsyncConnection, site_id: SiteId, stored: str | None, url: str, fetch: Fetch
) -> Robots | None:
    """The robots rules for `url` on its site, from the snapshot of its origin's robots.txt in the site's `stored`
    snapshots while it is fresh; otherwise fetched and stored beside the site's other fresh snapshots. `None` when
    robots.txt is unreachable; nothing is stored then."""
    now = datetime.now(UTC)
    target = robots_url(url)
    fresh = {
        source: snapshot for source, snapshot in _snapshots(stored).items() if now - snapshot.fetched_at < ROBOTS_TTL
    }
    if (snapshot := fresh.get(target)) is not None:
        return Robots(snapshot.body)
    fetched = snapshot_of(await fetch(target))
    if fetched is None:
        return None
    kept = _SNAPSHOTS.dump_json({**fresh, target: fetched}).decode()
    await conn.execute(update(Site).where(Site.id == site_id).values(robots_snapshot=kept))
    return Robots(fetched.body)


def _snapshots(stored: str | None) -> dict[str, RobotsSnapshot]:
    """The snapshots in `stored`. A value of another shape (a single snapshot, stored before origins were kept apart)
    holds none: its origin is unknown, so it is fetched again."""
    if stored is None:
        return {}
    try:
        return _SNAPSHOTS.validate_json(stored)
    except ValidationError:
        return {}
