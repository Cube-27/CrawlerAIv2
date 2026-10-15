"""Keyset paging (`crawlerai.db.paging`): the pages of a query, read cursor after cursor, are its rows in key order,
each once, and the last page has no cursor."""

from typing import Any

import pytest
from sqlalchemy import Select, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, JobId, Project
from crawlerai.db.paging import keyset_page

pytestmark = pytest.mark.anyio

JOBS = 7


async def _jobs(conn: AsyncConnection) -> list[JobId]:
    default_project = (await conn.execute(select(Project.id).where(Project.name == "default"))).scalar_one()
    values = {"project_id": default_project, "kind": "map", "request": {}, "engine_version": "0+cal.0"}
    rows = [{**values, "status": "completed"} for _ in range(JOBS)]
    ids = await conn.execute(insert(Job).returning(Job.id, sort_by_parameter_order=True), rows)
    return list(ids.scalars())


async def _all_pages(
    conn: AsyncConnection, query: Select[*tuple[Any, ...]], limit: int, *, descending: bool
) -> list[list[JobId]]:
    pages: list[list[JobId]] = []
    cursor = None
    while True:
        rows, cursor = await keyset_page(conn, query, Job.id, after=cursor, limit=limit, descending=descending)
        pages.append([row.id for row in rows])
        if cursor is None:
            return pages


@pytest.mark.parametrize("descending", [False, True])
@pytest.mark.parametrize(("limit", "sizes"), [(1, [1] * JOBS), (3, [3, 3, 1]), (JOBS, [JOBS]), (JOBS + 1, [JOBS])])
async def test_the_pages_are_the_rows_in_key_order(
    conn: AsyncConnection, limit: int, sizes: list[int], descending: bool
) -> None:
    ids = await _jobs(conn)
    query = select(Job.id, Job.kind).where(Job.id.in_(ids))

    pages = await _all_pages(conn, query, limit, descending=descending)

    assert [len(page) for page in pages] == sizes
    assert [job_id for page in pages for job_id in page] == sorted(ids, reverse=descending)
