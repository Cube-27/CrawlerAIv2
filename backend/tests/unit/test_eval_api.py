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
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.acquire.types import FetchPolicy
from crawlerai.api.app import create_app
from crawlerai.api.auth import require_api_key
from crawlerai.api.routers import eval as eval_router
from crawlerai.core.ids import uuid7
from crawlerai.core.settings import IMPERSONATE_DEFAULT, Settings
from crawlerai.db.models import ApiKeyId, CaptureId, EvalCategory, EvalPageId, EvalRunId, PageKind, SchemaId, Split
from crawlerai.eval.cli import Captured, EvalCliError, Outcome, PageRequest, Skipped
from crawlerai.eval.labels import LabelStatus, parse_labels
from crawlerai.eval.store import (
    DevEvalStore,
    EvalNotFound,
    EvalPageRow,
    EvalRunRow,
    LabelPass,
    Labels,
    LabelsChanged,
)
from crawlerai.llm.client import (
    OutputInvalid,
    ProviderRefused,
    ProviderUnavailable,
)
from crawlerai.llm.providers.fake import ScriptedClient
from crawlerai.schemas.types import FieldSpec, FieldType
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, CorruptBundle, Headers, sha256_hex

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
        self, labels: Labels | None = None, labeler: str | None = None, page_kind: PageKind = "detail"
    ) -> EvalPageRow:
        bundle = _bundle()
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
        _capture_body([PAGE_URL], split),
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

    engine = create_async_engine(settings.database_url.get_secret_value())

    backend = eval_router.DevLabelingBackend(settings, engine, ScriptedClient())

    assert type(backend.store) is DevEvalStore
    assert backend.store.split == "dev"
    asyncio.run(engine.dispose())


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
    unset = {"description": None, "required": False, "scope": "row", "schema_org": None, "vocab": None}
    unset |= {"scheme": None, "item": None, "fields": None, "key": None}
    assert body["fields"] == {"title": {"type": "text", **unset}, "price": {"type": "money", **unset}}


@pytest.mark.parametrize(
    "href",
    [
        "javascript:buy()",
        "java&#x09;script:buy()",
    ],
)
def test_get_page_drops_javascript_urls_as_url_parsing_reads_them(href: str) -> None:
    # WHATWG URL parsing strips leading C0 controls and spaces and removes every tab and newline, so each of these
    # is a `javascript:` URL in a browser.
    backend = FakeBackend()
    page = backend.store.add()
    backend.store.bundles[page.capture_id] = _bundle(f'<html><body><a href="{href}">Buy</a></body></html>'.encode())

    response = _request(backend, "GET", f"/v1/eval/pages/{page.id}")

    assert response.json()["bundle_html"].endswith("<body><a>Buy</a></body></html>")


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


@pytest.mark.parametrize("error", [ObjectNotFound("no object"), CorruptBundle("not a bundle")])
def test_get_page_with_an_unreadable_capture_is_a_problem(error: Exception) -> None:
    backend = FakeBackend()
    page = backend.store.add()
    backend.store.bundles[page.capture_id] = error

    response = _request(backend, "GET", f"/v1/eval/pages/{page.id}")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert (response.json()["type"], response.json()["detail"]) == (
        "capture_unreadable",
        f"the capture {page.capture_id} of dev eval page {page.id} cannot be read",
    )


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


def test_checker_cannot_be_the_labeler() -> None:
    backend = FakeBackend()
    page = backend.store.add(_stored(_labels()), labeler="ana")

    problem = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("checked", checker="Ana")).json()

    assert problem["errors"] == [{"field": "", "reason": "a checked page is checked by someone other than its labeler"}]


def test_checker_pass_matches_the_labeler_casefolded_and_keeps_the_stored_name() -> None:
    backend = FakeBackend()
    page = backend.store.add(_stored(_labels()), labeler="ana")

    response = _request(
        backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("checked", labeler="ANA", checker="ben")
    )

    assert response.status_code == 200
    assert backend.store.pages[page.id].labels["labeler"] == "ana"


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


@pytest.mark.parametrize(("if_match", "status"), [("*", 200), ('"other", W/"x"', 412)])
def test_if_match_takes_a_star_or_a_list_of_strong_tags(if_match: str, status: int) -> None:
    backend = FakeBackend()
    page = backend.store.add()

    response = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels(), {"If-Match": if_match})

    assert response.status_code == status


def test_a_pass_racing_another_store_is_a_conflict() -> None:
    backend = FakeBackend()
    page = backend.store.add(_stored(_labels()), labeler="ana")
    get_page = backend.store.get_page

    async def read_then_relabel(page_id: EvalPageId) -> EvalPageRow:
        read = await get_page(page_id)  # the labeler stores a new pass right after the checker's read
        backend.store.pages[page_id] = read.model_copy(update={"labels": _stored(_labels(labeler="cleo"))})
        return read

    backend.store.get_page = read_then_relabel  # type: ignore[method-assign]

    response = _request(backend, "PUT", f"/v1/eval/pages/{page.id}/labels", _labels("checked", checker="ben"))

    assert response.status_code == 409
    assert response.json()["type"] == "labels_changed"
    assert backend.store.pages[page.id].labels["labeler"] == "cleo"


