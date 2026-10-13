"""`url_state` upkeep for recurring runs (SPEC-11 §4.1, ARCHITECTURE §6, §14): what a URL of a site last answered with,
read before it is fetched again and written after."""

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import FetchResult, Validators
from crawlerai.db.models import SiteId, UrlState
from crawlerai.recurring.conditional import Unchanged, received

__all__ = ["record_fetch", "stored_validators"]

_OK = 200  # RFC 9110 §15.3.1: the response carries the page itself, and its validators describe it


async def stored_validators(conn: AsyncConnection, site_id: SiteId, canonical_url: str) -> Validators | None:
    """The validators to send with the next fetch of the URL; None when it has none stored."""
    query = select(UrlState.etag, UrlState.last_modified).where(*_url(site_id, canonical_url))
    row = (await conn.execute(query)).first()
    if row is None or (row.etag is None and row.last_modified is None):
        return None
    return Validators(etag=row.etag, last_modified=row.last_modified)


async def record_fetch(
    conn: AsyncConnection, site_id: SiteId, canonical_url: str, fetched: FetchResult | Unchanged
) -> None:
    """Record a fetch of the URL (§4.2). `Unchanged` marks it seen, keeping its validators. A 200 over HTTP stores the
    validators it answered with, replacing the ones before, and none where it sent none. Any other result leaves the
    state as it is: only the HTTP rung sends validators, and an API response describes its endpoint, not the page."""
    if isinstance(fetched, Unchanged):
        await conn.execute(update(UrlState).where(*_url(site_id, canonical_url)).values(last_seen_at=func.now()))
        return
    if fetched.method != "http" or fetched.bundle.manifest.status_code != _OK:
        return
    validators = received(fetched)
    values = {"etag": validators.etag, "last_modified": validators.last_modified, "last_seen_at": func.now()}
    insert = pg_insert(UrlState).values(site_id=site_id, canonical_url=canonical_url, **values)
    await conn.execute(
        insert.on_conflict_do_update(index_elements=[UrlState.site_id, UrlState.canonical_url], set_=values)
    )


def _url(site_id: SiteId, canonical_url: str) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (UrlState.site_id == site_id, UrlState.canonical_url == canonical_url)
