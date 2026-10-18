"""The listing diff (SPEC-11 §4.5, ARCHITECTURE §14 row 4) against a real Postgres: runs of one records crawl are
simulated as jobs with their tasks, and ended through `close_run` as the queue ends them. A URL absent from two
consecutive runs of the crawl gets `gone_at` and a `url_gone` event; seen again, it is back."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import record_event
from crawlerai.db.models import (
    Extraction,
    Job,
    JobEvent,
    JobId,
    JobStatus,
    Project,
    Record,
    SchemaId,
    Site,
    SiteId,
    TaskRecord,
    UrlState,
    UrlTask,
)
from crawlerai.recurring.listing_diff import SITEMAPS_TIMED_OUT, close_run
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaChanges, SchemaDocument
from crawlerai.services.crawl import CrawlRequest

pytestmark = pytest.mark.anyio

TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}


class Shop:
    """A site, a detail schema, and the runs of records crawls over it."""

    def __init__(self, conn: AsyncConnection, site_id: SiteId, host: str, schema_id: SchemaId) -> None:
        self.conn, self.site_id, self.host, self.schema_id = conn, site_id, host, schema_id

    def url(self, path: str) -> str:
        return f"https://{self.host}/{path}"

    def request(self, **members: Any) -> dict[str, Any]:
        """A records crawl of the shop's products, as `submit_crawl` stores it."""
        rules = [{"pattern": self.url("p/*"), "page_kind": "detail"}]
        body = {"url": self.url(""), "formats": ["records"], "schema": {"id": str(self.schema_id)}}
        request = CrawlRequest.model_validate(body | {"page_kind_rules": rules} | members)
        return request.model_dump(mode="json", by_alias=True)

    async def run(
        self,
        *paths: str,
        request: dict[str, Any] | None = None,
        schema: bool = True,
        status: JobStatus = "completed",
        extra: tuple[dict[str, Any], ...] = (),
        events: tuple[str, ...] = (),
        rows: tuple[str | None, ...] = (),
        pinned: dict[str, Any] | None = None,
    ) -> JobId:
        """A run whose tasks are the start page, `paths` (each matched the crawl's rule) and `extra` tasks (their
        `url_task` columns), that recorded `events`; ended in `status`. The first of `paths` stands for a record per
        row URL of `rows` (None: a record that publishes no row URL). The job pinned `pinned`, else the schema as it is
        now."""
        if pinned is None:
            pinned = {"schema": (await registry.get_by_id(self.conn, self.schema_id)).model_dump(mode="json")}
        default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
        job = {
            "project_id": default_project,
            "kind": "crawl",
            "status": "running",
            "request": request or self.request(),
            "schema_id": self.schema_id if schema else None,
            "engine_version": "test",
            # What submit pins (INV-28, `JobPins`): only its schema is read here.
            "pinned": pinned,
        }
        job_id: JobId = (await self.conn.execute(insert(Job).values(job).returning(Job.id))).scalar_one()
        tasks = [self.task(""), *extra, *(self.task(path, page_kind="detail") for path in paths)]
        inserted = insert(UrlTask).returning(UrlTask.id, sort_by_parameter_order=True)
        task_ids = (await self.conn.execute(inserted, [{"job_id": job_id} | task for task in tasks])).scalars().all()
        if rows:
            await self.stand_for_rows(job_id, task_ids[1 + len(extra)], rows)
        for kind in events:
            await record_event(self.conn, job_id, kind, {"url": self.url("")})
        await close_run(self.conn, job_id, status)
        return job_id

    async def stand_for_rows(self, job_id: JobId, task_id: Any, rows: tuple[str | None, ...]) -> None:
        """Make the task stand for one record per row URL, as a listing page's task does."""
        extraction = {"url_task_id": task_id, "engine_version": "test", "mode": "adhoc"}
        extraction_id = (
            await self.conn.execute(insert(Extraction).values(extraction).returning(Extraction.id))
        ).scalar_one()
        for index, url in enumerate(rows):
            data = {"title": "row"} if url is None else {"title": "row", "url": url}
            values = {
                "extraction_id": extraction_id,
                "job_id": job_id,
                "site_id": self.site_id,
                "schema_id": self.schema_id,
                "entity_key": url or f"row-{index}",
                "data": data,
                "field_meta": {},
                "complete": True,
                "mode": "adhoc",
                "schema_digest": "digest",
            }
            record_id = (await self.conn.execute(insert(Record).values(values).returning(Record.id))).scalar_one()
            await self.conn.execute(insert(TaskRecord).values(url_task_id=task_id, record_id=record_id))

    def task(self, path: str, **columns: Any) -> dict[str, Any]:
        """A task of a run at `path`: a page that ended `links_only` unless `columns` say otherwise."""
        url = self.url(path) if "://" not in path else path
        task = {"url": url, "canonical_url": url, "page_kind": None, "status": "done", "outcome": "links_only"}
        return task | columns

    async def state(self) -> dict[str, tuple[int, bool]]:
        """Each URL's `url_state` row, by path: its missing runs, and whether it is gone."""
        query = select(UrlState.canonical_url, UrlState.missing_runs, UrlState.gone_at).where(
            UrlState.site_id == self.site_id
        )
        prefix = len(self.url(""))
        return {url[prefix:]: (missing, gone is not None) for url, missing, gone in await self.conn.execute(query)}

    async def gone_events(self, job_id: JobId) -> list[dict[str, Any]]:
        query = select(JobEvent.payload).where(JobEvent.job_id == job_id, JobEvent.kind == "url_gone")
        return list((await self.conn.execute(query.order_by(JobEvent.id))).scalars())


