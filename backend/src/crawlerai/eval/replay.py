"""The replay harness (SPEC-03 §4.5, ARCHITECTURE §15, G7, INV-10): the only path from eval captures to metrics.

`replay_split` replays every checked page of a store's split (and, for a dev report that asks, its drafts: D-1461)
through an `Engine` and returns the cases that `build_report` (`crawlerai.eval.metrics`) scores. Every LLM call goes
through `RecordedLLM`, which answers from the split's recorded responses, so a replay reads nothing but the bundle,
the page's config snapshot and the recordings: two replays of one engine version give byte-identical results.

`Engine` is the seam to SPEC-05: its `replay_page` runs `resolve.pipeline.extract_page`, the function the worker
runs, with SPEC-03's signature (`eval.engine`); the engine holds its calibration, which `version` names
(`core.engine_version`). Its `ExtractionResult` is scored as the `PageOutput` that `metrics` reads.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.core.capture import BlockClass
from crawlerai.core.validation import field_error
from crawlerai.db.models import ExtractionMode, FieldStatus, SourceKind
from crawlerai.eval.labels import LabelStatus, parse_labels
from crawlerai.eval.metrics import CHECKED, EvalCase, FieldOutput, PageOutput, ReplayFailed, SchemaFields
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalStore
from crawlerai.llm.client import (
    BudgetExhausted,
    LLMClient,
    LLMFailure,
    LLMRequest,
    LLMResponse,
    ReplyCheck,
    request_hash,
)
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
    or raises `RecordingMissing` when `live` is `None`, as in CI.

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


class CappedLLM:
    """A live client that answers at most `max_calls` requests, then raises `BudgetExhausted` as a job without budget
    does (SPEC-06 §4.7): the fields asked stay missing with `llm_budget`. It bounds what a local dev run spends; a
    recorded response costs nothing and is not counted, as `RecordedLLM` answers it before any live call."""

    def __init__(self, client: LLMClient, max_calls: int) -> None:
        self._client = client
        self._left = max_calls

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        if self._left <= 0:
            raise BudgetExhausted("the run's LLM call cap is reached")
        self._left -= 1
        return await self._client.complete_json(req, check)


class _PageCalls:
    """One page's view of the harness's client: it counts the calls that got no reply (`LLMFailure`), which the
    pipeline turns into missing fields, so a dev report tells the misses that depend on role C (D-1464)."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self.unanswered = 0

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        try:
            return await self._client.complete_json(req, check)
        except LLMFailure:
            self.unanswered += 1
            raise


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
    store: EvalStore,
    engine: Engine,
    schema_filter: str | None = None,
    live: LLMClient | None = None,
    statuses: frozenset[LabelStatus] = CHECKED,
) -> list[EvalCase]:
    """Replay every page of the store's split whose labels are in `statuses` (`checked` unless a dev report asks for
    drafts too, D-1461; of schema `schema_filter`, if given), in page order.

    A page with its site's config snapshot replays in `config` mode with that config, any other cold (`adhoc`, no
    config). A missing or corrupt bundle, an invalid snapshot, or a recording that is missing or unreadable drops the
    page as a `ReplayFailed` case, reported in `n_pages` and the page's error. A schema the engine doesn't know, or
    labels that don't fit it, stop the run: those are setup errors, not pages to drop.
    """
    llm = RecordedLLM(store, live)
    pages = [page for status in sorted(statuses) for page in await store.list_pages(schema_filter, status)]
    cases = []
    for page in sorted(pages, key=lambda page: page.id):
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


def page_output(result: ExtractionResult, block_class: BlockClass, llm_unanswered: int = 0) -> PageOutput:
    """What metrics score of an extraction: each field's status, value, evidence, reason and the values each source
    kind offered, and the page's LLM calls, answered and not."""
    return PageOutput(
        block_class=block_class,
        mode=result.mode,
        llm_calls=len(result.llm_calls),
        llm_unanswered=llm_unanswered,
        fields=_field_outputs(result.entity or {}),
        rows=tuple(_field_outputs(row) for row in result.rows),
    )


def _field_outputs(fields: FieldSet) -> dict[str, FieldOutput]:
    return {
        name: FieldOutput(
            status=outcome.status,
            value=outcome.value,
            evidence=outcome.evidence,
            reason=outcome.reason,
            offered=_offered(outcome),
            # A row-mapped field's rows, each scored per sub-field (SPEC-13 §4.10).
            items=tuple(_field_outputs(row.fields) for row in outcome.items or ()),
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
            reasons = "; ".join(f"{path}: {reason}" for path, reason in map(field_error, e.errors()))
            return ReplayFailed(error=f"invalid config_snapshot: {reasons}"), {}
    mode: ExtractionMode = "adhoc" if config is None else "config"
    calls = _PageCalls(llm)
    try:
        result = await engine.replay_page(bundle, schema, config, calls, mode)
    except RecordingMissing as e:
        return ReplayFailed(error=f"recording missing: {e}"), {}
    except RecordingUnreadable as e:
        return ReplayFailed(error=f"recording unreadable: {e}"), {}
    status = {} if config is None else config.field_status
    return page_output(result, bundle.manifest.block_class, calls.unanswered), status
