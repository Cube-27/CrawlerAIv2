"""Every collector over one page (extraction spec rule 1): their entities, candidates
and diagnostics as one result.

The standard collectors run first, each on its own: one that raises gives no candidates and a diagnostic, and the
others still run. An `api` capture of an active adapter adds that adapter's collector (D-0445). Then js_state and xhr
admit their values against the candidates of the other kinds (D-0418); on a listing, xhr also reads the rows of the
page's captured calls (Appendix A #59), which resolution takes where structured data and the config give none; on a
listing none of whose groups aligns and with no call rows, the rows of its state JSON are read too
(`collect.items.state_rows`), resolution taking them, and their candidates, only where no other source gives rows.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial

from crawlerai.adapters.registry import Registry
from crawlerai.collect.adapter import AdapterCollector
from crawlerai.collect.admission import AdmittingCollector
from crawlerai.collect.base import Candidate, Collector, CollectResult, Entity
from crawlerai.collect.dom import DomCollector, product_apart
from crawlerai.collect.dom_text import DescriptionCollector
from crawlerai.collect.items.align import Items, align
from crawlerai.collect.items.state_rows import StateRows, state_rows
from crawlerai.collect.js_state import JsStateCollector, state_documents
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.microdata import MicrodataCollector
from crawlerai.collect.network_match import LearnedCalls
from crawlerai.collect.og import OpenGraphCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.collect.xhr import XhrCollector
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef
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
    collectors: list[Collector] = [JsonLdCollector(vocabulary), MicrodataCollector(vocabulary), OpenGraphCollector()]
    diagnostics: list[str] = []
    adapter = _adapter_collector(manifest, adapters, vocabulary, diagnostics)
    if adapter is not None:
        collectors.insert(0, adapter)
    results = [
        r for c in collectors if (r := _isolated(c, partial(c.collect, page, schema, ctx), diagnostics)) is not None
    ]
    dom = _DomPasses.of(page, schema, ctx, [c for result in results for c in result.candidates], diagnostics)
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
    return Collected(
        entities=(*entities, *(entity for result in admitted for entity in result.entities), *state.rows),
        candidates=(
            *others,
            *(candidate for group in items[1:] for candidate in group.candidates),
            *(candidate for result in admitted for candidate in result.candidates),
        ),
        diagnostics=(
            *(d for result in results for d in result.diagnostics),
            *(d for group in items for d in group.diagnostics),
            *(d for result in admitted for d in result.diagnostics),
            *state.diagnostics,
            *diagnostics,
        ),
        rows=rows,
        items=items,
        state=state,
    )


@dataclass(frozen=True, slots=True)
class _DomPasses:
    """A detail page's two DOM passes, scoped to its product container (`collect.dom.product_apart`, read once against
    the structured data's prices)."""

    outside: frozenset[int]

    @classmethod
    def of(
        cls, page: ParsedPage, schema: SchemaDef, ctx: Context, structured: Sequence[Candidate], diagnostics: list[str]
    ) -> "_DomPasses":
        outside = _isolated(product_apart, partial(product_apart, page, schema, ctx, structured), diagnostics)
        return cls(outside or frozenset())

    def structural(
        self, page: ParsedPage, schema: SchemaDef, ctx: Context, diagnostics: list[str]
    ) -> list[CollectResult]:
        dom = DomCollector(self.outside)
        found = _isolated(dom, partial(dom.collect, page, schema, ctx), diagnostics)
        return [] if found is None else [found]

    def description(
        self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate], diagnostics: list[str]
    ) -> CollectResult | None:
        described = DescriptionCollector(self.outside)
        return _isolated(described, partial(described.collect, page, schema, ctx, others), diagnostics)


def _adapter_collector(
    manifest: CaptureManifest, adapters: Adapters | None, vocabulary: Vocabulary, diagnostics: list[str]
) -> AdapterCollector | None:
    """D-0445, INV-39: an `api` capture holds the JSON of the adapter that detects its page URL, the bundle's `url`, and
    fetches from its final URL."""
    if manifest.method != "api":
        return None
    found = None if adapters is None else adapters.reader(manifest.url, manifest.final_url)
    if found is None:
        diagnostics.append("adapter: no active adapter reads this api capture")
        return None
    adapter, match = found
    return AdapterCollector(adapter, match, vocabulary)


def _isolated[R](collector: object, run: Callable[[], R], diagnostics: list[str]) -> R | None:
    """§4.14: a collector that raises gives no result but a diagnostic, and the page's other collectors run."""
    try:
        return run()
    except Exception as error:  # a collector bug must not cost the page the other collectors' values
        name = type(collector).__name__
        log.exception("collector %s failed", name)
        diagnostics.append(f"{name}: {type(error).__name__}: {error}")
        return None