@pytest.mark.parametrize(
    ("stored", "labeler", "error"),
    [
        (None, "ana", {"field": "status", "reason": "only a labeled page can be checked"}),
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


def test_normalize_is_not_implemented_yet() -> None:
    backend = FakeBackend()
    page = backend.store.add()

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/normalize", {"field": "price", "raw_text": "x"})

    assert response.status_code == 501
    assert response.json()["type"] == "not_implemented"


# --- pre-fill (§4.10, SPEC-06 §4.4) ---

# The cleaned text of `HTML` is "Blue mug\nBuy\nEUR 19.90".


def _span(value: str, start: int) -> dict[str, JsonValue]:
    return {"value": value, "start": start, "end": start + len(value)}


# Role C's claim of a field the page does not show.
_ABSENT: dict[str, JsonValue] = {"value": "", "start": 0, "end": 0}


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


def test_prefill_leaves_null_ungrounded_and_declined_values_unlabeled() -> None:
    # A pre-fill never claims a field is absent: that is the labeler's call (G2).
    specs = SPECS | {"sku": FieldSpec(type=FieldType.IDENTIFIER, scheme="sku")}
    client = ScriptedClient({"fields": {"title": _ABSENT, "price": _span("Buy", 9), "sku": _span("Q-9", 0)}})
    backend = FakeBackend(llm=client, specs=specs)
    page = backend.store.add()

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == 200
    assert (response.json()["fields"], response.json()["prefill_source"]) == ({}, "llm:fake-fast")


def test_prefill_never_asks_for_a_row_mapped_field() -> None:
    # SPEC-13 §4.9: role C is never asked for a row-mapped field; the labeler labels its rows.
    variants = FieldSpec.model_validate(
        {
            "type": "list",
            "schema_org": "Product.offers",
            "key": ["sku"],
            "item": {
                "type": "object",
                "fields": {"sku": {"type": "identifier", "scheme": "sku", "schema_org": "Offer.sku"}},
            },
        }
    )
    client = ScriptedClient({"fields": {"title": _span("Blue mug", 0), "price": _ABSENT}})
    backend = FakeBackend(llm=client, specs=SPECS | {"variants": variants})
    page = backend.store.add()

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == 200
    (request,) = client.requests
    assert "variants" not in request.user
    assert "title" in request.user


def test_prefill_of_a_listing_labels_rows_in_page_order_and_page_fields() -> None:
    specs = {
        "title": FieldSpec(type=FieldType.TEXT, scope="row"),
        "heading": FieldSpec(type=FieldType.TEXT, scope="page"),
    }
    reply: dict[str, JsonValue] = {
        "rows": [{"title": _span("Buy", 9)}, {"title": _ABSENT}, {"title": _span("Blue mug", 0)}],
        "page": {"heading": _span("EUR 19.90", 13)},
    }
    client = ScriptedClient(reply)
    backend = FakeBackend(llm=client, specs=specs)
    page = backend.store.add(page_kind="listing")

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == 200
    body = response.json()
    assert [row["fields"]["title"]["value"] for row in body["rows"]] == ["Buy", "Blue mug"]
    assert body["fields"] == {
        "heading": {"value": "EUR 19.90", "absent": False, "locator": "text:13-22", "distractors": []}
    }
    parse_labels(body, "listing", specs)
    assert client.requests[0].prompt_kind == "c_prefill"


def test_prefill_replaces_a_draft() -> None:
    client = ScriptedClient({"fields": {"title": _span("Blue mug", 0), "price": _ABSENT}})
    backend = FakeBackend(llm=client)
    page = backend.store.add(_stored(_labels("draft")), labeler="ana")

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == 200
    stored = backend.store.pages[page.id]
    assert (stored.labels["prefill_source"], stored.labeler) == ("llm:fake-fast", None)


@pytest.mark.parametrize("status", ["labeled", "checked"])
def test_prefill_never_replaces_a_labeled_pass(status: str) -> None:
    backend = FakeBackend()
    labels = _stored(_labels(status, checker="ben" if status == "checked" else None))
    page = backend.store.add(labels, labeler="ana")

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == 409
    assert (backend.llm.requests, _writes(backend)) == ([], [])


def test_prefill_with_a_stale_if_match_is_refused_before_the_call() -> None:
    backend = FakeBackend()
    page = backend.store.add(_stored(_labels("draft")), labeler="ana")

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill", headers={"If-Match": '"stale"'})

    assert response.status_code == 412
    assert (backend.llm.requests, _writes(backend)) == ([], [])


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (ProviderUnavailable("no provider answered"), 503),
        (ProviderRefused("fake", "fake-fast", 400, "schema refused"), 503),
        (OutputInvalid("at $: not an object"), 502),
    ],
)
def test_prefill_without_a_valid_reply_stores_nothing(failure: Exception, status: int) -> None:
    backend = FakeBackend(llm=ScriptedClient(failure))
    page = backend.store.add()

    response = _request(backend, "POST", f"/v1/eval/pages/{page.id}/prefill")

    assert response.status_code == status
    assert response.json()["detail"] == str(failure)
    assert _writes(backend) == []


def test_prefill_of_an_unknown_page_is_not_found() -> None:
    response = _request(FakeBackend(), "POST", f"/v1/eval/pages/{uuid7()}/prefill")

    assert response.status_code == 404


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
        _capture_body(urls),
    )

    assert response.status_code == 422
    assert (response.json()["type"], response.json()["detail"]) == ("validation", detail)
