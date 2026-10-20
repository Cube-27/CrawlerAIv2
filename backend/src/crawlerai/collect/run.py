"""Every collector over one page (extraction spec rule 1): their entities, candidates
and diagnostics as one result.

The adapter collectors, then the standard collectors, run first, each on its own: one that raises gives no candidates
and a diagnostic, and the others still run. An `api` capture of an active adapter adds that adapter's collector
(D-0445), as does the answer a page-scoped adapter joined to the page it serves (`ADAPTER_CALL`), read with that
adapter's shapes; a platform's documented product JSON that a detail page's HTTP fetch joined after its identity check
is read as that platform documents it (`collect.platform_json`). Then js_state and xhr admit their values against the
candidates of the other kinds (D-0418); on a listing, xhr also reads the rows of the page's captured calls (Appendix A
#59), which resolution takes where structured data and the config give none; on a listing none of whose groups aligns
and with no call rows, the rows of its state JSON are read too (`collect.items.state_rows`), resolution taking them, and
their candidates, only where no other source gives rows.
The page's detect-and-report signals (`content.signals`) join the diagnostics.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial

from crawlerai.adapters.base import ADAPTER_CALL
from crawlerai.adapters.platforms import signature_of
from crawlerai.adapters.registry import Registry
from crawlerai.collect.adapter import AdapterCollector
from crawlerai.collect.admission import AdmittingCollector
from crawlerai.collect.base import Candidate, Collector, CollectResult, Entity
from crawlerai.collect.dom import DomCollector, product_apart
from crawlerai.collect.dom_images import stated_images
from crawlerai.collect.dom_text import DescriptionCollector
from crawlerai.collect.items.align import Items, align
from crawlerai.collect.items.state_rows import StateRows, state_rows
from crawlerai.collect.js_state import JsStateCollector, state_documents
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.microdata import MicrodataCollector
from crawlerai.collect.network_match import LearnedCalls
from crawlerai.collect.og import OpenGraphCollector
from crawlerai.collect.platform_json import PlatformJsonCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.collect.scope import other_items
from crawlerai.collect.xhr import XhrCollector
from crawlerai.content.metadata import canonical_link
from crawlerai.content.page import ParsedPage
from crawlerai.content.signals import PREFIX as SIGNAL_PREFIX
from crawlerai.content.signals import page_signals
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureManifest

log = logging.getLogger(__name__)

# The adapters a pipeline reads `api` captures with: only the active ones answer (`Registry`).
Adapters = Registry


@dataclass(frozen=True, slots=True)
class Collected:
    entities: tuple[Entity, ...]
    candidates: tuple[Candidate, ...]
    diagnostics: tuple[str, ...]
    rows: tuple[Entity, ...] = ()  # a listing's rows from captured calls, also among `entities`
    # A listing's aligned groups of item blocks (the item layer), best first; their entities and candidates are among
    # the others.
    items: tuple[Items, ...] = ()
    # A listing's rows from its state JSON, read only when no group aligns and no call gives rows; their entities are
    # among `entities`, their candidates only here.
    state: StateRows = field(default_factory=StateRows)
    # The query parameters by which the page's platform selects a variant on a product's own URL
    # (`adapters.platforms.variant_params`); none when the page shows no platform that documents any.
    variant_params: tuple[str, ...] = ()
    # A detail page's blocks outside its product container (`collect.dom.product_apart`), by element.
    outside: frozenset[int] = frozenset()


def collect_page(
    page: ParsedPage,
    manifest: CaptureManifest,
    schema: SchemaDef,
    ctx: Context,
    *,
    vocabulary: Vocabulary,
    adapters: Adapters | None,
    learned: LearnedCalls | None = None,
) -> Collected:
    """Every collector over the page; `learned` is the site's learned listing recipe's calls (`collect.xhr`)."""
    collectors: list[Collector] = [
        JsonLdCollector(vocabulary),
        MicrodataCollector(vocabulary),
        OpenGraphCollector(),
        PlatformJsonCollector(vocabulary),
    ]
    diagnostics: list[str] = []
    collectors[:0] = _adapter_collectors(page, manifest, adapters, vocabulary, diagnostics)
    results = [
        r for c in collectors if (r := _isolated(c, partial(c.collect, page, schema, ctx), diagnostics)) is not None
    ]
    stated = _stated(results, vocabulary, page, manifest) if schema.page_kind == "detail" else ()
    dom = _DomPasses.of(page, schema, ctx, stated, diagnostics)
    results.extend(dom.structural(page, schema, ctx, diagnostics))
    # The item layer's blocks are read before the admitting collectors, whose values then agree with the best aligned
    # group's too.
    items = _isolated(align, partial(align, page, schema, ctx), diagnostics) or ()
    best = items[0].candidates if items else ()
    entities = (*(entity for result in results for entity in result.entities), *(e for i in items for e in i.entities))
    others = (*(candidate for result in results for candidate in result.candidates), *best)
    # The description block extends what the other collectors state, so it reads after them.
    described = dom.description(page, schema, ctx, others, diagnostics)
    if described is not None:
        results.append(described)
        others = (*others, *described.candidates)
    admitting: Sequence[AdmittingCollector] = (JsStateCollector(), XhrCollector(learned))
    admitted = [
        a
        for c in admitting
        if (a := _isolated(c, partial(c.collect, page, schema, ctx, others), diagnostics)) is not None
    ]
    rows = tuple(row for result in admitted for row in result.rows)
    state = StateRows()
    if schema.page_kind == "listing" and not items and not rows:
        read = partial(state_rows, page, state_documents(page, []), schema, ctx)
        state = _isolated(state_rows, read, diagnostics) or StateRows()
    candidates = (
        *others,
        *(candidate for group in items[1:] for candidate in group.candidates),
        *(candidate for result in admitted for candidate in result.candidates),
    )
    return Collected(
        entities=(*entities, *(entity for result in admitted for entity in result.entities), *state.rows),
        candidates=candidates,
        diagnostics=(
            *(d for result in results for d in result.diagnostics),
            *(d for group in items for d in group.diagnostics),
            *(d for result in admitted for d in result.diagnostics),
            *state.diagnostics,
            *diagnostics,
            *_signals(page, manifest, schema, (*candidates, *state.candidates)),
        ),
        rows=rows,
        items=items,
        state=state,
        variant_params=_variant_params(page, manifest) if schema.page_kind == "detail" else (),
        outside=dom.outside,
    )


def _signals(
    page: ParsedPage, manifest: CaptureManifest, schema: SchemaDef, candidates: Sequence[Candidate]
) -> tuple[str, ...]:
    """The page's detect-and-report signals as diagnostics (`content.signals`): reported only, read by nothing here."""
    money = {name for name, spec in schema.fields.items() if FieldType.MONEY in (spec.type, _item_type(spec))}
    texts = (c.raw for c in candidates if c.field in money and isinstance(c.raw, str))
    return tuple(f"{SIGNAL_PREFIX}{signal}" for signal in page_signals(page, manifest.resources, texts))


