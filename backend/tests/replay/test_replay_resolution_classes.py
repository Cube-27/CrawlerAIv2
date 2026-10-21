"""Failure classes of extraction replayed through `extract_page` on synthetic captures (extraction spec): each
test builds the class's page shape on `example.test` names (C3, C9) and checks what the commerce preset publishes."""

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from tests.replay.captures import PAGE_URL, capture

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


def _extract(head: str, body: str = "", schema: SchemaDef = SCHEMA, lang: str = "") -> ExtractionResult:
    lang_attribute = f' lang="{lang}"' if lang else ""
    raw = f"<html{lang_attribute}><head>{head}</head><body>{body}</body></html>".encode()
    return asyncio.run(extract_page(capture(raw), schema, None, None, data=DATA))


def _jsonld(*nodes: Mapping[str, Any]) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(node)}</script>' for node in nodes)


def _outcomes(result: ExtractionResult, *names: str) -> dict[str, tuple[str, str | None, JsonValue]]:
    assert result.entity is not None
    return {name: (result.entity[name].status, result.entity[name].reason, result.entity[name].value) for name in names}


def _og(*metas: tuple[str, str]) -> str:
    return "".join(f'<meta property="{p}" content="{c}">' for p, c in metas)


def test_site_wide_og_values_on_a_client_rendered_page_do_not_publish() -> None:
    # The page names its product only in rendered text; its og block is the site's default.
    head = _og(
        ("og:site_name", "Synthetic Tools - Workshop"),
        ("og:title", "Synthetic Tools"),
        ("og:image", "https://shop.example.test/banner.png"),
        ("og:url", PAGE_URL),
    )

    result = _extract(head, "<h1>Widget One</h1>")

    assert _outcomes(result, "title", "image_url", "url") == {
        "title": ("missing", "no_candidates", None),
        "image_url": ("missing", "no_candidates", None),
        "url": ("published", None, PAGE_URL),
    }


def _product(**properties: Any) -> dict[str, Any]:
    return {"@context": "https://schema.org", "@type": "Product", **properties}


def _offer(price: str, availability: str, **properties: Any) -> dict[str, Any]:
    return {"@type": "Offer", "price": price, "priceCurrency": "EUR", "availability": availability, **properties}


_LISTING_PRESET = next(p for p in load_presets() if p.name == "commerce_listing")
LISTING = SchemaDef(**_LISTING_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


_MICRODATA_PRODUCT = (
    '<div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Widget One</h1>'
    '<meta itemprop="sku" content="W-1"><div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
    '<meta itemprop="price" content="14.00"><meta itemprop="priceCurrency" content="EUR">'
    '<link itemprop="availability" href="https://schema.org/InStock"></div></div>'
)


def test_standalone_variants_naming_their_group_s_id_are_its_variants() -> None:
    # schema.org `inProductGroupWithID`: each Product is a variant of the ProductGroup with that `productGroupID`, so
    # the group is the page's product, its variants are rows, and the properties it states for all of them publish.
    group = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "productGroupID": "G-1",
        "name": "Widget",
        "url": PAGE_URL,
        "color": "Blue",
        "audience": {"@type": "PeopleAudience", "suggestedGender": "unisex"},
        "variesBy": "https://schema.org/size",
    }
    variants = [
        _product(
            name=f"Widget {size}",
            sku=f"W-{size}",
            size=size,
            inProductGroupWithID="G-1",
            offers=_offer("10.00", "https://schema.org/InStock"),
        )
        for size in ("S", "M")
    ]

    result = _extract(_jsonld(group, *variants))

    assert _outcomes(result, "title", "color", "gender", "price") == {
        "title": ("published", None, "Widget"),
        "color": ("published", None, "Blue"),
        "gender": ("published", None, "unisex"),
        "price": ("published", None, {"amount": "10.00", "currency": "EUR"}),
    }
    assert result.entity is not None
    published = result.entity["variants"]
    assert published.status == "published"
    assert [item.fields["sku"].value for item in published.items or ()] == ["W-S", "W-M"]


def test_a_visible_bound_of_a_stated_price_range_is_no_price() -> None:
    # Resolution spec, "Candidate score": `€80` beside an AggregateOffer of 80-120 is its bound; the range publishes.
    price_range = {"type": "range", "description": "d", "schema_org": "AggregateOffer.lowPrice+highPrice+priceCurrency"}
    fields = {**_PRESET.model_dump()["fields"], "price_range": price_range}
    preset = {**_PRESET.model_dump(), "fields": fields}
    schema = SchemaDef(**preset, id=SchemaId(uuid7()), origin="user", status="active")
    offers = {"@type": "AggregateOffer", "lowPrice": 80, "highPrice": 120, "priceCurrency": "EUR"}
    head = _jsonld(_product(name="Widget One", sku="W-1", offers=offers))

    result = _extract(head, "<main><h1>Widget One</h1><p>From <span>€80</span></p></main>", schema)

    assert _outcomes(result, "price", "price_range") == {
        "price": ("missing", "range_bound", None),
        "price_range": (
            "published",
            None,
            {"min": "80", "max": "120", "currency": "EUR", "unit": None, "period": None},
        ),
    }
