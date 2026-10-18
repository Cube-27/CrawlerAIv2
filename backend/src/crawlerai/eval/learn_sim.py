"""The learning simulation (evaluation spec, "Learning simulation"): what learning would make of each dev host's
first pages, without a database run or a job.

Each host's pages (a host is the final URL's, per schema) are replayed cold in capture order through the engine, as
`replay_split` replays them, and the first `pages` of them are the learning sample. The config is validated on the
host's later pages (held out: pages learning never read), or, when it has none or `same-page` is asked, on the
sample itself, which measures what induction and role A cover, not how a config generalizes. A validation list
shorter than `MIN_HELD_OUT` is repeated to that length.

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
from functools import reduce
from itertools import cycle, islice
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.config_ir.executability import CLASSES, Executability, class_counts
from crawlerai.config_ir.held_out import StoredCandidate, StoredPage, StoredRecord, facts_of, published_of, read_bundle
from crawlerai.config_ir.induction import SamplePage
from crawlerai.config_ir.learning import Target, learn_config
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.validation import MIN_HELD_OUT, HeldOutPage
from crawlerai.db.models import CaptureId, FetchMethod
from crawlerai.eval.engine import PipelineEngine
from crawlerai.eval.replay import RecordedLLM, RecordingMissing, RecordingUnreadable
from crawlerai.eval.store import EvalNotFound, EvalPageRow, EvalStore
from crawlerai.llm.client import AnsweredCall, LLMClient, LLMFailure, LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.llm.pricing import CacheTokens, default_pricing
from crawlerai.normalize.base import Ok
from crawlerai.resolve.records import RecordContent
from crawlerai.resolve.types import ExtractionResult, FieldSet
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CorruptBundle

Validation = Literal["held-out", "same-page"]

# Role A's prompt kinds: its first request and its repairs (learning-configs, "Induction, then role A synthesis").
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
    executability: dict[Executability, int]
    role_a_calls: int
    role_a_chars: int
    role_a_tokens: "RoleATokens"
    held_out: int = 0  # the distinct pages the config was validated on that learning did not read

    @property
    def zero_touch(self) -> bool:
        return self.activated and self.role_a_calls == 0


@dataclass(frozen=True, slots=True)
class RoleATokens:
    """The tokens a live role A's answered calls used, and what the provider charged for them at the model's prices
    (None when a call has no price): `tokens_in` are the uncached input tokens."""

    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    usd: float | None = 0.0

    @property
    def used(self) -> bool:
        return bool(self.tokens_in + self.tokens_out + self.cache_read + self.cache_write)

    def combined(self, other: "RoleATokens") -> "RoleATokens":
        """The sum; its cost is unknown when either has none."""
        usd = None if self.usd is None or other.usd is None else self.usd + other.usd
        return RoleATokens(
            self.tokens_in + other.tokens_in,
            self.tokens_out + other.tokens_out,
            self.cache_read + other.cache_read,
            self.cache_write + other.cache_write,
            usd,
        )

    def plus(self, call: AnsweredCall) -> "RoleATokens":
        price = default_pricing().call_usd(
            call.provider,
            call.model,
            call.tokens_in,
            call.tokens_out,
            datetime.now(UTC).date(),
            CacheTokens(call.cache_read_tokens, call.cache_write_tokens),
        )
        return RoleATokens(
            self.tokens_in + call.tokens_in,
            self.tokens_out + call.tokens_out,
            self.cache_read + call.cache_read_tokens,
            self.cache_write + call.cache_write_tokens,
            None if price is None or self.usd is None else self.usd + float(price),
        )


class RoleACounter:
    """An `LLMClient` that counts role A's calls and their characters, answering role A from `role_a` or, without one,
    with no step; every other call goes to `other` (role C, replayed). A live role A's repairs are counted, as the
    provider is called for them; an abstaining one's are not: they say nothing of a live one's."""

    def __init__(self, other: LLMClient, role_a: LLMClient | None) -> None:
        self._other = other
        self._role_a = role_a
        self.calls = 0
        self.chars = 0
        self.tokens = RoleATokens()

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        if req.prompt_kind not in ROLE_A:
            return await self._other.complete_json(req, check)
        if req.prompt_kind == FIRST_CALL or self._role_a is not None:
            self.calls += 1
            self.chars += len(req.system) + sum(map(len, req.cached)) + len(req.user)
        if self._role_a is not None:
            try:
                response = await self._role_a.complete_json(req, check)
            except LLMFailure as failure:  # the calls that answered before it failed were charged
                self._charge(failure.answered)
                raise
            self._charge(response.answered)
            return response
        return LLMResponse(
            data=_abstained(req.output_schema),
            provider="none",
            model="none",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            request_hash=request_hash(req),
        )

    def _charge(self, answered: Sequence[AnsweredCall]) -> None:
        for call in answered:
            self.tokens = self.tokens.plus(call)


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
    validation: Validation = "held-out",
) -> list[HostRun]:
    """One `HostRun` per (host, schema) of the store's split, learning from its first `pages` pages in capture order
    and validating on the later ones (`validation`, see `validation_pages`). Role C's
    calls are answered from the recordings, then by `live` (`RecordedLLM`); role A's by `role_a`, or not at all."""
    recorded = RecordedLLM(store, live)
    by_host: dict[tuple[str, str], list[_Page]] = defaultdict(list)
    for row in await store.list_pages():
        page = await _loaded(store, row)
        if page is not None:
            by_host[(page.host, row.schema_name)].append(page)
    runs = []
    for (_, schema_name), found in sorted(by_host.items()):
        ordered = sorted(found, key=lambda p: (p.bundle.manifest.fetched_at, p.row.capture_id))
        if validation == "same-page":
            ordered = ordered[:pages]
        runs.append(await _host_run(engine, engine.schema(schema_name), ordered, pages, recorded, role_a, max_chars))
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
    sample: int,
    recorded: LLMClient,
    role_a: LLMClient | None,
    max_chars: int,
) -> HostRun:
    stored = [s for page in pages if (s := await _stored(engine, schema, page, recorded)) is not None]
    counter = RoleACounter(recorded, role_a)
    ir: ExtractionConfigIR | None = None
    held = 0
    if stored:
        learning, validating = validation_pages(stored, sample)
        held = len({s.held_out.capture_id for s in validating} - {s.held_out.capture_id for s in learning})
        # The fetch method a config names does not change what its steps extract.
        fetch: FetchMethod = "http" if stored[0].bundle.manifest.method == "http" else "browser"
        target = Target(schema, pages[0].host, fetch, None)
        held_out = [s.held_out for s in validating]
        try:
            validated = await learn_config(
                counter, target, learning, held_out, engine.data.vocabulary, max_chars, absent_from=learning
            )
        except LLMFailure:  # a live role A failed or its budget ran out: as a learning run, nothing activates
            validated = None
        ir = None if validated is None else validated.ir
    return HostRun(
        category=pages[0].row.category,
        page_kind=schema.page_kind,
        pages=len(learning) if stored else 0,
        activated=ir is not None,
        fields=config_fields(ir),
        executability=class_counts(ir),
        role_a_calls=counter.calls,
        role_a_chars=counter.chars,
        role_a_tokens=counter.tokens,
        held_out=held,
    )


