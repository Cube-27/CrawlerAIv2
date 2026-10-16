"""The replay harness (SPEC-03 §4.5, INV-10): `RecordedLLM` recording and replaying, `replay_split` over a synthetic
dev split, and the determinism test: two runs give byte-identical JSON."""

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import (
    CaptureId,
    EvalCategory,
    EvalPageId,
    EvalRunId,
    ExtractionMode,
    SchemaId,
    SourceKind,
    Split,
)
from crawlerai.eval.engine import PipelineEngine
from crawlerai.eval.labels import LabelStatus
from crawlerai.eval.metrics import (
    EvalCase,
    FieldOutput,
    PageOutput,
    PrecisionMetrics,
    ReplayFailed,
    SchemaFields,
    Usage,
    build_report,
)
from crawlerai.eval.replay import ConfigSnapshot, RecordedLLM, RecordingMissing, page_output, replay_split
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalRunRow, LabelPass, Labels
from crawlerai.llm.client import LLMClient, LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.normalize.base import Ok
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import Evidence, ExtractionResult, FieldOutcome, LLMCallRecord
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, decode, encode, sha256_hex

SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic_detail",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "summary": FieldSpec(type=FieldType.TEXT, description="d"),
    },
)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)


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

    async def put_labels(
        self, page_id: EvalPageId, labels: Labels, who: str | None, pass_: LabelPass, *, expected: Labels
    ) -> None:
        raise NotImplementedError

    async def put_run(self, run: EvalRunRow) -> EvalRunId:
        raise NotImplementedError

    async def get_run(self, run_id: EvalRunId) -> EvalRunRow:
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

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        self.calls.append(req)
        return LLMResponse(
            data={"summary": f"summary of {len(req.user)} chars"},
            provider="provider-a",
            model="model-a",
            tokens_in=len(req.user),
            tokens_out=4,
            latency_ms=100 + len(self.calls),
            request_hash=request_hash(req),
        )


def published(value: str, evidence: Evidence, source_kind: SourceKind, locator: str) -> FieldOutcome:
    return FieldOutcome(
        status="published",
        reason=None,
        value=value,
        evidence=evidence,
        confidence=None,
        calibrated=False,
        source_kind=source_kind,
        locator=locator,
        derived_by=None,
        chosen=None,
        rejected=(),
    )


class StubEngine:
    """A synthetic engine: the title from the page's `<h1>`, the summary from one LLM call. It reads nothing but the
    bundle and the LLM, as `extract_page` does. Records what the harness passed it."""

    version = "stub+cal.none"

    def __init__(self) -> None:
        self.seen: list[tuple[ConfigSnapshot | None, ExtractionMode]] = []

    def schema(self, name: str) -> SchemaDef:
        if name != SCHEMA.name:
            raise LookupError(name)
        return SCHEMA

    async def replay_page(
        self,
        bundle: CaptureBundle,
        schema: SchemaDef,
        config: ConfigSnapshot | None,
        llm: LLMClient,
        mode: ExtractionMode,
    ) -> ExtractionResult:
        self.seen.append((config, mode))
        html = bundle.body.decode()
        heading = re.search(r"<h1>(.*?)</h1>", html)
        response = await llm.complete_json(
            LLMRequest(
                prompt_kind="c_extract_detail",
                model_class="fast",
                system="Extract the summary.",
                user=html,
                output_schema={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                    "additionalProperties": False,
                },
                max_output_tokens=64,
                job_id=None,
            )
        )
        summary = response.data["summary"]
        assert isinstance(summary, str)
        fields = {"summary": published(summary, "llm_grounded", "llm", "text:0-1")}
        if heading is not None:
            fields["title"] = published(heading.group(1), "structured", "microdata", "microdata:/html/body/h1")
        call = LLMCallRecord(
            prompt_kind="c_extract_detail",
            provider=response.provider,
            model=response.model,
            request_hash=response.request_hash,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
        )
        return ExtractionResult(
            outcome="extracted",
            entity=fields,
            rows=(),
            candidates=(),
            llm_calls=(call,),
            mode=mode,
            record_confidence=None,
        )


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
    output_schema={"type": "object", "required": ["a"], "additionalProperties": False},
    max_output_tokens=64,
    job_id=None,
)


