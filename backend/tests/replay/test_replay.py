"""The replay harness (SPEC-03 §4.5, INV-10): `RecordedLLM` recording and replaying, `replay_split` over a synthetic
dev split, and the determinism test: two runs give byte-identical JSON."""

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, EvalRunId, ExtractionMode, SchemaId, Split
from crawlerai.eval.labels import LabelStatus, ScalarShape
from crawlerai.eval.metrics import EvalCase, FieldOutput, PageOutput, ReplayFailed, SchemaFields, build_report
from crawlerai.eval.replay import (
    ConfigSnapshot,
    LLMClient,
    LLMRequest,
    LLMResponse,
    RecordedLLM,
    RecordingMissing,
    replay_split,
    request_key,
)
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalRunRow, LabelPass, Labels
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, decode, encode, sha256_hex

SCHEMA = SchemaFields(
    name="synthetic_detail",
    page_kind="detail",
    fields={"title": ScalarShape(type="text"), "summary": ScalarShape(type="text")},
    required=frozenset({"title"}),
)


class MemoryStore:
    """An in-memory `EvalStore` of one split: pages, encoded bundles and LLM cache entries in dicts."""

    def __init__(self, split: Split = "dev") -> None:
        self._split: Split = split
        self.pages: dict[EvalPageId, EvalPageRow] = {}
        self.blobs: dict[CaptureId, bytes] = {}
        self.cache: dict[str, bytes] = {}

    @property
    def split(self) -> Split:
        return self._split

    async def list_pages(self, schema_name: str | None = None, status: LabelStatus | None = None) -> list[EvalPageRow]:
        return [
            page
            for _, page in sorted(self.pages.items())
            if (schema_name is None or page.schema_name == schema_name)
            and (status is None or page.labels.get("status") == status)
        ]

    async def get_page(self, page_id: EvalPageId) -> EvalPageRow:
        return self.pages[page_id]

    async def get_bundle(self, capture_id: CaptureId) -> CaptureBundle:
        if capture_id not in self.blobs:
            raise EvalNotFound(capture_id)
        return decode(self.blobs[capture_id])

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId:
        capture_id = CaptureId(bundle.manifest.capture_id)
        self.blobs[capture_id] = encode(bundle)
        return capture_id

    async def put_page(self, page: EvalPageRow) -> EvalPageId:
        self.pages[page.id] = page
        return page.id

    async def put_labels(self, page_id: EvalPageId, labels: Labels, who: str, pass_: LabelPass) -> None:
        raise NotImplementedError

    async def put_run(self, run: EvalRunRow) -> EvalRunId:
        raise NotImplementedError

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None:
        raise NotImplementedError

    async def llm_cache_get(self, key: str) -> bytes | None:
        return self.cache.get(key)

    async def llm_cache_put(self, key: str, value: bytes) -> None:
        self.cache[key] = value

    async def aclose(self) -> None:
        pass


