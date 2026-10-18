"""`crawlerai eval import-labels` without a database (D-1460): the label file's shape and its checks, label values
normalized as drafts in the captured page's context, declines reported by path, and the import loop's skips. Synthetic
`.test` URLs only."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import JsonValue

from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, EvalRunId, SchemaId, Split
from crawlerai.eval.cli import PageRequest, Skipped
from crawlerai.eval.label_file import (
    Declined,
    Imported,
    LabeledPage,
    draft_labels,
    import_pages,
    labeled_pages,
    read_label_file,
    report,
)
from crawlerai.eval.labels import LabelStatus
from crawlerai.eval.store import EvalPageRow, EvalRunRow, LabelPass, Labels
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

A = "https://a.example.test"


def _spec(type_: FieldType, **more: Any) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, "description": "d", **more})


DETAIL = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic_detail",
    page_kind="detail",
    fields={
        "title": _spec(FieldType.TEXT, required=True),
        "price": _spec(FieldType.MONEY),
        "availability": _spec(FieldType.ENUM, vocab="schema:ItemAvailability"),
        "images": _spec(FieldType.LIST, item={"type": "image_url"}),
        "places": _spec(FieldType.LIST, item={"type": "location"}),
        "variants": _spec(
            FieldType.LIST,
            key=["sku"],
            schema_org="Product.offers",
            item={"type": "object", "fields": {"sku": {"type": "identifier", "scheme": "sku", "description": "d"}}},
        ),
    },
)
LISTING = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic_listing",
    page_kind="listing",
    fields={
        "title": _spec(FieldType.TEXT, required=True),
        "url": _spec(FieldType.URL, required=True),
        "next_page_url": _spec(FieldType.URL, scope="page"),
    },
)
SCHEMAS = {schema.name: schema for schema in (DETAIL, LISTING)}
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))


def file_text(*pages: dict[str, Any], **top: Any) -> str:
    return json.dumps({"dataset": "ignored", **top, "pages": list(pages)})


def page(url: str = f"{A}/p/1", schema: str = "synthetic_detail", **more: Any) -> dict[str, Any]:
    return {"url": url, "schema": schema, "category": "custom_store", "site": "ignored", **more}


def labeled(fields: dict[str, JsonValue], rows: tuple[dict[str, JsonValue], ...] = ()) -> LabeledPage:
    return LabeledPage(PageRequest(1, f"{A}/p/1", "synthetic_detail", "custom_store"), fields, rows, "")


def test_values_are_stored_as_the_normalizer_reads_them() -> None:
    labels, declined = draft_labels(
        labeled(
            {
                "title": "  Item &amp; more ",
                "price": {"amount": "19.9", "currency": "EUR"},
                "availability": "http://schema.org/InStock",
                "places": [{"name": "Lakeside", "jobLocationType": "TELECOMMUTE"}],
                "images": [f"{A}/i/1.jpg"],
            }
        ),
        DETAIL,
        CTX,
    )
    assert declined == ()
    assert (labels.status, labels.labeler, labels.prefill_source) == ("draft", None, "none")
    assert {name: label.value for name, label in labels.fields.items()} == {
        "title": "Item & more",
        "price": {"amount": "19.9", "currency": "EUR"},
        "availability": "InStock",
        "places": [{"text": "Lakeside", "locality": None, "region": None, "country": None, "remote_flag": True}],
        "images": [f"{A}/i/1.jpg"],
    }
    # A field the file does not give stays unlabeled, never absent.
    assert all(not label.absent for label in labels.fields.values())


def bundle(url: str) -> CaptureBundle:
    body = b"<html lang='en'><body><h1>Item</h1></body></html>"
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
        fetched_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={"total": 100},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=body, network=())


class LabelStore:
    """The parts of an `EvalStore` an import writes, in memory."""

    split: Split = "dev"

    def __init__(self) -> None:
        self.pages: dict[EvalPageId, EvalPageRow] = {}
        self.labels: dict[EvalPageId, tuple[Labels, str | None, LabelPass, Labels]] = {}

    async def list_pages(self, schema_name: str | None = None, status: LabelStatus | None = None) -> list[EvalPageRow]:
        raise NotImplementedError

    async def get_page(self, page_id: EvalPageId) -> EvalPageRow:
        raise NotImplementedError

    async def get_bundle(self, capture_id: CaptureId) -> CaptureBundle:
        raise NotImplementedError

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId:
        return CaptureId(bundle.manifest.capture_id)

    async def put_page(self, page: EvalPageRow) -> EvalPageId:
        self.pages[page.id] = page
        return page.id

    async def put_labels(
        self, page_id: EvalPageId, labels: Labels, who: str | None, pass_: LabelPass, *, expected: Labels
    ) -> None:
        self.labels[page_id] = (labels, who, pass_, expected)

    async def put_run(self, run: EvalRunRow) -> EvalRunId:
        raise NotImplementedError

    async def get_run(self, run_id: EvalRunId) -> EvalRunRow:
        raise NotImplementedError

    async def llm_cache_get(self, key: str) -> bytes | None:
        raise NotImplementedError

    async def llm_cache_put(self, key: str, value: bytes) -> None:
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


def test_an_import_stores_each_fetched_page_with_its_draft_and_skips_the_rest() -> None:
    pages = labeled_pages(
        read_label_file(
            file_text(
                page(fields={"title": "Item", "price": {"amount": "5", "currency": "XYZ"}}),
                page(f"{A}/p/2", fields={"title": "Robots"}),
                page(f"{A}/p/3", fields={"title": "Done"}),
            )
        ),
        SCHEMAS,
    )
    fetched: list[tuple[str, str]] = []

    async def fetch(url: str, schema: SchemaDef) -> Any:
        fetched.append((url, schema.name))
        return "robots" if url.endswith("/2") else bundle_result(url)

    store = LabelStore()
    outcomes = asyncio.run(import_pages(store, SCHEMAS, pages, fetch, existing={f"{A}/p/3"}))

    assert fetched == [(f"{A}/p/1", "synthetic_detail"), (f"{A}/p/2", "synthetic_detail")]
    [imported, robots, done] = outcomes
    assert (robots, done) == (Skipped(2, "robots"), Skipped(3, "already_in_split"))
    assert isinstance(imported, Imported)
    assert (imported.labeled, imported.declined) == (1, (Declined("fields.price", "unknown_currency"),))
    [(page_id, (stored, who, pass_, expected))] = store.labels.items()
    assert page_id == imported.captured.page_id
    assert store.pages[page_id].schema_name == "synthetic_detail"
    assert (who, pass_, expected) == (None, "labeler", {})
    assert stored["status"] == "draft"
    assert stored["fields"] == {"title": {"value": "Item", "absent": False, "locator": None, "distractors": []}}
    lines = [json.loads(line) for line in report(outcomes).splitlines()]
    assert [line["n"] for line in lines] == [1, 2, 3]
    assert lines[0]["declined"] == [{"path": "fields.price", "reason": "unknown_currency"}]
    assert "example.test" not in report(outcomes)


def bundle_result(url: str) -> Any:
    from crawlerai.acquire.types import AttemptRecord, FetchResult

    attempt = AttemptRecord.model_validate({"method": "http", "status": 200, "block_class": "ok", "duration_ms": 1})
    return FetchResult(bundle=bundle(url), attempts=(attempt,), duration_ms=1)