def test_a_miss_calls_the_provider_and_records_the_response() -> None:
    store, live = MemoryStore(), LiveLLM()
    response = asyncio.run(RecordedLLM(store, live).complete_json(REQUEST))
    assert live.calls == [REQUEST]
    assert store.cache == {request_hash(REQUEST): response.model_dump_json().encode()}


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
    with pytest.raises(RecordingMissing, match=request_hash(REQUEST)):
        asyncio.run(call)


def test_a_recording_is_data_not_code() -> None:
    # A recording is parsed as JSON into an `LLMResponse`; anything else is refused, never evaluated.
    store = MemoryStore()
    store.cache[request_hash(REQUEST)] = b"__import__('os').system('true')"
    call = RecordedLLM(store, None).complete_json(REQUEST)
    with pytest.raises(ValueError, match="Invalid JSON"):
        asyncio.run(call)


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
    assert (case.page_id, case.category) == (str(page.id), "custom_store")
    # Metrics read the schema's fields, required fields and groups.
    assert case.schema_def == SchemaFields(
        name="synthetic_detail", page_kind="detail", fields=SCHEMA.fields, required=frozenset({"title"})
    )
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


# A config for SCHEMA that reads the title from the page's `<h1>` (SPEC-08 §4.2).
IR: dict[str, JsonValue] = {
    "ir_version": "1",
    "site": "shop.example.com",
    "schema": {"name": SCHEMA.name},
    "page_kind": "detail",
    "fetch": {"method": "http"},
    "fields": {"title": {"steps": [{"xpath": "normalize-space(//h1)"}], "status": "corroborated"}},
    "listing": None,
    "provenance": {
        "origin": "induced",
        "validated_on": [],
        "learned_at": "2026-10-01T00:00:00Z",
        "engine_version": "test",
    },
}
SNAPSHOT: dict[str, JsonValue] = {"ir": IR, "field_status": {"title": "corroborated"}}


def test_a_config_snapshot_replays_in_config_mode_and_gives_field_status() -> None:
    store, engine = MemoryStore(), StubEngine()
    asyncio.run(add_page(store, 1, config_snapshot=SNAPSHOT))
    [case] = asyncio.run(replay_split(store, engine, live=LiveLLM()))
    assert engine.seen == [(ConfigSnapshot.model_validate(SNAPSHOT), "config")]
    assert case.config_status == {"title": "corroborated"}


def dropped_error(store: MemoryStore, *, provider: bool = True) -> str:
    """The error of the store's one page, which the replay dropped."""
    [case] = asyncio.run(replay_split(store, StubEngine(), live=LiveLLM() if provider else None))
    assert isinstance(case.output, ReplayFailed)
    return case.output.error


def test_an_invalid_config_snapshot_drops_the_page() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1, config_snapshot={"ir": IR, "field_status": {"title": "trusted"}}))
    assert dropped_error(store).startswith("invalid config_snapshot: field_status.title: ")


def test_a_snapshot_whose_ir_the_model_refuses_drops_the_page() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1, config_snapshot={"ir": {**IR, "ir_version": "2"}}))
    error = dropped_error(store)
    assert error.startswith("invalid config_snapshot: ")
    assert "ir_version" in error


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


def test_an_unreadable_recording_drops_the_page() -> None:
    class Garbled(MemoryStore):
        async def llm_cache_get(self, key: str) -> bytes | None:
            return b'{"data": {}}'

    store = Garbled()
    asyncio.run(add_page(store, 1))
    assert dropped_error(store, provider=False).startswith("recording unreadable: recording ")


def test_a_recording_whose_object_is_gone_drops_the_page() -> None:
    class Lost(MemoryStore):
        async def llm_cache_get(self, key: str) -> bytes | None:
            raise ObjectNotFound(key)

    store = Lost()
    asyncio.run(add_page(store, 1))
    assert dropped_error(store, provider=False).endswith("its object is missing")


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
        def schema(self, name: str) -> SchemaDef:
            return listing

    run = replay_split(store, ListingEngine(), live=LiveLLM())
    with pytest.raises(ValueError, match="is a detail page"):
        asyncio.run(run)


