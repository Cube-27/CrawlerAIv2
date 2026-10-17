"""Every collector over one page (SPEC-05 §4.5, §4.14, ARCHITECTURE §8.1, §8.2 rule 1): their entities, candidates
and diagnostics as one result.

The standard collectors run first, each on its own: one that raises gives no candidates and a diagnostic, and the
others still run. An `api` capture of an active adapter adds that adapter's collector (D-0445). Then js_state and xhr
admit their values against the candidates of the other kinds (D-0418); on a listing, xhr also reads the rows of the
page's captured calls (Appendix A #59), which resolution takes where structured data and the config give none.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from crawlerai.adapters.registry import Registry
from crawlerai.collect.adapter import AdapterCollector
from crawlerai.collect.admission import AdmittingCollector
from crawlerai.collect.base import Candidate, Collector, Entity
from crawlerai.collect.dom import DomCollector
from crawlerai.collect.js_state import JsStateCollector
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.microdata import MicrodataCollector
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


def collect_page(
    page: ParsedPage,
    manifest: CaptureManifest,
    schema: SchemaDef,
    ctx: Context,
    *,
    vocabulary: Vocabulary,
    adapters: Adapters | None,
) -> Collected:
    collectors: list[Collector] = [
        JsonLdCollector(vocabulary),
        MicrodataCollector(vocabulary),
        OpenGraphCollector(),
        DomCollector(),
    ]
    diagnostics: list[str] = []
    adapter = _adapter_collector(manifest, adapters, vocabulary, diagnostics)
    if adapter is not None:
        collectors.insert(0, adapter)
    results = [
        r for c in collectors if (r := _isolated(c, partial(c.collect, page, schema, ctx), diagnostics)) is not None
    ]
    entities = tuple(entity for result in results for entity in result.entities)
    others = tuple(candidate for result in results for candidate in result.candidates)
    admitting: Sequence[AdmittingCollector] = (JsStateCollector(), XhrCollector())
    admitted = [
        a
        for c in admitting
        if (a := _isolated(c, partial(c.collect, page, schema, ctx, others), diagnostics)) is not None
    ]
    return Collected(
        entities=entities + tuple(entity for result in admitted for entity in result.entities),
        candidates=others + tuple(candidate for result in admitted for candidate in result.candidates),
        diagnostics=(
            *(d for result in results for d in result.diagnostics),
            *(d for result in admitted for d in result.diagnostics),
            *diagnostics,
        ),
        rows=tuple(row for result in admitted for row in result.rows),
    )


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
