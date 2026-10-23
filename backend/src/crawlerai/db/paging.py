"""Keyset paging: a page is the rows after a cursor, the key of the last row of the page before, in key
order. Unlike an offset, a cursor stays valid while rows are added, and each page reads only its own rows through the
key's index.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import KeyedColumnElement


async def keyset_page[K](
    conn: AsyncConnection,
    statement: Select[*tuple[Any, ...]],
    key: QueryableAttribute[K] | KeyedColumnElement[K],
    *,
    after: K | None,
    limit: int,
    descending: bool,
) -> tuple[Sequence[Row[*tuple[Any, ...]]], K | None]:
    """The page of up to `limit` rows of `statement` after the cursor `after` (the first page without one), ordered
    by `key`, which `statement` selects under its own name and which is unique; and the cursor of the page after it,
    None on the last. One row past `limit` is read to tell whether there is a next page."""
    if after is not None:
        statement = statement.where(key < after if descending else key > after)
    ordered = statement.order_by(key.desc() if descending else key).limit(limit + 1)
    rows = (await conn.execute(ordered)).all()
    page = rows[:limit]
    next_cursor: K | None = page[-1]._mapping[key.key] if len(rows) > limit else None
    return page, next_cursor


async def total_rows(conn: AsyncConnection, statement: Select[*tuple[Any, ...]]) -> int:
    """How many rows `statement` selects in all, whatever the cursor: the total a paged answer shows beside its page.
    `statement` is the filtered, unordered select, before any cursor or limit."""
    return (await conn.execute(select(func.count()).select_from(statement.order_by(None).subquery()))).scalar_one()
