"""Host turns and holds shared by every process that fetches (`politeness.SharedTurns`): one `host_turn` row per host,
written by single statements, so the database orders the
processes' turns. A turn is taken, and the host held, in one upsert whose condition (turn due, no other holder's lease
running) PostgreSQL re-checks on the row's latest version under its lock (INSERT ... ON CONFLICT DO UPDATE), so two
processes never both take it. Times are the database's clock (`clock_timestamp()`), the one clock every process
shares.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from snowcrawl.acquire.politeness import HOLD_LEASE

__all__ = ["EXPIRE_BATCH", "HostTurns", "expire_host_turns"]

# Rows the scheduler deletes per run (`expire_host_turns`).
EXPIRE_BATCH: Final = 1000

# The upsert takes the turn (and the hold, with a holder); the outer SELECT reads the row as it was before the
# statement (PostgreSQL §7.8.4: the sub-statements and the main query see one snapshot), for the wait when it did not.
_TAKE = text("""
    WITH taken AS (
        INSERT INTO host_turn (host, next_at, holder, held_until)
        VALUES (
            :host,
            clock_timestamp() + CAST(:spacing AS interval),
            CAST(:holder AS text),
            CASE WHEN CAST(:holder AS text) IS NOT NULL THEN clock_timestamp() + CAST(:lease AS interval) END
        )
        ON CONFLICT (host) DO UPDATE
        SET next_at = clock_timestamp() + CAST(:spacing AS interval),
            holder = coalesce(CAST(:holder AS text), host_turn.holder),
            held_until = CASE WHEN CAST(:holder AS text) IS NOT NULL
                              THEN clock_timestamp() + CAST(:lease AS interval) ELSE host_turn.held_until END
        WHERE host_turn.next_at <= clock_timestamp()
          AND (host_turn.holder IS NULL OR host_turn.held_until <= clock_timestamp()
               OR host_turn.holder = CAST(:holder AS text))
        RETURNING 1
    )
    SELECT EXISTS (SELECT FROM taken) AS taken,
           extract(epoch FROM host_turn.next_at - clock_timestamp()) AS wait,
           coalesce(
               host_turn.held_until > clock_timestamp() AND host_turn.holder IS DISTINCT FROM CAST(:holder AS text),
               false
           ) AS held
    FROM (VALUES (1)) AS one (x) LEFT JOIN host_turn ON host_turn.host = :host
""")
_PAUSE = text("""
    INSERT INTO host_turn (host, next_at) VALUES (:host, clock_timestamp() + CAST(:after AS interval))
    ON CONFLICT (host) DO UPDATE
    SET next_at = greatest(host_turn.next_at, clock_timestamp() + CAST(:after AS interval))
""")
_RELEASE = text("UPDATE host_turn SET holder = NULL, held_until = NULL WHERE host = :host AND holder = :holder")
# A row whose turn is due and that no lease holds says nothing its absence does not: a take inserts it afresh.
_EXPIRE = text("""
    DELETE FROM host_turn WHERE host IN (
        SELECT host FROM host_turn
        WHERE next_at <= clock_timestamp() AND (held_until IS NULL OR held_until <= clock_timestamp())
        LIMIT :batch FOR UPDATE SKIP LOCKED
    )
""")
_RENEW = text("""
    UPDATE host_turn SET held_until = clock_timestamp() + CAST(:lease AS interval)
    WHERE holder = ANY(CAST(:holders AS text[]))
""")


@dataclass(frozen=True)
class HostTurns:
    """`SharedTurns` in `database`'s `host_turn` table."""

    database: AsyncEngine

    async def take(self, host: str, spacing: timedelta, holder: str | None) -> timedelta:
        params = {"host": host, "spacing": spacing, "holder": holder, "lease": HOLD_LEASE}
        async with self.database.begin() as conn:
            row = (await conn.execute(_TAKE, params)).one()
        if row.taken:
            return timedelta(0)
        # Held by another, or taken by another process since the snapshot the wait was read in: ask again a spacing on.
        if row.held or row.wait is None or row.wait <= 0:
            return spacing
        return timedelta(seconds=float(row.wait))

    async def pause(self, host: str, after: timedelta) -> None:
        async with self.database.begin() as conn:
            await conn.execute(_PAUSE, {"host": host, "after": after})

    async def release(self, host: str, holder: str) -> None:
        async with self.database.begin() as conn:
            await conn.execute(_RELEASE, {"host": host, "holder": holder})

    async def renew(self, holders: Iterable[str]) -> None:
        if names := list(holders):
            async with self.database.begin() as conn:
                await conn.execute(_RENEW, {"holders": names, "lease": HOLD_LEASE})


async def expire_host_turns(conn: AsyncConnection, *, batch: int) -> int:
    """Delete up to `batch` rows of hosts whose turn is due and that no lease holds, and return how many: one row per
    host ever fetched would otherwise stay (scheduler)."""
    result = await conn.execute(_EXPIRE, {"batch": batch})
    return int(result.rowcount)
