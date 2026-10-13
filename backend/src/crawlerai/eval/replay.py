"""The replay harness (SPEC-03 §4.5, ARCHITECTURE §15, G7, INV-10): the only path from eval captures to metrics.

`replay_split` replays every checked page of a store's split through an `Engine` and returns the cases that
`build_report` (`crawlerai.eval.metrics`) scores. Every LLM call goes through `RecordedLLM`, which answers from the
split's recorded responses, so a replay reads nothing but the bundle, the page's config snapshot and the
recordings: two replays of one engine version give byte-identical results.

`Engine` is the seam to SPEC-05: its `replay_page` runs `resolve.pipeline.extract_page`, the function the worker
runs, with SPEC-03's signature (`eval.engine`); the engine holds its calibration, which `version` names
(`core.engine_version`). Its `ExtractionResult` is scored as the `PageOutput` that `metrics` reads.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.core.capture import BlockClass
from crawlerai.db.models import ExtractionMode, FieldStatus, SourceKind
from crawlerai.eval.labels import from_pydantic, parse_labels
from crawlerai.eval.metrics import EvalCase, FieldOutput, PageOutput, ReplayFailed, SchemaFields
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalStore
from crawlerai.llm.client import LLMClient, LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.normalize.base import Ok
from crawlerai.resolve.types import ExtractionResult, FieldOutcome, FieldSet
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CorruptBundle


class RecordingMissing(LookupError):
    """A replay asked for a response that was never recorded, and no provider may be called."""


class RecordingUnreadable(ValueError):
    """A recorded response that does not read back: not an `LLMResponse`, or its object is gone from the store."""


class RecordedLLM:
    """An `LLMClient` that answers from the store's recordings. On a miss it calls `live` and records the response,
    or raises `RecordingMissing` when `live` is `None`, as in CI. Only custodian credentials open a hidden or fresh
    store (C1), so recording on those splits happens in the protected job or on a custodian machine.

    A recording is JSON parsed into an `LLMResponse`: data, never code."""

    def __init__(self, store: EvalStore, live: LLMClient | None) -> None:
        self._store = store
        self._live = live

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        key = request_hash(req)
        try:
            recorded = await self._store.llm_cache_get(key)
        except ObjectNotFound as e:
            raise RecordingUnreadable(f"recording {key}: its object is missing") from e
        if recorded is not None:
            try:
                return LLMResponse.model_validate_json(recorded)
            except ValidationError as e:
                raise RecordingUnreadable(f"recording {key} is not an LLMResponse: {e}") from e
        if self._live is None:
            raise RecordingMissing(f"no recorded response for {key}")
        response = await self._live.complete_json(req, check)
        await self._store.llm_cache_put(key, response.model_dump_json().encode())
        return response


class ConfigSnapshot(BaseModel):
    """The site's active config as `eval_page.config_snapshot` holds it: the `extraction_config` row's `ir` and
    `field_status` (ARCHITECTURE §6, §12). Other columns of the row pass through to the engine. An `ir` the IR model
    refuses makes the snapshot invalid, and the page is dropped."""

    model_config = ConfigDict(frozen=True, extra="allow")

    ir: ExtractionConfigIR
    field_status: dict[str, FieldStatus] = {}


class Engine(Protocol):
    @property
    def version(self) -> str: ...

    def schema(self, name: str) -> SchemaDef:
        """The schema named `name`; `LookupError` when there is none."""
        ...

    async def replay_page(
        self,
        bundle: CaptureBundle,
        schema: SchemaDef,
        config: ConfigSnapshot | None,
        llm: LLMClient,
        mode: ExtractionMode,
    ) -> ExtractionResult: ...


async def replay_split(
    store: EvalStore, engine: Engine, schema_filter: str | None = None, live: LLMClient | None = None
) -> list[EvalCase]:
    """Replay every `checked` page of the store's split (of schema `schema_filter`, if given), in page order.

    A page with its site's config snapshot replays in `config` mode with that config, any other cold (`adhoc`, no
    config). A missing or corrupt bundle, an invalid snapshot, or a recording that is missing or unreadable drops the
    page as a `ReplayFailed` case, which the `n_pages` gate catches (§4.11). A schema the engine doesn't know, or
    labels that don't fit it, stop the run: those are setup errors, not pages to drop.
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
                schema_def=schema_fields(schema),
                labels=parse_labels(page.labels, schema.page_kind, schema.fields),
                output=output,
                config_status=config_status,
            )
        )
    return cases


def schema_fields(schema: SchemaDef) -> SchemaFields:
    """The parts of a schema that metrics read: its fields, required fields and required groups."""
    return SchemaFields(
        name=schema.name,
        page_kind=schema.page_kind,
        fields=schema.fields,
        required=frozenset(name for name, spec in schema.fields.items() if spec.required),
        required_groups=tuple(frozenset(group) for group in schema.required_groups),
    )


def page_output(result: ExtractionResult, block_class: BlockClass) -> PageOutput:
    """What metrics score of an extraction: each field's status, value, evidence and the values each source kind
    offered, and the page's LLM calls."""
    return PageOutput(
        block_class=block_class,
        mode=result.mode,
        llm_calls=len(result.llm_calls),
        fields=_field_outputs(result.entity or {}),
        rows=tuple(_field_outputs(row) for row in result.rows),
    )


def _field_outputs(fields: FieldSet) -> dict[str, FieldOutput]:
    return {
        name: FieldOutput(
            status=outcome.status, value=outcome.value, evidence=outcome.evidence, offered=_offered(outcome)
        )
        for name, outcome in fields.items()
    }


def _offered(outcome: FieldOutcome) -> dict[SourceKind, tuple[JsonValue, ...]]:
    # Kept candidates normalized (validity, SPEC-05 §4.7); kinds sorted so two replays dump the same bytes (INV-10).
    offered: dict[SourceKind, list[JsonValue]] = {}
    for candidate in outcome.kept:
        if isinstance(candidate.normalized, Ok):
            offered.setdefault(candidate.source_kind, []).append(candidate.normalized.value)
    return {kind: tuple(offered[kind]) for kind in sorted(offered)}


async def _replay(
    store: EvalStore, engine: Engine, llm: LLMClient, page: EvalPageRow, schema: SchemaDef
) -> tuple[PageOutput | ReplayFailed, dict[str, FieldStatus]]:
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
        result = await engine.replay_page(bundle, schema, config, llm, mode)
    except RecordingMissing as e:
        return ReplayFailed(error=f"recording missing: {e}"), {}
    except RecordingUnreadable as e:
        return ReplayFailed(error=f"recording unreadable: {e}"), {}
    return page_output(result, bundle.manifest.block_class), {} if config is None else config.field_status