# --- the pipeline (SPEC-05 §7: `extract_page` is what `replay_split` runs) ---


def jsonld_page(n: int) -> CaptureBundle:
    node = {"@context": "https://schema.org", "@type": "Product", "name": f"Item {n}"}
    body = f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head></html>'.encode()
    original = bundle(n)
    manifest = original.manifest.model_copy(update={"html_sha256": sha256_hex(body)})
    return original.model_copy(update={"manifest": manifest, "body": body})


def test_the_pipeline_engine_replays_pages_through_extract_page() -> None:
    store = MemoryStore()
    for n in (1, 2):
        page = asyncio.run(add_page(store, n))
        store.blobs[page.capture_id] = encode(jsonld_page(n))
    engine = PipelineEngine(DATA, {SCHEMA.name: SCHEMA})

    first = asyncio.run(replay_split(store, engine, live=None))
    second = asyncio.run(replay_split(store, engine, live=None))

    assert dump(first) == dump(second)
    outputs = [case.output for case in first]
    assert all(isinstance(output, PageOutput) for output in outputs)
    assert [o.fields["title"] for o in outputs if isinstance(o, PageOutput)] == [
        FieldOutput(status="published", value=f"Item {n}", evidence="structured", offered={"jsonld": (f"Item {n}",)})
        for n in (1, 2)
    ]
    report = build_report(first, "dev", engine_version=engine.version, git_sha="a" * 40)
    assert report.n_pages == 2


def test_the_pipeline_engine_replays_a_config_snapshot_in_config_mode() -> None:
    # SPEC-08 §6 "dev replay": a page with its site's config snapshot runs that config, and its config fields'
    # precision is reported per field status.
    store = MemoryStore()
    for n in (1, 2):
        asyncio.run(add_page(store, n, config_snapshot=SNAPSHOT))
    engine = PipelineEngine(DATA, {SCHEMA.name: SCHEMA})

    cases = asyncio.run(replay_split(store, engine, live=None))

    outputs = [case.output for case in cases]
    assert [(o.mode, o.llm_calls, o.fields["title"]) for o in outputs if isinstance(o, PageOutput)] == [
        (
            "config",
            0,
            FieldOutput(
                status="published",
                value=f"Item {n}",
                evidence="config_corroborated",
                offered={"config": (f"Item {n}",)},
            ),
        )
        for n in (1, 2)
    ]
    report = build_report(cases, "dev", engine_version=engine.version, git_sha="a" * 40)
    assert list(report.by_config_status) == ["text|corroborated"]


def test_the_pipeline_engine_knows_only_its_schemas() -> None:
    engine = PipelineEngine(DATA, {SCHEMA.name: SCHEMA})
    with pytest.raises(LookupError, match="other_schema"):
        engine.schema("other_schema")


LISTING = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic_listing",
    page_kind="listing",
    fields={
        "title": SCHEMA.fields["title"],
        "url": FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
        "next_page_url": FieldSpec(type=FieldType.URL, description="d", scope="page"),
    },
)