def validation_pages[T](stored: Sequence[T], sample: int) -> tuple[list[T], list[T]]:
    """The learning sample (the first `sample` pages) and the pages its config is validated on: the later pages, or
    the sample when there are none, repeated to `MIN_HELD_OUT` pages when fewer."""
    learning = list(stored[:sample])
    later = list(stored[sample:]) or learning
    return learning, list(islice(cycle(later), max(MIN_HELD_OUT, len(later))))


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
    tokens = reduce(RoleATokens.combined, (r.role_a_tokens for r in runs), RoleATokens())
    return {
        "hosts": hosts,
        "pages_per_host": round(sum(r.pages for r in runs) / hosts, 2),
        "held_out_hosts": sum(r.held_out > 0 for r in runs),
        "zero_touch": round(sum(r.zero_touch for r in runs) / hosts, 3),
        "activated": round(sum(r.activated for r in runs) / hosts, 3),
        "fields_per_host": round(sum(r.fields for r in runs) / hosts, 2),
        "executability": {name: sum(r.executability.get(name, 0) for r in runs) for name in CLASSES},
        "role_a_hosts": sum(r.role_a_calls > 0 for r in runs),
        "role_a_calls": sum(r.role_a_calls for r in runs),
        "role_a_chars": chars,
        "role_a_usd_estimate": None if usd_per_char is None else round(chars * usd_per_char, 2),
        "role_a_live_hosts": sum(r.role_a_tokens.used for r in runs),
        "role_a_tokens_in": tokens.tokens_in,
        "role_a_tokens_out": tokens.tokens_out,
        "role_a_cache_read_tokens": tokens.cache_read,
        "role_a_cache_write_tokens": tokens.cache_write,
        "role_a_usd": None if not tokens.used or tokens.usd is None else round(tokens.usd, 4),
    }
