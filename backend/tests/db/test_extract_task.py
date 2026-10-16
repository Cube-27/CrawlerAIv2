"""The extraction step of a page task (SPEC-05 §4.10, ARCHITECTURE §6, INV-27): the extraction, its candidates and
the page's record, as resolution decided them."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import AttemptRecord, FetchResult
from crawlerai.collect.og import OpenGraphCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.role_c import role_c
from crawlerai.core.capture import BlockClass
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Candidate, Extraction, Job, JobId, Project, Record, Site, SiteId, SourceKind, UsageEvent
from crawlerai.db.queue import ClaimedTask, insert_claimed
from crawlerai.llm.client import MeteredClient, ProviderReply
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.pipeline import EngineData, RoleC
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.records import entity_key
from crawlerai.resolve.task import Stored, extract_task
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
DOCUMENT = SchemaDocument(
    name="synthetic_product",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(
            type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"
        ),
    },
)


def _product(name: str, url: str, *, offers: bool = True) -> dict[str, Any]:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name, "url": url}
    if offers:
        node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    return node


def _page(*nodes: dict[str, Any], body: str = "") -> str:
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(node)}</script>' for node in nodes)
    return f"<html><head>{scripts}</head><body>{body}</body></html>"


class _Setup:
    def __init__(self, conn: AsyncConnection, tmp_path: Path) -> None:
        self.conn = conn
        self.store = FsStore(tmp_path)

    async def prepare(
        self, document: SchemaDocument, job_id: JobId | None = None
    ) -> tuple[SiteId, SchemaDef, ClaimedTask]:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site_id: SiteId = (
            await self.conn.execute(
                insert(Site).values(project_id=project, host="shop.example.test").returning(Site.id)
            )
        ).scalar_one()
        schema = await registry.create(self.conn, document, "user")
        if job_id is None:
            job_id = (
                await self.conn.execute(
                    insert(Job)
                    .values(project_id=project, kind="scrape", request={}, schema_id=schema.id, engine_version="e")
                    .returning(Job.id)
                )
            ).scalar_one()
        task = await insert_claimed(self.conn, job_id, PAGE_URL, PAGE_URL, document.page_kind, "test-worker")
        return site_id, schema, task

    async def run(
        self,
        body: str,
        *,
        document: SchemaDocument = DOCUMENT,
        block_class: BlockClass = "ok",
        caller_supplied: bool = True,
        role_c: RoleC | None = None,
        job_id: JobId | None = None,
    ) -> Stored:
        site_id, schema, task = await self.prepare(document, job_id)
        raw = body.encode()
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=PAGE_URL,
            final_url=PAGE_URL,
            fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
            method="http",
            status_code=200,
            block_class=block_class,
            headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
            timings_ms={},
            html_sha256=sha256_hex(raw),
            network_bodies=(),
            fetch_policy={},
            engine_version="0+cal.0",
        )
        bundle = CaptureBundle(manifest=manifest, body=raw, network=())
        attempt = AttemptRecord(method="http", status=200, block_class=block_class, duration_ms=1)
        fetched = FetchResult(bundle=bundle, duration_ms=1, attempts=(attempt,))
        capture_id = await store_capture(self.conn, self.store, fetched, site_id)
        self.site_id, self.schema = site_id, schema
        return await extract_task(
            self.conn,
            task,
            capture_id=capture_id,
            site_id=site_id,
            bundle=bundle,
            schema=schema,
            data=DATA,
            role_c=role_c,
            config=None,
            caller_supplied=caller_supplied,
            write_records=store_records,
        )

    async def candidates(self, stored: Stored) -> list[tuple[Any, ...]]:
        rows = await self.conn.execute(
            select(
                Candidate.field,
                Candidate.source_kind,
                Candidate.normalize_status,
                Candidate.chosen,
                Candidate.reject_reason,
            )
            .where(Candidate.extraction_id == stored.extraction_id)
            .order_by(Candidate.field, Candidate.entity_ref)
        )
        return [tuple(row) for row in rows]


@pytest.fixture
def setup(conn: AsyncConnection, tmp_path: Path) -> _Setup:
    return _Setup(conn, tmp_path)


async def test_a_complete_page_stores_its_extraction_candidates_and_record(setup: _Setup) -> None:
    stored = await setup.run(_page(_product("Widget One", PAGE_URL)))

    assert stored.outcome == "extracted"
    extraction = (
        await setup.conn.execute(select(Extraction.__table__).where(Extraction.id == stored.extraction_id))
    ).one()
    assert (extraction.mode, extraction.llm_calls, extraction.config_version, extraction.engine_version) == (
        "adhoc",
        0,
        None,
        ENGINE_VERSION,
    )
    assert await setup.candidates(stored) == [
        ("price", "jsonld", "ok", True, None),
        ("title", "jsonld", "ok", True, None),
    ]
    record = (await setup.conn.execute(select(Record.__table__).where(Record.id == stored.records[0].id))).one()
    assert record.data == {"title": "Widget One", "price": {"amount": "19.90", "currency": "EUR"}}
    assert record.complete is True
    assert (record.entity_key, record.schema_id, record.mode) == (
        entity_key(setup.site_id, PAGE_URL),
        setup.schema.id,
        "adhoc",
    )
    assert record.field_meta["title"] == {
        "status": "published",
        "reason": None,
        "evidence": "structured",
        "confidence": None,
        "calibrated": False,
        "source_kind": "jsonld",
        "locator": "jsonld:0:$['name']",
        "derived_by": None,
    }


async def test_a_rejected_candidate_keeps_its_reason(setup: _Setup) -> None:
    other = _product("Widget Two", "https://shop.example.test/p/2", offers=False)
    stored = await setup.run(_page(_product("Widget One", PAGE_URL), other))
    assert sorted(await setup.candidates(stored)) == [
        ("price", "jsonld", "ok", True, None),
        ("title", "jsonld", "ok", False, "not_owned"),
        ("title", "jsonld", "ok", True, None),
    ]


async def test_an_incomplete_caller_supplied_page_keeps_its_record(setup: _Setup) -> None:
    stored = await setup.run(_page(_product("Widget One", PAGE_URL, offers=False)))
    assert stored.outcome == "partial"
    record = (await setup.conn.execute(select(Record.__table__).where(Record.id == stored.records[0].id))).one()
    assert (record.data, record.complete) == ({"title": "Widget One"}, False)
    assert record.field_meta["price"]["status"] == "missing"


async def test_an_incomplete_crawl_discovered_page_is_no_match_without_a_record(setup: _Setup) -> None:
    stored = await setup.run(_page(_product("Widget One", PAGE_URL, offers=False)), caller_supplied=False)
    assert (stored.outcome, stored.records) == ("no_match", ())
    assert await setup.conn.scalar(select(Record.id).where(Record.extraction_id == stored.extraction_id)) is None
    assert await setup.candidates(stored) == [("title", "jsonld", "ok", True, None)]


async def test_a_page_that_was_not_served_stores_an_extraction_and_nothing_else(setup: _Setup) -> None:
    stored = await setup.run(_page(_product("Widget One", PAGE_URL)), block_class="shell")
    assert (stored.outcome, stored.records) == ("shell", ())
    assert await setup.candidates(stored) == []


async def test_the_extraction_keeps_the_collectors_diagnostics(setup: _Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    # SPEC-05 §4.14: a collector that raises is recorded on the extraction row, and the page still resolves.
    def broken(*_args: object) -> None:
        raise RuntimeError("collector bug")

    monkeypatch.setattr(OpenGraphCollector, "collect", broken)
    stored = await setup.run(_page(_product("Widget One", PAGE_URL)))
    diagnostics = await setup.conn.scalar(select(Extraction.diagnostics).where(Extraction.id == stored.extraction_id))
    assert diagnostics == ["OpenGraphCollector: RuntimeError: collector bug"]
    assert stored.outcome == "extracted"


LISTING = SchemaDocument(
    name="synthetic_listing",
    page_kind="listing",
    fields={
        "title": DOCUMENT.fields["title"],
        "url": FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
        "price": DOCUMENT.fields["price"].model_copy(update={"required": False}),
    },
)


def _item_list(*items: dict[str, Any]) -> dict[str, Any]:
    elements = [{"@type": "ListItem", "position": i + 1, "item": item} for i, item in enumerate(items)]
    return {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": elements}


async def test_a_listing_stores_one_record_per_row(setup: _Setup) -> None:
    urls = ["https://shop.example.test/p/1", "https://shop.example.test/p/2"]
    rows = [_product(f"Widget {n}", url, offers=False) for n, url in enumerate(urls, start=1)]
    stored = await setup.run(_page(_item_list(*rows)), document=LISTING)

    assert (stored.outcome, len(stored.records)) == ("extracted", 2)
    records = await setup.conn.execute(
        select(Record.entity_key, Record.data, Record.complete).where(Record.extraction_id == stored.extraction_id)
    )
    assert {(row.entity_key, row.data["title"], row.complete) for row in records} == {
        (entity_key(setup.site_id, urls[0]), "Widget 1", True),
        (entity_key(setup.site_id, urls[1]), "Widget 2", True),
    }
    # Each row's title is chosen by its own row; another row does not own it, which is not why it was rejected.
    assert [row for row in await setup.candidates(stored) if row[0] == "title"] == [
        ("title", "jsonld", "ok", True, None),
        ("title", "jsonld", "ok", True, None),
    ]


async def test_a_crawled_listing_keeps_only_its_complete_rows(setup: _Setup) -> None:
    nameless = {key: value for key, value in _product("", "https://shop.example.test/p/2").items() if key != "name"}
    rows = [_product("Widget 1", "https://shop.example.test/p/1"), nameless]
    stored = await setup.run(_page(_item_list(*rows)), document=LISTING, caller_supplied=False)

    assert stored.outcome == "partial"
    kept = await setup.conn.execute(select(Record.entity_key).where(Record.extraction_id == stored.extraction_id))
    assert kept.scalars().all() == [entity_key(setup.site_id, "https://shop.example.test/p/1")]


async def test_a_rows_candidate_keeps_the_reason_its_own_row_gave(setup: _Setup) -> None:
    # Two Offers that disagree make the row's price a conflict (INV-15); the other row does not own those values.
    split = _product("Widget 2", "https://shop.example.test/p/2")
    split["offers"] = [split["offers"], {**split["offers"], "price": "21.00"}]
    rows = [split, _product("Widget 1", "https://shop.example.test/p/1", offers=False)]
    stored = await setup.run(_page(_item_list(*rows)), document=LISTING)

    assert [row for row in await setup.candidates(stored) if row[0] == "price"] == [
        ("price", "jsonld", "ok", False, "offers_disagree"),
        ("price", "jsonld", "ok", False, "offers_disagree"),
    ]


async def test_role_c_runs_inside_the_task_without_waiting_on_its_transaction(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    # D-0346: the client commits usage on its own connection; the step writes nothing before role C's call, so the
    # call's usage commits while the task's transaction is open, and stays when that transaction rolls back.
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    async with engine.begin() as committed:
        job_id: JobId = (
            await committed.execute(
                insert(Job).values(project_id=project, kind="scrape", request={}, engine_version="e").returning(Job.id)
            )
        ).scalar_one()
    price = {"shown": True, "value": "19.90 EUR", "start": 11, "end": 20}
    answer = json.dumps({"fields": {"price": price}})
    provider = FakeProvider([ProviderReply(model="fake-fast", text=answer, tokens_in=7, tokens_out=3)])
    client = MeteredClient([provider], engine)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        setup = _Setup(conn, tmp_path)
        page = _page(_product("Widget One", PAGE_URL, offers=False), body="<h1>Widget One</h1><p>19.90 EUR</p>")
        with anyio.fail_after(30):
            stored = await setup.run(
                page,
                role_c=role_c(client, job_id=job_id),
                job_id=job_id,
            )
        assert await setup.candidates(stored) == [
            ("price", "llm", "ok", True, None),
            ("title", "jsonld", "ok", True, None),
        ]
        await transaction.rollback()
    async with engine.connect() as conn:
        usage = (await conn.execute(select(UsageEvent.resource).where(UsageEvent.job_id == job_id))).scalars().all()
    assert sorted(usage) == ["llm_calls", "llm_tokens_in", "llm_tokens_out"]