class LiveLLM:
    """Stands in for a provider: its answer depends on the prompt, but its latency changes from call to call, as a
    real provider's does, so only a recorded response replays identically."""

    def __init__(self) -> None:
        self.calls: list[LLMRequest] = []

    async def complete_json(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        return LLMResponse(
            data={"summary": f"summary of {len(req.user)} chars"},
            provider="provider-a",
            model="model-a",
            tokens_in=len(req.user),
            tokens_out=4,
            latency_ms=100 + len(self.calls),
            request_hash=request_key(req),
        )


class StubEngine:
    """A synthetic engine: the title from the page's `<h1>`, the summary from one LLM call. It reads nothing but the
    bundle and the LLM, as SPEC-05's `replay_page` will. Records what the harness passed it."""

    version = "stub+cal.none"

    def __init__(self) -> None:
        self.seen: list[tuple[ConfigSnapshot | None, ExtractionMode]] = []

    def schema(self, name: str) -> SchemaFields:
        if name != SCHEMA.name:
            raise LookupError(name)
        return SCHEMA

    async def replay_page(
        self,
        bundle: CaptureBundle,
        schema: SchemaFields,
        config: ConfigSnapshot | None,
        llm: LLMClient,
        mode: ExtractionMode,
    ) -> PageOutput:
        self.seen.append((config, mode))
        html = bundle.body.decode()
        heading = re.search(r"<h1>(.*?)</h1>", html)
        response = await llm.complete_json(
            LLMRequest(
                prompt_kind="c_extract_detail",
                model_class="fast",
                system="Extract the summary.",
                user=html,
                output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            )
        )
        fields = {"summary": FieldOutput(status="published", value=response.data["summary"], evidence="llm_grounded")}
        if heading is not None:
            fields["title"] = FieldOutput(status="published", value=heading.group(1), evidence="structured")
        return PageOutput(block_class=bundle.manifest.block_class, mode=mode, llm_calls=1, fields=fields)


def bundle(n: int) -> CaptureBundle:
    body = f"<html><body><h1>Item {n}</h1><p>{'text ' * n}</p></body></html>".encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=f"https://shop.example.com/p/{n}",
        final_url=f"https://shop.example.com/p/{n}",
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


def labels(n: int, status: LabelStatus = "checked") -> dict[str, JsonValue]:
    return {
        "label_version": 1,
        "status": status,
        "labeler": "labeler-a" if status != "draft" else None,
        "checker": "checker-b" if status == "checked" else None,
        "fields": {
            "title": {"value": f"Item {n}", "absent": False},
            "summary": {"value": None, "absent": True},
        },
    }


async def add_page(
    store: MemoryStore,
    n: int,
    *,
    status: LabelStatus = "checked",
    schema_name: str = SCHEMA.name,
    config_snapshot: dict[str, JsonValue] | None = None,
) -> EvalPageRow:
    capture_id = await store.put_capture(bundle(n), "custom_store")
    page = EvalPageRow(
        capture_id=capture_id,
        split=store.split,
        schema_id=SchemaId(uuid7()),
        schema_name=schema_name,
        page_kind="detail",
        category="custom_store",
        labels=labels(n, status),
        config_snapshot=config_snapshot,
    )
    await store.put_page(page)
    return page


def dump(cases: list[EvalCase]) -> str:
    return json.dumps([case.model_dump(mode="json") for case in cases], sort_keys=True)


# --- determinism (INV-10) ---


def test_two_runs_over_a_split_are_byte_identical() -> None:
    store = MemoryStore()
    for n in range(1, 6):
        asyncio.run(add_page(store, n))
    live = LiveLLM()

    first = asyncio.run(replay_split(store, StubEngine(), live=live))
    # The second run may not reach the provider at all: every response comes from the recording.
    second = asyncio.run(replay_split(store, StubEngine(), live=None))

    assert len(live.calls) == 5
    assert dump(first) == dump(second)
    first_report = build_report(first, "dev", engine_version=StubEngine.version, git_sha="a" * 40)
    second_report = build_report(second, "dev", engine_version=StubEngine.version, git_sha="a" * 40)
    assert first_report.model_dump_json() == second_report.model_dump_json()
    assert first_report.n_pages == 5


def test_a_recorded_run_and_a_live_run_agree() -> None:
    # Recording changes nothing about the answer: the first (recording) run gives what the live client gave.
    store = MemoryStore()
    asyncio.run(add_page(store, 3))
    [case] = asyncio.run(replay_split(store, StubEngine(), live=LiveLLM()))
    assert isinstance(case.output, PageOutput)
    assert case.output.fields["summary"].value == f"summary of {len(bundle(3).body)} chars"
    assert case.output.fields["title"].value == "Item 3"


# --- RecordedLLM ---


REQUEST = LLMRequest(
    prompt_kind="c_extract_detail",
    model_class="fast",
    system="system prompt",
    user="user prompt",
    output_schema={"type": "object", "required": ["a"]},
)


def test_a_miss_calls_the_provider_and_records_the_response() -> None:
    store, live = MemoryStore(), LiveLLM()
    response = asyncio.run(RecordedLLM(store, live).complete_json(REQUEST))
    assert live.calls == [REQUEST]
    assert store.cache == {request_key(REQUEST): response.model_dump_json().encode()}


def test_a_hit_returns_the_recording_without_calling_the_provider() -> None:
    store, live = MemoryStore(), LiveLLM()
    recorded = asyncio.run(RecordedLLM(store, live).complete_json(REQUEST))
    again = LiveLLM()
    assert asyncio.run(RecordedLLM(store, again).complete_json(REQUEST)) == recorded
    assert asyncio.run(RecordedLLM(store, None).complete_json(REQUEST)) == recorded
    assert again.calls == []


def test_a_miss_without_a_provider_raises() -> None:
    llm = RecordedLLM(MemoryStore(), None)
    call = llm.complete_json(REQUEST)
    with pytest.raises(RecordingMissing, match=request_key(REQUEST)):
        asyncio.run(call)


def test_a_recording_is_data_not_code() -> None:
    # A recording is parsed as JSON into an `LLMResponse`; anything else is refused, never evaluated.
    store = MemoryStore()
    store.cache[request_key(REQUEST)] = b"__import__('os').system('true')"
    call = RecordedLLM(store, None).complete_json(REQUEST)
    with pytest.raises(ValueError, match="Invalid JSON"):
        asyncio.run(call)


def test_the_key_is_sha256_of_the_canonical_request() -> None:
    canonical = json.dumps(
        ["c_extract_detail", "fast", "system prompt", "user prompt", {"required": ["a"], "type": "object"}],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert request_key(REQUEST) == hashlib.sha256(canonical.encode()).hexdigest()


def test_the_key_ignores_schema_key_order() -> None:
    reordered = REQUEST.model_copy(update={"output_schema": {"required": ["a"], "type": "object"}})
    assert request_key(reordered) == request_key(REQUEST)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_kind", "c_extract_listing"),
        ("model_class", "strong"),
        ("system", "system prompt "),
        ("user", "user prompt."),
        ("output_schema", {"type": "object"}),
    ],
)
def test_each_part_of_the_request_changes_the_key(field: str, value: Any) -> None:
    assert request_key(REQUEST.model_copy(update={field: value})) != request_key(REQUEST)


