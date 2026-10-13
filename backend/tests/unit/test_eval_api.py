"""The labeling API (SPEC-03 §4.10): dev pages only (C1, INV-01), sanitized page HTML, labels validated before
anything is stored, every validation error returned with its field and reason (§4.11). A fake backend stands in for
the dev store and `schema_def`; `tests/db/test_labeling_api.py` runs the same flow against Postgres."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import JsonValue

from crawlerai.acquire.types import FetchPolicy
from crawlerai.api.app import create_app
from crawlerai.api.routers import eval as eval_router
from crawlerai.core.ids import uuid7
from crawlerai.core.settings import IMPERSONATE_DEFAULT, Settings
from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, EvalRunId, PageKind, SchemaId, Split
from crawlerai.eval.cli import Captured, EvalCliError, Outcome, PageRequest, Skipped
from crawlerai.eval.labels import FieldShape, LabelStatus, ScalarShape
from crawlerai.eval.store import DevEvalStore, EvalNotFound, EvalPageRow, EvalRunRow, LabelPass, Labels
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

PAGE_URL = "https://store.test/items/1"
FINAL_URL = "https://store.test/items/1?ref=a"
SCHEMA_ID = SchemaId(uuid7())
SHAPES: dict[str, FieldShape] = {"title": ScalarShape(type="text"), "price": ScalarShape(type="money")}
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
    bundles: dict[CaptureId, CaptureBundle] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    @property
    def split(self) -> Split:
        return "dev"

    def add(self, labels: Labels | None = None, labeler: str | None = None) -> EvalPageRow:
        bundle = _bundle()
        capture_id = CaptureId(bundle.manifest.capture_id)
        page = EvalPageRow(
            capture_id=capture_id,
            split="dev",
            schema_id=SCHEMA_ID,
            schema_name="item_detail",
            page_kind="detail",
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
        return self.bundles[capture_id]

    async def put_labels(self, page_id: EvalPageId, labels: Labels, who: str, pass_: LabelPass) -> None:
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

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None:
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

    async def schema_fields(self, schema_id: SchemaId) -> dict[str, FieldShape]:
        assert schema_id == SCHEMA_ID
        return SHAPES

    async def capture(self, requests: Sequence[PageRequest], page_kind: PageKind) -> list[Outcome]:
        self.captures.append((list(requests), page_kind))
        if isinstance(self.capture_result, EvalCliError):
            raise self.capture_result
        return self.capture_result

    async def aclose(self) -> None:
        pass


def _request(backend: FakeBackend | None, method: str, path: str, body: Any = None) -> httpx.Response:
    app = create_app(eval_ui=backend is not None)
    if backend is not None:
        app.dependency_overrides[eval_router.labeling_backend] = lambda: backend

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
            return await client.request(method, path, json=body)

    return asyncio.run(send())


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


def test_eval_routes_are_not_mounted_without_eval_ui() -> None:
    assert _request(None, "GET", "/v1/eval/pages").status_code == 404
    assert not any(path.startswith("/v1/eval") for path in create_app(eval_ui=False).openapi()["paths"])


def test_list_returns_dev_page_summaries_filtered_by_status() -> None:
    backend = FakeBackend()
    labeled = backend.store.add(_stored(_labels()), labeler="ana")
    backend.store.add()

    response = _request(backend, "GET", "/v1/eval/pages?split=dev&status=labeled&schema=item_detail")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(labeled.id),
            "capture_id": str(labeled.capture_id),
            "split": "dev",
            "schema_name": "item_detail",
            "page_kind": "detail",
            "category": "custom_store",
            "status": "labeled",
            "labeler": "ana",
            "checker": None,
        }
    ]


@pytest.mark.parametrize("split", ["hidden", "fresh"])
def test_hidden_and_fresh_splits_are_refused_without_touching_a_store(split: str) -> None:
    backend = FakeBackend()

    listing = _request(backend, "GET", f"/v1/eval/pages?split={split}")
    capture = _request(
        backend,
        "POST",
        "/v1/eval/capture",
        {
            "split": split,
            "schema": "item_detail",
            "page_kind": "detail",
            "category": "custom_store",
            "urls": [PAGE_URL],
        },
    )

    assert (listing.status_code, capture.status_code) == (422, 422)
    assert backend.store.calls == []
    assert backend.captures == []


def test_backend_serves_the_dev_store_even_with_private_settings(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://app@127.0.0.1/main",
            "object_store": "fs:///" + (tmp_path / "main").as_posix().lstrip("/"),
            "eval_private_database_url": "postgresql+asyncpg://custodian@127.0.0.1/private",
            "eval_private_object_store": "fs:///" + (tmp_path / "private").as_posix().lstrip("/"),
            "impersonate": IMPERSONATE_DEFAULT,
        }
    )

    backend = eval_router.DevLabelingBackend(settings)

    assert type(backend.store) is DevEvalStore
    assert backend.store.split == "dev"
    asyncio.run(backend.aclose())


def test_get_page_returns_sanitized_html_with_a_base_at_the_capture_url() -> None:
    backend = FakeBackend()
    page = backend.store.add()

    response = _request(backend, "GET", f"/v1/eval/pages/{page.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["bundle_html"] == (
        '<html><head><title>Item</title><base href="https://store.test/items/1?ref=a"></head>'
        '<body><h1 class="t">Blue mug</h1><a>Buy</a><img src="/mug.png"><p>EUR 19.90</p></body></html>'
    )
    assert (body["url"], body["final_url"], body["labels"], body["text"]) == (PAGE_URL, FINAL_URL, None, None)


def test_get_page_resolves_the_page_own_base_against_the_capture_url() -> None:
    backend = FakeBackend()
    page = backend.store.add()
    bundle = _bundle(b'<html><head><base href="/shop/" target="_blank"></head><body></body></html>')
    backend.store.bundles[page.capture_id] = bundle

    response = _request(backend, "GET", f"/v1/eval/pages/{page.id}")

    assert response.json()["bundle_html"] == (
        '<html><head><base href="https://store.test/shop/"></head><body></body></html>'
    )


def test_get_unknown_page_is_a_404_problem() -> None:
    response = _request(FakeBackend(), "GET", f"/v1/eval/pages/{uuid7()}")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "not_found"


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


def test_a_labeler_pass_names_its_labeler() -> None:
    backend = FakeBackend()
    page = backend.store.add()

    problem = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("draft", labeler=None)).json()

    assert problem["errors"] == [{"field": "labeler", "reason": "a labeler pass names its labeler"}]


def test_checker_pass_confirms_a_labeled_page() -> None:
    backend = FakeBackend()
    page = backend.store.add(_stored(_labels()), labeler="ana")

    response = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("checked", checker="ben"))

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["checker"]) == ("checked", "ben")
    assert _writes(backend) == ["put_labels:checker:ben"]


def test_checker_cannot_be_the_labeler() -> None:
    backend = FakeBackend()
    page = backend.store.add(_stored(_labels()), labeler="ana")

    problem = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("checked", checker="Ana")).json()

    assert problem["errors"] == [{"field": "", "reason": "a checked page is checked by someone other than its labeler"}]


@pytest.mark.parametrize(
    ("stored", "labeler", "error"),
    [
        (None, "ana", {"field": "status", "reason": "only a labeled page can be checked"}),
        (_stored(_labels("draft")), "ana", {"field": "status", "reason": "only a labeled page can be checked"}),
        (_stored(_labels()), "cleo", {"field": "labeler", "reason": "a checker pass keeps the page's labeler (ana)"}),
    ],
)
def test_checker_pass_needs_a_labeled_page_and_keeps_its_labeler(
    stored: Labels | None, labeler: str, error: dict[str, str]
) -> None:
    backend = FakeBackend()
    page = backend.store.add(stored, labeler="ana" if stored else None)

    response = _request(
        backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("checked", labeler=labeler, checker="ben")
    )

    assert response.status_code == 422
    assert response.json()["errors"] == [error]
    assert _writes(backend) == []


@pytest.mark.parametrize("action", ["normalize", "prefill"])
def test_normalize_and_prefill_are_not_implemented_yet(action: str) -> None:
    backend = FakeBackend()
    page = backend.store.add()
    body = {"field": "price", "raw_text": "EUR 19.90"} if action == "normalize" else None

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/{action}", body)

    assert response.status_code == 501
    assert response.json()["type"] == "not_implemented"


def test_capture_runs_eval_capture_into_dev_and_reports_outcomes() -> None:
    capture_id, page_id = CaptureId(uuid7()), EvalPageId(uuid7())
    backend = FakeBackend(capture_result=[Captured(1, capture_id, page_id, 200, "ok", None), Skipped(2, "robots")])
    urls = [PAGE_URL, "https://store.test/private"]

    response = _request(
        backend,
        "POST",
        "/v1/eval/capture",
        {"split": "dev", "schema": "item_detail", "page_kind": "detail", "category": "custom_store", "urls": urls},
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


@pytest.mark.parametrize(
    ("urls", "result", "detail"),
    [
        (["ftp://store.test/a"], [], "not an http or https URL with a host: URL 1"),
        ([PAGE_URL], EvalCliError("no active schema named item_detail"), "no active schema named item_detail"),
    ],
)
def test_capture_input_errors_are_validation_problems(
    urls: list[str], result: list[Outcome] | EvalCliError, detail: str
) -> None:
    backend = FakeBackend(capture_result=result)

    response = _request(
        backend,
        "POST",
        "/v1/eval/capture",
        {"split": "dev", "schema": "item_detail", "page_kind": "detail", "category": "custom_store", "urls": urls},
    )

    assert response.status_code == 422
    assert (response.json()["type"], response.json()["detail"]) == ("validation", detail)