@pytest.fixture
async def shop(conn: AsyncConnection) -> Shop:
    host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    insert_site = insert(Site).values(project_id=default_project, host=host).returning(Site.id)
    site_id: SiteId = (await conn.execute(insert_site)).scalar_one()
    document = {"name": f"synthetic_{uuid.uuid4().hex[:12]}", "page_kind": "detail"}
    schema = await registry.create(conn, SchemaDocument.model_validate(document | {"fields": {"title": TITLE}}), "user")
    return Shop(conn, site_id, host, schema.id)


async def test_a_url_absent_from_two_consecutive_runs_is_gone_and_back_once_seen_again(shop: Shop) -> None:
    await shop.run("p/a", "p/b", "p/c")
    await shop.run("p/a", "p/b")
    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False), "p/c": (1, False)}

    third = await shop.run("p/a", "p/b")

    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False), "p/c": (2, True)}
    assert await shop.gone_events(third) == [{"url": shop.url("p/c")}]

    fourth = await shop.run("p/a", "p/b", "p/c")

    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False), "p/c": (0, False)}
    assert await shop.gone_events(fourth) == []


async def test_a_gone_url_is_not_counted_or_announced_again(shop: Shop) -> None:
    await shop.run("p/a", "p/b")
    for _ in range(2):
        await shop.run("p/a")

    fourth = await shop.run("p/a")

    assert await shop.state() == {"p/a": (0, False), "p/b": (2, True)}
    assert await shop.gone_events(fourth) == []


async def test_a_url_seen_between_two_misses_starts_counting_again(shop: Shop) -> None:
    for paths in (("p/a", "p/b"), ("p/a",), ("p/a", "p/b"), ("p/a",)):
        await shop.run(*paths)

    assert await shop.state() == {"p/a": (0, False), "p/b": (1, False)}


async def test_a_crawl_with_another_scope_marks_nothing_missing(shop: Shop) -> None:
    await shop.run("p/a", "p/b")
    other = shop.request(include=[shop.url("p/c*")])

    for _ in range(2):
        await shop.run("p/c", request=other)

    # Each listing is diffed against its own earlier runs: p/a and p/b were never in the other crawl's.
    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False), "p/c": (0, False)}


async def test_a_run_that_stopped_at_its_limit_marks_nothing_missing(shop: Shop) -> None:
    request = shop.request(limit=4)
    await shop.run("p/a", "p/b", request=request)

    # Four tasks: the frontier stopped adding URLs, so p/b may still be listed.
    for _ in range(2):
        await shop.run("p/a", "p/c", "p/d", request=request)

    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False), "p/c": (0, False), "p/d": (0, False)}


async def test_a_run_that_matched_no_url_marks_nothing_missing(shop: Shop) -> None:
    await shop.run("p/a")

    for _ in range(2):
        await shop.run()

    assert await shop.state() == {"p/a": (0, False)}


async def test_a_run_with_an_unreached_navigation_page_marks_nothing_missing(shop: Shop) -> None:
    await shop.run("p/a", "p/b")

    # The category page that listed p/b added no links: p/b may still be listed.
    for _ in range(2):
        await shop.run("p/a", extra=(shop.task("c/1", outcome="blocked"),))

    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False)}


async def test_a_run_whose_sitemap_reading_timed_out_marks_nothing_missing(shop: Shop) -> None:
    await shop.run("p/a", "p/b")

    # The sitemaps' tail was not read: p/b may be listed there still.
    for _ in range(2):
        await shop.run("p/a", events=(SITEMAPS_TIMED_OUT,))

    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False)}