def test_the_pipeline_engine_scores_a_listing_row_by_row() -> None:
    # SPEC-03 §4.6: engine rows match label rows by URL, whatever their order on the page.
    items = [
        {
            "@type": "ListItem",
            "item": {"@type": "Product", "name": f"Item {n}", "url": f"https://shop.example.com/p/{n}"},
        }
        for n in (2, 1)
    ]
    node = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items}
    original = jsonld_page(1)
    body = f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head></html>'.encode()
    manifest = original.manifest.model_copy(update={"html_sha256": sha256_hex(body)})
    store = MemoryStore()
    capture_id = asyncio.run(
        store.put_capture(original.model_copy(update={"manifest": manifest, "body": body}), "custom_store")
    )
    rows: list[JsonValue] = [
        {
            "fields": {
                "title": {"value": f"Item {n}", "absent": False},
                "url": {"value": f"https://shop.example.com/p/{n}", "absent": False},
            }
        }
        for n in (1, 2)
    ]
    page_labels = labels(1) | {"fields": {"next_page_url": {"value": None, "absent": True}}, "rows": rows}
    page = EvalPageRow(
        capture_id=capture_id,
        split="dev",
        schema_id=LISTING.id,
        schema_name=LISTING.name,
        page_kind="listing",
        category="custom_store",
        labels=page_labels,
        config_snapshot=None,
    )
    asyncio.run(store.put_page(page))

    cases = asyncio.run(replay_split(store, PipelineEngine(DATA, {LISTING.name: LISTING}), live=None))
    report = build_report(cases, "dev", engine_version="e", git_sha="a" * 40)

    assert report.pages is not None
    cells = {(j.entity, j.field, j.cell) for j in report.pages[0].judgments}
    assert cells == {
        ("page", "next_page_url", "TN"),
        ("row[0]", "title", "TP"),
        ("row[0]", "url", "TP"),
        ("row[1]", "title", "TP"),
        ("row[1]", "url", "TP"),
    }


class GroundingLLM:
    """Stands in for a provider answering role C: the page text's `Item <n>` line as the title, nothing else. Its
    latency changes from call to call, so only a recorded response replays identically."""

    def __init__(self) -> None:
        self.calls: list[LLMRequest] = []

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        self.calls.append(req)
        text = req.user.split("<page_text>\n", 1)[1].rsplit("\n</page_text>", 1)[0]
        title = next(line for line in text.split("\n") if line.startswith("Item "))
        start = text.index(title)
        # Every asked field is claimed, empty when the page does not show it (SPEC-06 §4.4).
        asked = json.loads(json.dumps(req.output_schema))["properties"]["fields"]["required"]
        claims: dict[str, JsonValue] = {name: {"value": "", "start": 0, "end": 0} for name in asked}
        claims["title"] = {"value": title, "start": start, "end": start + len(title)}
        return LLMResponse(
            data={"fields": claims},
            provider="provider-a",
            model="model-a",
            tokens_in=len(req.user),
            tokens_out=12,
            latency_ms=100 + len(self.calls),
            request_hash=request_hash(req),
        )


def test_role_c_values_replay_from_the_recording_into_the_llm_grounded_bucket() -> None:
    # SPEC-06 §7: the bucket appears in the dev report, and a replay with the recordings calls no provider.
    store = MemoryStore()
    for n in (1, 2):
        asyncio.run(add_page(store, n))  # no structured data: the title is only in the page text
    engine = PipelineEngine(DATA, {SCHEMA.name: SCHEMA})
    live = GroundingLLM()

    first = asyncio.run(replay_split(store, engine, live=live))
    second = asyncio.run(replay_split(store, engine, live=None))

    assert [req.prompt_kind for req in live.calls] == ["c_extract_detail", "c_extract_detail"]
    assert dump(first) == dump(second)
    outputs = [case.output for case in second]
    assert [o.fields["title"] for o in outputs if isinstance(o, PageOutput)] == [
        FieldOutput(status="published", value=f"Item {n}", evidence="llm_grounded", offered={"llm": (f"Item {n}",)})
        for n in (1, 2)
    ]
    report = build_report(second, "dev", engine_version=engine.version, git_sha="a" * 40)
    assert report.by_bucket["text|llm_grounded"] == PrecisionMetrics(precision=1.0, n=2)
    assert report.usage["adhoc"] == Usage(llm_calls_per_1k_pages=1000.0, n=2)


def _title(kind: SourceKind, value: str, n: int) -> Candidate:
    return Candidate(
        field="title",
        entity_id=PAGE,
        source_kind=kind,
        raw=value,
        normalized=Ok(value),
        locator=f"meta:og:x{n}" if kind == "og" else f"jsonld:0:$['x{n}']",
        independent=True,
    )


