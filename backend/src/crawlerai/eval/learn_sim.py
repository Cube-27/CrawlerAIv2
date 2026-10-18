"""The learning simulation (evaluation spec, "Learning simulation"): what learning would make of each dev host's
first pages, without a database run or a job.

Each host's pages (a host is the final URL's, per schema) are replayed cold in capture order through the engine, as
`replay_split` replays them, and the first `pages` of them are both the learning sample and the pages the config is
validated on: the dev split holds too few pages per host for a held-out set of its own, so this measures what
induction and role A cover, not how a config generalizes (a held-out page is a page learning never read). A page
list shorter than `MIN_HELD_OUT` is repeated to that length, which validates on the same pages as before.

Role A abstains unless asked to run: its first call is counted, with the characters of the request as the measure of
its cost, and answers no step. A host is **zero-touch** when its config activates with no role A call. Only
aggregates are reported: by category, the hosts, the zero-touch and activated shares, the config fields per host and
role A's calls.
"""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import cycle, islice
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.config_ir.held_out import StoredCandidate, StoredPage, StoredRecord, facts_of, published_of, read_bundle
from crawlerai.config_ir.induction import SamplePage
from crawlerai.config_ir.learning import Target, learn_config
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.validation import MIN_HELD_OUT, HeldOutPage
from crawlerai.db.models import CaptureId, FetchMethod
from crawlerai.eval.engine import PipelineEngine
from crawlerai.eval.replay import RecordedLLM, RecordingMissing, RecordingUnreadable
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalStore
from crawlerai.llm.client import LLMClient, LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.llm.pricing import default_pricing
from crawlerai.normalize.base import Ok
from crawlerai.resolve.records import RecordContent
from crawlerai.resolve.types import ExtractionResult, FieldSet
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CorruptBundle

# Role A's prompt kinds (SPEC-08 §4.6).
ROLE_A: Final = frozenset({"a_synth", "a_repair"})
FIRST_CALL: Final = "a_synth"
# The most role A calls a simulation makes when role A runs live and no other bound is given.
ROLE_A_CALLS: Final = 100
# An estimate of role A's input tokens from its characters: about four characters per token of English text and
# markup, the providers' rule of thumb. Role A's cost is reported as an estimate for that reason.
CHARS_PER_TOKEN: Final = 4
_MILLION: Final = 1_000_000
# A step role A abstains with: no expression, so it parses as no selector and verifies nothing.
NO_STEP: Final[dict[str, JsonValue]] = {
    "selector": "xpath",
    "expression": "",
    "when_type": "",
    "source": "",
    "post": [],
}


@dataclass(frozen=True, slots=True)
class HostRun:
    """What learning made of one host's pages: its config's field count (0 when none activated) and role A's calls."""

    category: str
    page_kind: str
    pages: int
    activated: bool
    fields: int
    role_a_calls: int
    role_a_chars: int

    @property
    def zero_touch(self) -> bool:
        return self.activated and self.role_a_calls == 0


class RoleACounter:
    """An `LLMClient` that counts role A's first calls and their characters, answering role A from `role_a` or, without
    one, with no step; every other call goes to `other` (role C, replayed). Repairs are not counted: an abstaining role
    A's repairs say nothing of a live one's."""

    def __init__(self, other: LLMClient, role_a: LLMClient | None) -> None:
        self._other = other
        self._role_a = role_a
        self.calls = 0
        self.chars = 0

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        if req.prompt_kind not in ROLE_A:
            return await self._other.complete_json(req, check)
        if req.prompt_kind == FIRST_CALL:
            self.calls += 1
            self.chars += len(req.system) + len(req.user)
        if self._role_a is not None:
            return await self._role_a.complete_json(req, check)
        return LLMResponse(
            data=_abstained(req.output_schema),
            provider="none",
            model="none",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            request_hash=request_hash(req),
        )


