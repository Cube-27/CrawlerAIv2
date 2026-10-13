"""robots.txt (SPEC-02 §4.6, RFC 9309): fetched once per site per 24 hours, kept in `site.robots_snapshot`, and read
with `urllib.robotparser`'s semantics, `Crawl-delay` and `Sitemap:` included.

Fetches impersonate a browser and announce no product token of their own, so the only group addressed to them is
`*` (RFC 9309 §2.2.1).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import FetchResult
from crawlerai.db.models import Site, SiteId

ROBOTS_TTL: Final = timedelta(hours=24)  # SPEC-02 §4.6; RFC 9309 §2.4 allows caching for up to 24 hours
PARSE_LIMIT_BYTES: Final = 500 * 1024  # RFC 9309 §2.5: parse at least the first 500 KiB
_USER_AGENT: Final = "*"

Fetch = Callable[[str], Awaitable[FetchResult]]


class RobotsSnapshot(BaseModel):
    """What `site.robots_snapshot` holds, as JSON: the rules in force and when they were fetched. An unavailable
    robots.txt (RFC 9309 §2.3.1.3) is kept as an empty body, which allows everything."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fetched_at: AwareDatetime
    status_code: int
    body: str


class Robots:
    def __init__(self, body: str) -> None:
        self._parser = RobotFileParser()
        self._parser.parse(body.splitlines())

    def allows(self, url: str) -> bool:
        return self._parser.can_fetch(_USER_AGENT, url)

    @property
    def crawl_delay(self) -> timedelta | None:
        delay = self._parser.crawl_delay(_USER_AGENT)
        return None if delay is None else timedelta(seconds=float(delay))

    @property
    def sitemaps(self) -> tuple[str, ...]:
        return tuple(self._parser.site_maps() or ())


def robots_url(url: str) -> str:
    """The robots.txt that governs `url`: `/robots.txt` at its scheme, host and port (RFC 9309 §2.3)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, "/robots.txt", "", ""))


def snapshot_of(result: FetchResult) -> RobotsSnapshot | None:
    """The rules a robots.txt fetch yields, or `None` when it was unreachable, which allows nothing (RFC 9309
    §2.3.1.4: a 5xx status or a network error)."""
    manifest = result.bundle.manifest
    status, error = manifest.status_code, result.attempts[-1].error
    if 200 <= status < 300 and error is None:
        body = result.bundle.body[:PARSE_LIMIT_BYTES].decode("utf-8", errors="replace")  # RFC 9309 §2.3: UTF-8
    # RFC 9309 §2.3.1.3: a 4xx status means unavailable, as do more than five redirects (§2.3.1.2).
    elif 400 <= status < 500 or error == "too_many_redirects":
        body = ""
    else:
        return None
    return RobotsSnapshot(fetched_at=manifest.fetched_at, status_code=status, body=body)


async def site_robots(conn: AsyncConnection, site_id: SiteId, url: str, fetch: Fetch) -> Robots | None:
    """The robots rules for `url` on its site, from the site's snapshot while it is fresh; otherwise fetched and
    stored as the new snapshot. `None` when robots.txt is unreachable; nothing is stored then."""
    stored = (await conn.execute(select(Site.robots_snapshot).where(Site.id == site_id))).scalar_one()
    if stored is not None:
        snapshot = RobotsSnapshot.model_validate_json(stored)
        if datetime.now(UTC) - snapshot.fetched_at < ROBOTS_TTL:
            return Robots(snapshot.body)
    fetched = snapshot_of(await fetch(robots_url(url)))
    if fetched is None:
        return None
    await conn.execute(update(Site).where(Site.id == site_id).values(robots_snapshot=fetched.model_dump_json()))
    return Robots(fetched.body)
