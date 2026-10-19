"""Host turns and holds shared by every process (acquisition spec, "Per-site rate and backoff"; `host_turn`): one turn
per spacing across holders, a held host refuses every other holder until released or its lease lapses, and only rows
that say nothing are swept."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.host_turns import HostTurns, expire_host_turns

ZERO = timedelta(0)
SPACING = timedelta(milliseconds=200)


@pytest.mark.anyio
async def test_a_turn_and_a_hold_are_one_holders_until_released_or_lapsed(engine: AsyncEngine) -> None:
    turns = HostTurns(engine)
    host = f"{uuid.uuid4().hex}.example.test"

    assert await turns.take(host, SPACING, "a") == ZERO
    assert ZERO < await turns.take(host, SPACING, "b") <= SPACING  # the spacing holds across holders
    await asyncio.sleep(SPACING.total_seconds())
    # The turn is due, but `a` holds the host: refused to `b` and to an unheld request; `a`'s own next request goes.
    assert await turns.take(host, SPACING, "b") == SPACING
    assert await turns.take(host, SPACING, None) == SPACING
    assert await turns.take(host, SPACING, "a") == ZERO

    await turns.release(host, "a")
    await asyncio.sleep(SPACING.total_seconds())
    assert await turns.take(host, SPACING, "b") == ZERO

    # A holder that stops renewing (its process died) holds the host no longer than its lease.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE host_turn SET held_until = clock_timestamp(), next_at = clock_timestamp() WHERE host = :h"),
            {"h": host},
        )
    assert await turns.take(host, SPACING, "c") == ZERO

    # A row the scheduler sweeps is one whose turn is due and that no lease holds.
    async with engine.begin() as conn:
        await expire_host_turns(conn, batch=1000)
        assert (await conn.execute(text("SELECT count(*) FROM host_turn WHERE host = :h"), {"h": host})).scalar() == 1
        await conn.execute(
            text("UPDATE host_turn SET held_until = NULL, next_at = clock_timestamp() WHERE host = :h"), {"h": host}
        )
        await expire_host_turns(conn, batch=1000)
        assert (await conn.execute(text("SELECT count(*) FROM host_turn WHERE host = :h"), {"h": host})).scalar() == 0
