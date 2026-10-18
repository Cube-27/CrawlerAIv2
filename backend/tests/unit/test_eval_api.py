"""The labeling API (SPEC-03 §4.10): the golden set's pages only, sanitized page HTML, labels validated before
anything is stored, every validation error returned with its field and reason (§4.11). A fake backend stands in for
the dev store and `schema_def`; `tests/db/test_labeling_api.py` runs the same flow against Postgres."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import JsonValue

from crawlerai.acquire.types import FetchPolicy
from crawlerai.api.app import create_app
from crawlerai.api.auth import require_api_key
from crawlerai.api.routers import eval as eval_router
from crawlerai.core.ids import uuid7
from crawlerai.db.models import ApiKeyId, CaptureId, EvalCategory, EvalPageId, EvalRunId, PageKind, SchemaId, Split
from crawlerai.eval.cli import Captured, EvalCliError, Outcome, PageRequest, Skipped
from crawlerai.eval.labels import LabelStatus, parse_labels
from crawlerai.eval.store import (
    EvalNotFound,
    EvalPageRow,
    EvalRunRow,
    LabelPass,
    Labels,
    LabelsChanged,
)
from crawlerai.llm.providers.fake import ScriptedClient
from crawlerai.schemas.types import FieldSpec, FieldType
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

PAGE_URL = "https://store.test/items/1"
FINAL_URL = "https://store.test/items/1?ref=a"
SCHEMA_ID = SchemaId(uuid7())
KEY_ID = ApiKeyId(uuid7())
SPECS: dict[str, FieldSpec] = {"title": FieldSpec(type=FieldType.TEXT), "price": FieldSpec(type=FieldType.MONEY)}
HTML = (
    b"<html><head><title>Item</title><script>track()</script></head>"
    b'<body onload="boot()"><h1 class="t" onclick="x()">Blue mug</h1>'
    b'<a href="javascript:buy()">Buy</a><img src="/mug.png">'
    b'<iframe src="/ad"></iframe><object data="/o"></object><embed src="/e">'
    b"<p>EUR 19.90</p></body></html>"
)


def _bundle(body: bytes = HTML) -> CaptureBundle:
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=PAGE_URL,
        final_url=FINAL_URL,
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("content-type", "text/html; charset=utf-8"),)),
        timings_ms={"total": 1},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy=FetchPolicy().model_dump(mode="json"),
        engine_version="test",
    )
    return CaptureBundle(manifest=manifest, body=body, network=())


@dataclass
class FakeStore:
    """The dev store's page and label operations, in memory."""

    pages: dict[EvalPageId, EvalPageRow] = field(default_factory=dict)
    bundles: dict[CaptureId, CaptureBundle | Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    @property
    def split(self) -> Split:
        return "dev"

    def add(
        self,
        labels: Labels | None = None,
        labeler: str | None = None,
        page_kind: PageKind = "detail",
        body: bytes = HTML,
    ) -> EvalPageRow:
        bundle = _bundle(body)
        capture_id = CaptureId(bundle.manifest.capture_id)
        page = EvalPageRow(
            capture_id=capture_id,
            split="dev",
            schema_id=SCHEMA_ID,
            schema_name="item_detail",
            page_kind=page_kind,
            category="custom_store",
            labels=labels or {},
            labeler=labeler,
        )
        self.pages[page.id], self.bundles[capture_id] = page, bundle
        return page

    async def list_pages(self, schema_name: str | None = None, status: LabelStatus | None = None) -> list[EvalPageRow]:
        self.calls.append("list_pages")
        return [
            page
            for page in self.pages.values()
            if schema_name in (None, page.schema_name) and status in (None, page.labels.get("status"))
        ]

    async def get_page(self, page_id: EvalPageId) -> EvalPageRow:
        self.calls.append("get_page")
        if page_id not in self.pages:
            raise EvalNotFound(f"no dev eval page {page_id}")
        return self.pages[page_id]

    async def get_bundle(self, capture_id: CaptureId) -> CaptureBundle:
        bundle = self.bundles[capture_id]
        if isinstance(bundle, Exception):
            raise bundle
        return bundle

    async def put_labels(
        self, page_id: EvalPageId, labels: Labels, who: str | None, pass_: LabelPass, *, expected: Labels
    ) -> None:
        if self.pages[page_id].labels != expected:
            raise LabelsChanged(f"the labels of dev eval page {page_id} changed since they were read")
        self.calls.append(f"put_labels:{pass_}:{who}")
        # As the store does: a labeler pass clears the checker.
        update: dict[str, object] = {"labels": labels, pass_: who}
        match pass_:
            case "labeler":
                update["checker"] = None
        self.pages[page_id] = self.pages[page_id].model_copy(update=update)

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId:
        raise AssertionError("not used by the API")

    async def put_page(self, page: EvalPageRow) -> EvalPageId:
        raise AssertionError("not used by the API")

    async def put_run(self, run: EvalRunRow) -> EvalRunId:
        raise AssertionError("not used by the API")

    async def get_run(self, run_id: EvalRunId) -> EvalRunRow:
        raise AssertionError("not used by the API")

    async def llm_cache_get(self, key: str) -> bytes | None:
        raise AssertionError("not used by the API")

    async def llm_cache_put(self, key: str, value: bytes) -> None:
        raise AssertionError("not used by the API")

    async def aclose(self) -> None:
        pass


@dataclass
class FakeBackend:
    store: FakeStore = field(default_factory=FakeStore)
    captures: list[tuple[list[PageRequest], PageKind]] = field(default_factory=list)
    capture_result: list[Outcome] | EvalCliError = field(default_factory=list)
    llm: "ScriptedClient" = field(default_factory=lambda: ScriptedClient())
    specs: dict[str, FieldSpec] = field(default_factory=lambda: SPECS)

    async def schema_fields(self, schema_id: SchemaId) -> dict[str, FieldSpec]:
        assert schema_id == SCHEMA_ID
        return self.specs

    async def capture(self, requests: Sequence[PageRequest], page_kind: PageKind) -> list[Outcome]:
        self.captures.append((list(requests), page_kind))
        if isinstance(self.capture_result, EvalCliError):
            raise self.capture_result
        return self.capture_result


def _request(
    backend: FakeBackend | None, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    app = create_app(eval_ui=backend is not None)
    if backend is not None:
        app.dependency_overrides[eval_router.labeling_backend] = lambda: backend
        app.dependency_overrides[require_api_key] = lambda: KEY_ID

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
            return await client.request(method, path, json=body, headers=headers)

    return asyncio.run(send())


def _capture_body(urls: list[str], split: str = "dev") -> dict[str, object]:
    return {"split": split, "schema": "item_detail", "page_kind": "detail", "category": "custom_store", "urls": urls}


def _writes(backend: FakeBackend) -> list[str]:
    return [call for call in backend.store.calls if call.startswith("put_labels")]


def _labels(status: str = "labeled", labeler: str | None = "ana", checker: str | None = None) -> dict[str, JsonValue]:
    return {
        "label_version": 1,
        "status": status,
        "labeler": labeler,
        "checker": checker,
        "fields": {
            "title": {"value": "Blue mug", "absent": False, "locator": "xpath://h1"},
            "price": {"value": {"amount": "19.90", "currency": "EUR"}, "absent": False, "locator": None},
        },
    }


def _stored(labels: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """`labels` as the API stores it: the full document with its defaults."""
    return {
        **labels,
        "prefill_source": None,
        "rows": [],
        "notes": "",
        "fields": {
            "title": {"value": "Blue mug", "absent": False, "locator": "xpath://h1", "distractors": []},
            "price": {
                "value": {"amount": "19.90", "currency": "EUR"},
                "absent": False,
                "locator": None,
                "distractors": [],
            },
        },
    }


def test_labeler_pass_stores_the_validated_labels() -> None:
    backend = FakeBackend()
    page = backend.store.add()

    response = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels())

    assert response.status_code == 200
    assert response.json()["status"] == "labeled"
    assert _writes(backend) == ["put_labels:labeler:ana"]
    assert backend.store.pages[page.id].labels == _stored(_labels())
    exported = _request(backend, "GET", f"/v1/eval/pages/{page.id}").json()["labels"]
    assert exported == _stored(_labels())


def test_invalid_labels_return_every_error_and_store_nothing() -> None:
    backend = FakeBackend()
    page = backend.store.add()
    labels = _labels()
    labels["fields"] = {
        "title": {"value": None, "absent": False},
        "colour": {"value": "blue", "absent": False},
    }

    response = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", labels)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert (problem["type"], problem["status"]) == ("validation", 422)
    assert problem["errors"] == [{"field": "fields.title", "reason": "a present field has a value"}]
    labels["fields"] = {"title": {"value": "Blue mug", "absent": False}, "colour": {"value": "blue", "absent": False}}
    problem = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", labels).json()
    assert problem["errors"] == [
        {"field": "fields.colour", "reason": "not a field of the schema"},
        {"field": "fields.price", "reason": "not labeled; mark it absent if the page does not show it"},
    ]
    assert _writes(backend) == []
    assert backend.store.pages[page.id].labels == {}


def test_checker_cannot_be_the_labeler() -> None:
    backend = FakeBackend()
    page = backend.store.add(_stored(_labels()), labeler="ana")

    problem = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("checked", checker="Ana")).json()

    assert problem["errors"] == [{"field": "", "reason": "a checked page is checked by someone other than its labeler"}]


def test_get_page_sends_an_etag_that_a_put_must_match() -> None:
    backend = FakeBackend()
    page = backend.store.add()
    etag = _request(backend, "GET", f"/v1/eval/pages/{page.id}").headers["etag"]

    first = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels(), {"If-Match": etag})
    stale = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("draft"), {"If-Match": etag})
    current = _request(backend, "GET", f"/v1/eval/pages/{page.id}").headers["etag"]

    assert first.status_code == 200
    assert first.headers["etag"] == current != etag
    assert stale.status_code == 412
    assert (stale.headers["content-type"], stale.json()["type"]) == ("application/problem+json", "labels_changed")
    assert _writes(backend) == ["put_labels:labeler:ana"]
    assert backend.store.pages[page.id].labels["status"] == "labeled"


