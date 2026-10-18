"""Structural DOM values replayed through `extract_page` on synthetic captures (extraction spec,
admitted 2026-10-16): a page without structured data publishes the brand, sku, availability and main image it shows
in a labelled table and its main region, in the `dom` evidence bucket; where structured data states the same value
the two agree, and where it states another the field resolves as any disagreement does. Pages are synthetic
(`example.test`, C3, C9)."""

import asyncio
import json
from pathlib import Path

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import FieldOutcome
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from tests.replay.captures import capture

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "dom", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")

BODY = (
    '<main><h1>Synthetic Widget</h1><img src="/img/widget.jpg" alt="Synthetic Widget">'
    "<table><tr><th>Brand</th><td>Example Brand</td></tr>"
    "<tr><th>SKU</th><td>W-1</td></tr>"
    "<tr><th>Availability</th><td>In stock (3 available)</td></tr></table></main>"
)


def _fields(head: str = "", body: str = BODY) -> dict[str, FieldOutcome]:
    raw = f"<html><head>{head}</head><body>{body}</body></html>".encode()
    result = asyncio.run(extract_page(capture(raw), SCHEMA, None, None, data=DATA))
    assert result.entity is not None
    return dict(result.entity)


def _jsonld(**product: object) -> str:
    block = {"@context": "https://schema.org", "@type": "Product", "name": "Synthetic Widget", **product}
    return f'<script type="application/ld+json">{json.dumps(block)}</script>'


def test_a_page_without_structured_data_publishes_what_its_label_table_and_main_image_show() -> None:
    fields = _fields()

    published = {n: (o.value, o.source_kind, o.evidence) for n, o in fields.items() if o.status == "published"}
    assert {n: published.get(n) for n in ("brand", "sku", "availability", "image_url")} == {
        "brand": ("Example Brand", "dom", "dom"),
        "sku": ("W-1", "dom", "dom"),
        "availability": ("InStock", "dom", "dom"),
        "image_url": ("https://shop.example.test/img/widget.jpg", "dom", "dom"),
    }
    assert fields["brand"].locator == "dom:/html[1]/body[1]/main[1]/table[1]/tbody[1]/tr[1]/td[1]"