def _abstained(output_schema: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """A reply in the request's shape with no step for any target."""
    properties = output_schema.get("properties")
    data: dict[str, JsonValue] = {"fields": []}
    if isinstance(properties, dict) and "listing" in properties:
        data["listing"] = {"row": NO_STEP, "fields": []}
    return data


@dataclass(frozen=True, slots=True)
class _Page:
    row: EvalPageRow
    bundle: CaptureBundle

    @property
    def host(self) -> str:
        return urlsplit(self.bundle.manifest.final_url).hostname or ""


async def simulate(
    store: EvalStore,
    engine: PipelineEngine,
    *,
    pages: int,
    live: LLMClient | None,
    role_a: LLMClient | None,
    max_chars: int,
) -> list[HostRun]:
    """One `HostRun` per (host, schema) of the store's split, from its first `pages` pages in capture order. Role C's
    calls are answered from the recordings, then by `live` (`RecordedLLM`); role A's by `role_a`, or not at all."""
    recorded = RecordedLLM(store, live)
    by_host: dict[tuple[str, str], list[_Page]] = defaultdict(list)
    for row in await store.list_pages():
        page = await _loaded(store, row)
        if page is not None:
            by_host[(page.host, row.schema_name)].append(page)
    runs = []
    for (_, schema_name), found in sorted(by_host.items()):
        ordered = sorted(found, key=lambda p: (p.bundle.manifest.fetched_at, p.row.capture_id))[:pages]
        runs.append(await _host_run(engine, engine.schema(schema_name), ordered, recorded, role_a, max_chars))
    return runs


async def _loaded(store: EvalStore, row: EvalPageRow) -> _Page | None:
    try:
        return _Page(row, await store.get_bundle(row.capture_id))
    except (EvalNotFound, ObjectNotFound, CorruptBundle):
        return None  # a page whose bundle is gone is dropped, as `replay_split` drops it


async def _host_run(
    engine: PipelineEngine,
    schema: SchemaDef,
    pages: Sequence[_Page],
    recorded: LLMClient,
    role_a: LLMClient | None,
    max_chars: int,
) -> HostRun:
    stored = [s for page in pages if (s := await _stored(engine, schema, page, recorded)) is not None]
    counter = RoleACounter(recorded, role_a)
    activated, fields = False, 0
    if stored:
        # The fetch method a config names does not change what its steps extract.
        fetch: FetchMethod = "http" if stored[0].bundle.manifest.method == "http" else "browser"
        target = Target(schema, pages[0].host, fetch, None)
        held_out = list(islice(cycle([s.held_out for s in stored]), max(MIN_HELD_OUT, len(stored))))
        validated = await learn_config(
            counter, target, stored, held_out, engine.data.vocabulary, max_chars, absent_from=stored
        )
        activated = validated.ir is not None
        fields = config_fields(validated.ir)
    return HostRun(
        category=pages[0].row.category,
        page_kind=schema.page_kind,
        pages=len(stored),
        activated=activated,
        fields=fields,
        role_a_calls=counter.calls,
        role_a_chars=counter.chars,
    )


def config_fields(ir: ExtractionConfigIR | None) -> int:
    """How many fields a config runs steps for: its page fields, its row fields and a listing's `next`."""
    if ir is None:
        return 0
    listing = ir.listing
    return len(ir.fields) + (0 if listing is None else len(listing.fields) + (listing.next is not None))


async def _stored(engine: PipelineEngine, schema: SchemaDef, page: _Page, llm: LLMClient) -> StoredPage | None:
    """The page replayed cold, as learning reads a stored page; None when a recording it needs is missing."""
    try:
        result = await engine.replay_page(page.bundle, schema, None, llm, "adhoc")
    except (RecordingMissing, RecordingUnreadable):
        return None
    parsed, ctx = await asyncio.to_thread(read_bundle, page.bundle)
    records = _records(schema, result)
    candidates = [_stored_candidate(c, result) for c in result.candidates if isinstance(c.normalized, Ok)]
    facts, rows = facts_of(schema, [r.data for r in records], candidates)
    published, published_rows = published_of(schema, records)
    return StoredPage(
        HeldOutPage(CaptureId(page.row.capture_id), parsed, ctx, facts, rows),
        SamplePage(parsed, ctx, published, published_rows),
        page.bundle,
        stated=frozenset(c.field for c in candidates),
        asked_llm=bool(result.llm_calls),
    )


def _records(schema: SchemaDef, result: ExtractionResult) -> list[StoredRecord]:
    """The records the extraction stores, in order: a detail page's one, or one per listing row holding the page's
    fields too (`resolve.records`)."""
    entity: FieldSet = result.entity or {}
    if schema.page_kind != "listing":
        return [_record(schema, entity)] if entity else []
    return [_record(schema, {**entity, **row}) for row in result.rows]


def _record(schema: SchemaDef, fields: FieldSet) -> StoredRecord:
    content = RecordContent.of(schema, fields)
    locators = {name: meta.locator for name, meta in content.field_meta.items() if meta.locator}
    return StoredRecord(content.data, locators)


def _stored_candidate(candidate: Candidate, result: ExtractionResult) -> StoredCandidate:
    value = candidate.normalized.value if isinstance(candidate.normalized, Ok) else None
    chosen = _chosen(candidate, result)
    return StoredCandidate(candidate.entity_id, candidate.field, value, candidate.source_kind, chosen)


def _chosen(candidate: Candidate, result: ExtractionResult) -> bool:
    entities = [result.entity or {}, *result.rows]
    return any(outcome.chosen == candidate for fields in entities for outcome in fields.values())


def usd_per_char(model: str) -> float | None:
    """Role A's estimated input price per character on the strong `model` today, or None without a price."""
    price = default_pricing().call_usd("anthropic", model, _MILLION, 0, datetime.now(UTC).date())
    return None if price is None else float(price) / _MILLION / CHARS_PER_TOKEN


def summary(runs: Sequence[HostRun], usd_per_char: float | None) -> dict[str, JsonValue]:
    """The simulation's aggregates by category and overall; role A's cost estimated from its characters at
    `usd_per_char` when given."""
    groups: dict[str, list[HostRun]] = defaultdict(list)
    for run in runs:
        groups[run.category].append(run)
        groups["all"].append(run)
    return {category: _aggregate(found, usd_per_char) for category, found in sorted(groups.items())}


def _aggregate(runs: Sequence[HostRun], usd_per_char: float | None) -> dict[str, JsonValue]:
    hosts = len(runs)
    chars = sum(r.role_a_chars for r in runs)
    return {
        "hosts": hosts,
        "pages_per_host": round(sum(r.pages for r in runs) / hosts, 2),
        "zero_touch": round(sum(r.zero_touch for r in runs) / hosts, 3),
        "activated": round(sum(r.activated for r in runs) / hosts, 3),
        "fields_per_host": round(sum(r.fields for r in runs) / hosts, 2),
        "role_a_hosts": sum(r.role_a_calls > 0 for r in runs),
        "role_a_calls": sum(r.role_a_calls for r in runs),
        "role_a_chars": chars,
        "role_a_usd_estimate": None if usd_per_char is None else round(chars * usd_per_char, 2),
    }