# --- pre-fill (§4.10, SPEC-06 §4.4) ---

# The cleaned text of `HTML` is "Blue mug\nBuy\nEUR 19.90".


def _span(value: str, start: int) -> dict[str, JsonValue]:
    return {"shown": True, "ref": "", "value": value, "start": start, "end": start + len(value)}


# Role C's claim of a field the page does not show.
_ABSENT: dict[str, JsonValue] = {"shown": False, "ref": "", "value": "", "start": 0, "end": 0}


def test_prefill_stores_and_returns_a_draft_of_the_grounded_normalized_values() -> None:
    client = ScriptedClient({"fields": {"title": _span("Blue mug", 0), "price": _span("EUR 19.90", 13)}})
    backend = FakeBackend(llm=client)
    page = backend.store.add()

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == 200
    draft: dict[str, JsonValue] = {
        "label_version": 1,
        "status": "draft",
        "labeler": None,
        "checker": None,
        "prefill_source": "llm:fake-fast",
        "fields": {
            "title": {"value": "Blue mug", "absent": False, "locator": "text:0-8", "distractors": []},
            "price": {
                "value": {"amount": "19.90", "currency": "EUR"},
                "absent": False,
                "locator": "text:13-22",
                "distractors": [],
            },
        },
        "rows": [],
        "notes": "",
    }
    assert response.json() == draft
    assert (backend.store.pages[page.id].labels, _writes(backend)) == (draft, ["put_labels:labeler:None"])
    # The stored draft is valid labels, and its tag is what a labeler's PUT sends back.
    parse_labels(draft, "detail", SPECS)
    tag = _request(backend, "GET", f"/v1/eval/pages/{page.id}").headers["ETag"]
    assert response.headers["ETag"] == tag
    (request,) = client.requests
    assert (request.prompt_kind, request.model_class, request.job_id) == ("c_prefill", "fast", None)
    assert "<page_text>\nBlue mug\nBuy\nEUR 19.90\n</page_text>" in request.user


