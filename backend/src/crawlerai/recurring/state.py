"""`url_state` upkeep for records tasks (jobs spec): the content fingerprint of the page a URL of a site last
answered with, so a fresh extraction can say whether the page's content changed since."""

import logging
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import SiteId, UrlState
from crawlerai.recurring.simhash import BITS, ContentFingerprint, hamming

__all__ = ["record_content"]

log = logging.getLogger(__name__)


async def record_content(
    conn: AsyncConnection, site_id: SiteId, canonical_url: str, fingerprint: ContentFingerprint
) -> bool:
    """Whether the page's content changed (§4.3): its digest differs from the stored one, or none is stored. A change
    stores the new fingerprint and sets `last_changed_at`, and logs how many SimHash bits it moved."""
    query = select(UrlState.content_digest, UrlState.content_fingerprint).where(*_url(site_id, canonical_url))
    stored = (await conn.execute(query)).first()
    if stored is not None and stored.content_digest == fingerprint.digest:
        return False
    if stored is not None and stored.content_fingerprint is not None:
        moved = hamming(int(stored.content_fingerprint, 16), fingerprint.simhash)
        # No URL in the line: a deployment may redact URLs from what it logs (`log_redact_urls`).
        log.info("content changed: SimHash moved %d of %d bits", moved, BITS)
    values = {
        "content_digest": fingerprint.digest,
        "content_fingerprint": _hex(fingerprint.simhash),
        "last_changed_at": func.now(),
    }
    await _upsert(conn, site_id, canonical_url, values, last_seen_at=func.now())
    return True


async def _upsert(
    conn: AsyncConnection, site_id: SiteId, canonical_url: str, values: dict[str, Any], **inserted: Any
) -> None:
    """Set `values` on the URL's row, inserting it (with `inserted` too) when it has none."""
    insert = pg_insert(UrlState).values(site_id=site_id, canonical_url=canonical_url, **values, **inserted)
    await conn.execute(
        insert.on_conflict_do_update(index_elements=[UrlState.site_id, UrlState.canonical_url], set_=values)
    )


def _hex(fingerprint: int) -> str:
    """The fingerprint as `url_state.content_fingerprint` stores it: 16 lower-case hex digits."""
    return f"{fingerprint:016x}"


def _url(site_id: SiteId, canonical_url: str) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (UrlState.site_id == site_id, UrlState.canonical_url == canonical_url)