@given(st.text(), st.text(), st.text(), st.text())
def test_parts_cannot_run_into_each_other(system_a: str, user_a: str, system_b: str, user_b: str) -> None:
    # Moving text between two parts never keeps the key: the parts are a JSON array, not a concatenation.
    a = REQUEST.model_copy(update={"system": system_a, "user": user_a})
    b = REQUEST.model_copy(update={"system": system_b, "user": user_b})
    assert (request_key(a) == request_key(b)) == ((system_a, user_a) == (system_b, user_b))


# --- replay_split ---


def test_only_checked_pages_replay() -> None:
    store = MemoryStore()
    checked = asyncio.run(add_page(store, 1))
    asyncio.run(add_page(store, 2, status="labeled"))
    asyncio.run(add_page(store, 3, status="draft"))
    assert [case.page_id for case in asyncio.run(replay_split(store, StubEngine(), live=LiveLLM()))] == [
        str(checked.id)
    ]


def test_the_schema_filter_selects_pages() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1, schema_name="other_schema"))
    kept = asyncio.run(add_page(store, 2))
    cases = asyncio.run(replay_split(store, StubEngine(), schema_filter=SCHEMA.name, live=LiveLLM()))
    assert [case.page_id for case in cases] == [str(kept.id)]


def test_a_case_carries_the_page_and_its_labels() -> None:
    store = MemoryStore()
    page = asyncio.run(add_page(store, 1))
    [case] = asyncio.run(replay_split(store, StubEngine(), live=LiveLLM()))
    assert (case.page_id, case.category, case.schema_def) == (str(page.id), "custom_store", SCHEMA)
    assert case.labels.model_dump(mode="json", exclude_defaults=True) == {
        "label_version": 1,
        "status": "checked",
        "labeler": "labeler-a",
        "checker": "checker-b",
        "fields": {"title": {"value": "Item 1", "absent": False}, "summary": {"absent": True}},
    }