LISTING_HTML = (
    "<html><body><h1>Mugs</h1><ul>"
    + "".join(
        f'<li class="card"><h3><a href="/p/{n}">Mug {n}</a></h3><span>{n}.50 EUR</span><p>Acme {n}</p></li>'
        for n in (1, 2, 3)
    )
    + "</ul></body></html>"
).encode()


def test_prefill_of_a_listing_labels_its_blocks_rows_in_page_order_and_its_page_fields() -> None:
    specs = {
        "url": FieldSpec(type=FieldType.URL, scope="row", schema_org="Product.url"),
        "brand": FieldSpec(type=FieldType.TEXT, scope="row"),
        "heading": FieldSpec(type=FieldType.TEXT, scope="page"),
    }
    blocks: dict[str, JsonValue] = {
        "claims": [
            {"block": 2, "field": "brand", "value": "Acme 3"},
            {"block": 0, "field": "brand", "value": "Acme 1"},
            {"block": 1, "field": "brand", "value": "Acme 9"},  # not in its block: ungrounded
        ]
    }
    client = ScriptedClient(blocks, {"fields": {"heading": _span("Mugs", 0)}})
    backend = FakeBackend(llm=client, specs=specs)
    page = backend.store.add(page_kind="listing", body=LISTING_HTML)

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == 200
    body = response.json()
    # A block whose claims are all dropped labels no field, so it is no row; the item URL is never asked.
    assert [row["fields"]["brand"]["value"] for row in body["rows"]] == ["Acme 1", "Acme 3"]
    assert body["fields"] == {"heading": {"value": "Mugs", "absent": False, "locator": "text:0-4", "distractors": []}}
    parse_labels(body, "listing", specs)
    listing, detail = client.requests
    assert (listing.prompt_kind, detail.prompt_kind) == ("c_prefill", "c_prefill")
    assert "[0] Mug 1 1.50 EUR Acme 1" in listing.user
    assert "url" not in json.dumps(listing.output_schema)


def test_capture_runs_eval_capture_into_dev_and_reports_outcomes() -> None:
    capture_id, page_id = CaptureId(uuid7()), EvalPageId(uuid7())
    backend = FakeBackend(capture_result=[Captured(1, capture_id, page_id, 200, "ok", None), Skipped(2, "robots")])
    urls = [PAGE_URL, "https://store.test/private"]

    response = _request(
        backend,
        "POST",
        "/v1/eval/capture",
        _capture_body(urls),
    )

    assert response.status_code == 200
    assert backend.captures == [
        (
            [
                PageRequest(1, PAGE_URL, "item_detail", "custom_store"),
                PageRequest(2, "https://store.test/private", "item_detail", "custom_store"),
            ],
            "detail",
        )
    ]
    assert response.json() == {
        "outcomes": [
            {
                "kind": "captured",
                "n": 1,
                "capture_id": str(capture_id),
                "page_id": str(page_id),
                "status_code": 200,
                "block_class": "ok",
                "error": None,
            },
            {"kind": "skipped", "n": 2, "reason": "robots"},
        ]
    }