async def test_a_navigation_page_that_is_not_found_lists_nothing(shop: Shop) -> None:
    await shop.run("p/a", "p/b")

    # A listing page that is gone is a real change: what only it listed is missing.
    for _ in range(2):
        await shop.run("p/a", extra=(shop.task("c/1", outcome="not_found"),))

    assert await shop.state() == {"p/a": (0, False), "p/b": (2, True)}


@pytest.mark.parametrize(("status", "schema"), [("cancelled", True), ("completed", False)])
async def test_only_a_completed_records_crawl_is_a_run(shop: Shop, status: JobStatus, schema: bool) -> None:
    await shop.run("p/a", "p/b")

    for _ in range(2):
        await shop.run("p/a", status=status, schema=schema)

    assert await shop.state() == {"p/a": (0, False), "p/b": (0, False)}


async def test_urls_no_rule_matched_and_urls_off_the_start_host_are_not_in_the_listing(shop: Shop) -> None:
    await shop.run("p/a", extra=(shop.task("c/1"), shop.task(f"https://de.{shop.host}/p/a", page_kind="detail")))

    assert await shop.state() == {"p/a": (0, False)}


async def test_a_url_no_listing_held_is_never_missing(shop: Shop) -> None:
    # A page fetched by a scrape has a row (conditional GET, §4.2), but no listing ever held it.
    row = {"site_id": shop.site_id, "canonical_url": shop.url("p/z"), "last_seen_at": func.now()}
    await shop.conn.execute(insert(UrlState).values(row))

    for _ in range(3):
        await shop.run("p/a")

    assert await shop.state() == {"p/a": (0, False), "p/z": (0, False)}


ROW_URL = {"type": "url", "required": True, "description": "d", "schema_org": "Product.url"}


async def listing_shop(shop: Shop, conn: AsyncConnection) -> Shop:
    """The shop with a listing schema whose rows name their URL in `url`."""
    document = {"name": f"synthetic_{uuid.uuid4().hex[:12]}", "page_kind": "listing"}
    fields = {"title": TITLE, "url": ROW_URL}
    schema = await registry.create(conn, SchemaDocument.model_validate(document | {"fields": fields}), "user")
    return Shop(conn, shop.site_id, shop.host, schema.id)


async def test_the_row_urls_of_a_listing_crawl_are_in_the_listing(shop: Shop, conn: AsyncConnection) -> None:
    rows = await listing_shop(shop, conn)
    kettles = tuple(shop.url(f"kettles/{name}") for name in ("a", "b", "c"))

    await rows.run("l/1", rows=kettles)
    await rows.run("l/1", rows=(*kettles[:2], "https://other.example.test/x"))
    third = await rows.run("l/1", rows=kettles[:2])

    # Row URLs are listed beside the page's: c, which only the first run held, has missed two runs and is gone, and a
    # row on another host is not the site's.
    assert await rows.state() == {
        "l/1": (0, False),
        "kettles/a": (0, False),
        "kettles/b": (0, False),
        "kettles/c": (2, True),
    }
    assert await rows.gone_events(third) == [{"url": kettles[2]}]


async def test_a_detail_schemas_records_add_no_row_urls(shop: Shop) -> None:
    await shop.run("p/a", rows=(shop.url("not/a/row"),))

    # The shop's schema is a detail schema: records name no row, so nothing but the matched page is listed.
    assert await shop.state() == {"p/a": (0, False)}


async def test_a_record_that_publishes_no_row_url_names_no_row(shop: Shop, conn: AsyncConnection) -> None:
    rows = await listing_shop(shop, conn)
    kettle = shop.url("kettles/a")

    await rows.run("l/1", rows=(kettle, None))

    # The row without a URL lists nothing, and the run still ends with its listing seen.
    assert await rows.state() == {"l/1": (0, False), "kettles/a": (0, False)}


async def test_a_schema_edit_while_a_run_is_live_keeps_its_row_urls(shop: Shop, conn: AsyncConnection) -> None:
    rows = await listing_shop(shop, conn)
    kettles = tuple(shop.url(f"kettles/{name}") for name in ("a", "b"))
    await rows.run("l/1", rows=kettles)
    current = await registry.get_by_id(conn, rows.schema_id)
    pinned = {"schema": current.model_dump(mode="json")}

    # The schema's row URL field is renamed after the second run was submitted: that run pinned the old schema, and
    # its records (extracted with it) still hold the row URLs in `url`.
    renamed = SchemaChanges.model_validate({"fields": {"title": TITLE, "link": ROW_URL}})
    await registry.update_schema(conn, current, renamed)
    second = await rows.run("l/1", rows=kettles, pinned=pinned)

    assert await rows.state() == {"l/1": (0, False), "kettles/a": (0, False), "kettles/b": (0, False)}
    assert await rows.gone_events(second) == []