def _item_type(spec: FieldSpec) -> FieldType | None:
    return None if spec.item is None else spec.item.type


@dataclass(frozen=True, slots=True)
class _DomPasses:
    """A detail page's two DOM passes, scoped to its product container (`collect.dom.product_apart`, read once against
    the structured data's prices)."""

    outside: frozenset[int]
    # The main image the structured data states (`collect.dom_images.stated_images`).
    primary: tuple[str, ...] = ()

    @classmethod
    def of(
        cls, page: ParsedPage, schema: SchemaDef, ctx: Context, structured: Sequence[Candidate], diagnostics: list[str]
    ) -> "_DomPasses":
        outside = _isolated(product_apart, partial(product_apart, page, schema, ctx, structured), diagnostics)
        return cls(outside or frozenset(), stated_images(schema, structured))

    def structural(
        self, page: ParsedPage, schema: SchemaDef, ctx: Context, diagnostics: list[str]
    ) -> list[CollectResult]:
        dom = DomCollector(self.outside, self.primary)
        found = _isolated(dom, partial(dom.collect, page, schema, ctx), diagnostics)
        return [] if found is None else [found]

    def description(
        self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate], diagnostics: list[str]
    ) -> CollectResult | None:
        described = DescriptionCollector(self.outside)
        return _isolated(described, partial(described.collect, page, schema, ctx, others), diagnostics)


def _stated(
    results: Sequence[CollectResult], vocabulary: Vocabulary, page: ParsedPage, manifest: CaptureManifest
) -> list[Candidate]:
    """The structured collectors' candidates of the page's product: an Offer in another item's scope prices that item,
    not the product (`collect.scope`)."""
    elsewhere = other_items([e for r in results for e in r.entities], vocabulary, _page_urls(page, manifest))
    return [c for r in results for c in r.candidates if c.entity_id not in elsewhere]


def _variant_params(page: ParsedPage, manifest: CaptureManifest) -> tuple[str, ...]:
    """The query parameters by which the page's platform selects a variant (`adapters.platforms`), or none."""
    signature = signature_of(page.html, manifest.headers.response)
    return () if signature is None else signature.variant_params


def _page_urls(page: ParsedPage, manifest: CaptureManifest) -> tuple[str, ...]:
    """The request, final and canonical URLs (RFC 6596): the URLs that name the page's own product."""
    canonical = canonical_link(page, manifest.final_url)
    return (manifest.url, manifest.final_url, *(() if canonical is None else (canonical,)))


def _adapter_collectors(
    page: ParsedPage,
    manifest: CaptureManifest,
    adapters: Adapters | None,
    vocabulary: Vocabulary,
    diagnostics: list[str],
) -> list[AdapterCollector]:
    """D-0445, INV-39: an `api` capture holds the JSON of the adapter that detects its page URL, the bundle's `url`, and
    fetches from its final URL; a network body marked `ADAPTER_CALL` holds the JSON of the page-scoped adapter that
    detects the page's final URL (the one it served) and fetches from the body's URL."""
    if manifest.method == "api":
        calls: list[tuple[int | None, str, str]] = [(None, manifest.url, manifest.final_url)]
    else:
        joined = enumerate(page.network_entries[: len(page.network)])
        calls = [(i, manifest.final_url, entry.url) for i, entry in joined if entry.data_call == ADAPTER_CALL]
    collectors: list[AdapterCollector] = []
    for call, url, endpoint in calls:
        found = None if adapters is None else adapters.reader(url, endpoint)
        if found is None:
            diagnostics.append("adapter: no active adapter reads this answer")
            continue
        collectors.append(AdapterCollector(*found, vocabulary, call))
    return collectors


def _isolated[R](collector: object, run: Callable[[], R], diagnostics: list[str]) -> R | None:
    """§4.14: a collector that raises gives no result but a diagnostic, and the page's other collectors run."""
    try:
        return run()
    except Exception as error:  # a collector bug must not cost the page the other collectors' values
        name = type(collector).__name__
        log.exception("collector %s failed", name)
        diagnostics.append(f"{name}: {type(error).__name__}: {error}")
        return None
