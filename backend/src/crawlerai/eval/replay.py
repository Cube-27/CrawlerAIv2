"""The replay harness (SPEC-03 §4.5, ARCHITECTURE §15, G7, INV-10): the only path from eval captures to metrics.

`replay_split` replays every checked page of a store's split through an `Engine` and returns the cases that
`build_report` (`crawlerai.eval.metrics`) scores. Every LLM call goes through `RecordedLLM`, which answers from the
split's recorded responses, so a replay reads nothing but the bundle, the page's config snapshot and the
recordings: two replays of one engine version give byte-identical results.

`Engine` is the seam for SPEC-05: its `replay_page` is the function the worker calls, with SPEC-03's signature; the
engine holds its calibration, which `version` names (`core.engine_version`). `LLMRequest`, `LLMResponse` and
`LLMClient` are the part of SPEC-06's client that recording needs. SPEC-06 brings the full types to
`crawlerai.llm.client`; these then go, and SPEC-05's `ExtractionResult` and SPEC-04's `SchemaDef` replace
`PageOutput` and `SchemaFields` (as in `metrics`).
"""

import json
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from crawlerai.db.models import ExtractionMode
from crawlerai.eval.labels import from_pydantic, parse_labels
from crawlerai.eval.metrics import ConfigFieldStatus, EvalCase, PageOutput, ReplayFailed, SchemaFields
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalStore
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CorruptBundle, sha256_hex


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LLMRequest(_Model):
    prompt_kind: str
    model_class: Literal["fast", "strong"]
    system: str
    user: str
    output_schema: dict[str, JsonValue]  # JSON Schema of the response


class LLMResponse(_Model):
    data: dict[str, JsonValue]
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    request_hash: str


class LLMClient(Protocol):
    async def complete_json(self, req: LLMRequest) -> LLMResponse: ...


class RecordingMissing(LookupError):
    """A replay asked for a response that was never recorded, and no provider may be called."""


def request_key(req: LLMRequest) -> str:
    """sha256 of (role, model, prompt, schema) (§4.5) as a canonical JSON array: an array keeps the parts apart, and
    sorted keys make the schema's key order irrelevant. The model is the requested class; the provider picks the
    concrete model after the request exists (SPEC-06 failover), so the key can't depend on it."""
    parts = [req.prompt_kind, req.model_class, req.system, req.user, req.output_schema]
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_hex(canonical.encode())


class RecordedLLM:
    """An `LLMClient` that answers from the store's recordings. On a miss it calls `live` and records the response,
    or raises `RecordingMissing` when `live` is `None`, as in CI. Only custodian credentials open a hidden or fresh
    store (C1), so recording on those splits happens in the protected job or on a custodian machine.

    A recording is JSON parsed into an `LLMResponse`: data, never code."""

    def __init__(self, store: EvalStore, live: LLMClient | None) -> None:
        self._store = store
        self._live = live

    async def complete_json(self, req: LLMRequest) -> LLMResponse:
        key = request_key(req)
        recorded = await self._store.llm_cache_get(key)
        if recorded is not None:
            return LLMResponse.model_validate_json(recorded)
        if self._live is None:
            raise RecordingMissing(f"no recorded response for {key}")
        response = await self._live.complete_json(req)
        await self._store.llm_cache_put(key, response.model_dump_json().encode())
        return response


class ConfigSnapshot(BaseModel):
    """The site's active config as `eval_page.config_snapshot` holds it: the `extraction_config` row's `ir` and
    `field_status` (ARCHITECTURE §6, §12). Other columns of the row pass through to the engine."""

    model_config = ConfigDict(frozen=True, extra="allow")

    ir: dict[str, JsonValue]
    field_status: dict[str, ConfigFieldStatus] = {}


class Engine(Protocol):
    @property
    def version(self) -> str: ...

    def schema(self, name: str) -> SchemaFields:
        """The schema named `name`; `LookupError` when there is none."""
        ...

    async def replay_page(
        self,
        bundle: CaptureBundle,
        schema: SchemaFields,
        config: ConfigSnapshot | None,
        llm: LLMClient,
        mode: ExtractionMode,
    ) -> PageOutput: ...


async def replay_split(
    store: EvalStore, engine: Engine, schema_filter: str | None = None, live: LLMClient | None = None
) -> list[EvalCase]:
    """Replay every `checked` page of the store's split (of schema `schema_filter`, if given), in page order.

    A page with its site's config snapshot replays in `config` mode with that config, any other cold (`adhoc`, no
    config). A missing or corrupt bundle, an invalid snapshot or a missing recording drops the page as a
    `ReplayFailed` case, which the `n_pages` gate catches (§4.11). A schema the engine doesn't know, or labels that
    don't fit it, stop the run: those are setup errors, not pages to drop.
    """
    llm = RecordedLLM(store, live)
    cases = []
    for page in await store.list_pages(schema_filter, "checked"):
        schema = engine.schema(page.schema_name)
        if schema.page_kind != page.page_kind:
            raise ValueError(f"eval page {page.id} is a {page.page_kind} page; schema {schema.name} is not")
        output, config_status = await _replay(store, engine, llm, page, schema)
        cases.append(
            EvalCase(
                page_id=str(page.id),
                category=page.category,
                schema_def=schema,
                labels=parse_labels(page.labels, schema.page_kind, schema.fields),
                output=output,
                config_status=config_status,
            )
        )
    return cases


async def _replay(
    store: EvalStore, engine: Engine, llm: LLMClient, page: EvalPageRow, schema: SchemaFields
) -> tuple[PageOutput | ReplayFailed, dict[str, ConfigFieldStatus]]:
    try:
        bundle = await store.get_bundle(page.capture_id)
    except (EvalNotFound, ObjectNotFound, CorruptBundle) as e:
        return ReplayFailed(error=f"bundle unavailable: {type(e).__name__}: {e}"), {}
    config = None
    if page.config_snapshot is not None:
        try:
            config = ConfigSnapshot.model_validate(page.config_snapshot)
        except ValidationError as e:
            reasons = "; ".join(f"{err.path}: {err.reason}" for err in map(from_pydantic, e.errors()))
            return ReplayFailed(error=f"invalid config_snapshot: {reasons}"), {}
    mode: ExtractionMode = "adhoc" if config is None else "config"
    try:
        output = await engine.replay_page(bundle, schema, config, llm, mode)
    except RecordingMissing as e:
        return ReplayFailed(error=f"recording missing: {e}"), {}
    return output, {} if config is None else config.field_status
