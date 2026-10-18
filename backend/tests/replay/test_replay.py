"""The replay harness (evaluation spec, INV-10): `RecordedLLM` recording and replaying, `replay_split` over a synthetic
dev split, and the determinism test: two runs give byte-identical JSON."""

import asyncio
from typing import Literal, get_args

import pytest
from pydantic import JsonValue

from crawlerai.core.ids import uuid7
from crawlerai.db.models import (
    CaptureId,
    EvalCategory,
    EvalPageId,
    EvalRunId,
    ExtractionMode,
    SchemaId,
    Split,
)
from crawlerai.eval.labels import LabelStatus
from crawlerai.eval.metrics import (
    ReplayFailed,
)
from crawlerai.eval.replay import ConfigSnapshot, RecordedLLM, replay_split
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalRunRow, LabelPass, Labels
from crawlerai.llm.client import LLMClient, LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.resolve.types import ExtractionResult, FieldOutcome, LLMCallRecord
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, decode, encode
from tests.replay.captures import capture

SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic_detail",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "summary": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.description"),
    },
)


class MemoryStore:
    """An in-memory `EvalStore`: pages, encoded bundles and LLM cache entries in dicts."""

    def __init__(self) -> None:
        self._split: Split = "dev"
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


def outcome(status: Literal["published", "missing"], reason: str | None, value: str | None) -> FieldOutcome:
    return FieldOutcome(
        status=status,
        reason=reason,
        value=value,
        evidence="llm_grounded" if value else None,
        confidence=None,
        calibrated=False,
        source_kind="llm" if value else None,
        locator="text:0-1" if value else None,
        derived_by=None,
        chosen=None,
        rejected=(),
    )


class StubEngine:
    """A synthetic engine: the summary from one LLM call. It reads nothing but the bundle and the LLM."""

    version = "stub+cal.none"

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
        html = bundle.body.decode()
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
        fields = {"summary": outcome("published", None, summary)}
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
    return capture(f"<html><body><h1>Item {n}</h1><p>{'text ' * n}</p></body></html>".encode())


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


REQUEST = LLMRequest(
    prompt_kind="c_extract_detail",
    model_class="fast",
    system="system prompt",
    user="user prompt",
    output_schema={"type": "object", "required": ["a"], "additionalProperties": False},
    max_output_tokens=64,
    job_id=None,
)


def test_a_hit_returns_the_recording_without_calling_the_provider() -> None:
    store, live = MemoryStore(), LiveLLM()
    recorded = asyncio.run(RecordedLLM(store, live).complete_json(REQUEST))
    again = LiveLLM()
    assert asyncio.run(RecordedLLM(store, again).complete_json(REQUEST)) == recorded
    assert asyncio.run(RecordedLLM(store, None).complete_json(REQUEST)) == recorded
    assert again.calls == []


def test_a_recording_is_data_not_code() -> None:
    # A recording is parsed as JSON into an `LLMResponse`; anything else is refused, never evaluated.
    store = MemoryStore()
    store.cache[request_hash(REQUEST)] = b"__import__('os').system('true')"
    call = RecordedLLM(store, None).complete_json(REQUEST)
    with pytest.raises(ValueError, match="Invalid JSON"):
        asyncio.run(call)


def test_drafts_and_labeled_pages_replay_when_asked() -> None:
    store = MemoryStore()
    pages = [asyncio.run(add_page(store, n, status=status)) for n, status in enumerate(get_args(LabelStatus), start=1)]
    asyncio.run(add_page(store, 9, status="checked", schema_name="other_schema"))
    assert len(asyncio.run(replay_split(store, StubEngine(), SCHEMA.name, live=LiveLLM()))) == 1
    cases = asyncio.run(
        replay_split(store, StubEngine(), SCHEMA.name, live=LiveLLM(), statuses=frozenset(get_args(LabelStatus)))
    )
    assert [case.page_id for case in cases] == sorted(str(page.id) for page in pages)


def dropped_error(store: MemoryStore, *, provider: bool = True) -> str:
    """The error of the store's one page, which the replay dropped."""
    [case] = asyncio.run(replay_split(store, StubEngine(), live=LiveLLM() if provider else None))
    assert isinstance(case.output, ReplayFailed)
    return case.output.error


def test_a_missing_recording_drops_the_page() -> None:
    store = MemoryStore()
    asyncio.run(add_page(store, 1))
    assert dropped_error(store, provider=False).startswith("recording missing:")