def test_without_a_config_snapshot_the_page_replays_cold() -> None:
    store, engine = MemoryStore(), StubEngine()
    asyncio.run(add_page(store, 1))
    [case] = asyncio.run(replay_split(store, engine, live=LiveLLM()))
    assert engine.seen == [(None, "adhoc")]
    assert case.config_status == {}


def test_a_config_snapshot_replays_in_config_mode_and_gives_field_status() -> None:
    store, engine = MemoryStore(), StubEngine()
    snapshot: dict[str, JsonValue] = {"ir": {"fields": {}}, "field_status": {"title": "corroborated"}}
    asyncio.run(add_page(store, 1, config_snapshot=snapshot))
    [case] = asyncio.run(replay_split(store, engine, live=LiveLLM()))
    assert engine.seen == [(ConfigSnapshot(ir={"fields": {}}, field_status={"title": "corroborated"}), "config")]
    assert case.config_status == {"title": "corroborated"}


def dropped_error(store: MemoryStore, *, provider: bool = True) -> str:
    """The error of the store's one page, which the replay dropped."""
    [case] = asyncio.run(replay_split(store, StubEngine(), live=LiveLLM() if provider else None))
    assert isinstance(case.output, ReplayFailed)
    return case.output.error


def test_an_invalid_config_snapshot_drops_the_page() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1, config_snapshot={"ir": {}, "field_status": {"title": "trusted"}}))
    assert dropped_error(store).startswith("invalid config_snapshot: field_status.title: ")


def test_a_missing_bundle_drops_the_page() -> None:
    store = MemoryStore()
    page = asyncio.run(add_page(store, 1))
    del store.blobs[page.capture_id]
    assert dropped_error(store).startswith("bundle unavailable: EvalNotFound")


def test_a_corrupt_bundle_drops_the_page() -> None:
    store = MemoryStore()
    page = asyncio.run(add_page(store, 1))
    store.blobs[page.capture_id] = b"not a bundle"
    assert dropped_error(store).startswith("bundle unavailable: CorruptBundle")


def test_a_missing_object_drops_the_page() -> None:
    class NoObjects(MemoryStore):
        async def get_bundle(self, capture_id: CaptureId) -> CaptureBundle:
            raise ObjectNotFound(str(capture_id))

    store = NoObjects()
    asyncio.run(add_page(store, 1))
    assert dropped_error(store).startswith("bundle unavailable: ObjectNotFound")


def test_a_missing_recording_drops_the_page() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1))
    assert dropped_error(store, provider=False).startswith("recording missing:")


def test_dropped_pages_leave_n_pages() -> None:
    # §4.11: a dropped page counts against `n_pages`, which trips the gate.
    store = MemoryStore()
    pages = [asyncio.run(add_page(store, n)) for n in range(1, 5)]
    del store.blobs[pages[-1].capture_id]
    report = build_report(asyncio.run(replay_split(store, StubEngine(), live=LiveLLM())), "dev", "e", "a" * 40)
    assert report.n_pages == 3


def test_a_schema_the_engine_does_not_know_stops_the_run() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1, schema_name="unknown_schema"))
    run = replay_split(store, StubEngine(), live=LiveLLM())
    with pytest.raises(LookupError, match="unknown_schema"):
        asyncio.run(run)


def test_a_schema_of_another_page_kind_stops_the_run() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1))
    listing = SCHEMA.model_copy(update={"page_kind": "listing"})

    class ListingEngine(StubEngine):
        def schema(self, name: str) -> SchemaFields:
            return listing

    run = replay_split(store, ListingEngine(), live=LiveLLM())
    with pytest.raises(ValueError, match="is a detail page"):
        asyncio.run(run)