def test_a_field_output_offers_the_kept_values_of_each_kind() -> None:
    # SPEC-05 §4.11: precedence is fitted on every kind's kept values, not only the published one.
    chosen, agreeing, lower = _title("og", "A", 0), _title("jsonld", "A", 1), _title("og", "B", 2)
    outcome = published("A", "agreed", "og", chosen.locator).model_copy(
        update={"chosen": chosen, "kept": (chosen, agreeing, lower), "rejected": ((lower, "precedence"),)}
    )
    result = ExtractionResult(
        outcome="extracted",
        entity={"title": outcome},
        rows=(),
        candidates=(),
        llm_calls=(),
        mode="adhoc",
        record_confidence=None,
    )

    output = page_output(result, "ok")

    assert list(output.fields["title"].offered.items()) == [("jsonld", ("A",)), ("og", ("A", "B"))]


OFFER_SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic_offer",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(
            type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"
        ),
        "availability": FieldSpec(
            type=FieldType.ENUM, description="d", vocab="schema:ItemAvailability", schema_org="Offer.availability"
        ),
    },
)


_OFFER_LABELS: dict[str, JsonValue] = {
    "title": {"value": "Item 1", "absent": False},
    "price": {"value": None, "absent": True},
    "availability": {"value": None, "absent": True},
}


class PriceLLM:
    """Stands in for a provider answering role C with the page text's price as written (`$12.50`), nothing else."""

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        text = req.user.split("<page_text>\n", 1)[1].rsplit("\n</page_text>", 1)[0]
        asked = json.loads(json.dumps(req.output_schema))["properties"]["fields"]["required"]
        claims: dict[str, JsonValue] = {name: {"value": "", "start": 0, "end": 0} for name in asked}
        start = text.index("$12.50")
        claims["price"] = {"value": "$12.50", "start": start, "end": start + len("$12.50")}
        return LLMResponse(
            data={"fields": claims},
            provider="provider-a",
            model="model-a",
            tokens_in=len(req.user),
            tokens_out=12,
            latency_ms=100,
            request_hash=request_hash(req),
        )


def test_an_aggregate_offer_s_price_read_only_by_role_c_stays_an_offer_split() -> None:
    # SPEC-05 §4.8, D-0440 (accuracy class R1b): the AggregateOffer holds the page's offer fields (availability), so
    # it is the anchor Offer; a price only role C reads is no value of that Offer and does not publish, even though
    # the page's stated currency (USD) settles the `$` it is written with (R1a).
    aggregate = {
        "@type": "AggregateOffer",
        "lowPrice": "12.50",
        "highPrice": "15.00",
        "priceCurrency": "USD",
        "availability": "https://schema.org/InStock",
    }
    node = {"@context": "https://schema.org", "@type": "Product", "name": "Item 1", "offers": aggregate}
    script = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    body = f"<html><head>{script}</head><body><h1>Item 1</h1><p>From $12.50 today.</p></body></html>".encode()
    original = bundle(1)
    manifest = original.manifest.model_copy(update={"html_sha256": sha256_hex(body)})
    store = MemoryStore()
    capture_id = asyncio.run(
        store.put_capture(original.model_copy(update={"manifest": manifest, "body": body}), "custom_store")
    )
    page = EvalPageRow(
        capture_id=capture_id,
        split="dev",
        schema_id=OFFER_SCHEMA.id,
        schema_name=OFFER_SCHEMA.name,
        page_kind="detail",
        category="custom_store",
        labels=labels(1) | {"fields": _OFFER_LABELS},
    )
    asyncio.run(store.put_page(page))
    engine = PipelineEngine(DATA, {OFFER_SCHEMA.name: OFFER_SCHEMA})

    asyncio.run(replay_split(store, engine, live=PriceLLM()))
    [case] = asyncio.run(replay_split(store, engine, live=None))

    assert isinstance(case.output, PageOutput)
    assert case.output.llm_calls == 1
    assert case.output.fields["price"] == FieldOutput(
        status="conflict", offered={"llm": ({"amount": "12.50", "currency": "USD"},)}
    )
    assert case.output.fields["availability"].status == "published"
