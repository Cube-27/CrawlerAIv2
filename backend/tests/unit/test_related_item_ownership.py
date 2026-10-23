"""Related items never lend their values to a detail page's target: a checkable value
inside an array of other items belongs to the item it sits in, in structured data by its entity and in embedded state
or API bodies by its array row, while a row naming the page is the target's.

Pages are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import asyncio
import json
from html import escape
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from tests.support.captures import capture

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("jsonld", "microdata", "og", "js_state", "xhr")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(
            type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"
        ),
    },
)

TARGET_PRICE: JsonValue = {"amount": "19.90", "currency": "EUR"}
TARGET = {"@type": "Product", "name": "Widget One", "url": PAGE_URL}


def _related(n: int, price: str) -> dict[str, Any]:
    return {
        "@type": "Product",
        "name": f"Gadget {n}",
        "url": f"https://shop.example.test/p/{n}",
        "offers": {"@type": "Offer", "price": price, "priceCurrency": "EUR"},
    }


def _page(*nodes: dict[str, Any], state: JsonValue = None, body: str = "", microdata: str = "") -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **n})}</script>'
        for n in nodes
    )
    script = "" if state is None else f"<script>window.__STATE__ = {json.dumps(state)};</script>"
    return (
        f'<html lang="en"><head>{blocks}{script}</head><body><h1>Widget One</h1>{microdata}{escape(body)}</body></html>'
    )


def _extract(html: str, schema: SchemaDef = SCHEMA) -> ExtractionResult:
    raw = html.encode()
    return asyncio.run(extract_page(capture(raw, url=PAGE_URL), schema, None, None, data=DATA))


def _price(result: ExtractionResult) -> tuple[str, str | None, JsonValue]:
    assert result.entity is not None
    outcome = result.entity["price"]
    return outcome.status, outcome.reason, outcome.value


def _rejections(result: ExtractionResult) -> set[str]:
    assert result.entity is not None
    return {reason for _, reason in result.entity["price"].rejected}


# --- embedded state ---

RELATED_ROWS: list[JsonValue] = [
    {"name": "Gadget 2", "href": "/p/2", "cost": "€5.00"},
    {"name": "Gadget 3", "href": "https://shop.example.test/p/3", "cost": "€7.00"},
]


def test_a_related_items_visible_price_in_state_does_not_become_the_targets() -> None:
    # Only the related items' prices are shown: before rows, the page owned them and one published as the target's.
    result = _extract(_page(TARGET, state={"product": {"id": 1}, "related": RELATED_ROWS}, body="€5.00 €7.00"))

    assert _price(result) == ("missing", "not_owned", None)


def _kept(result: ExtractionResult) -> list[JsonValue]:
    assert result.entity is not None
    return [c.normalized.value for c in result.entity["price"].kept if isinstance(c.normalized, Ok)]


def test_related_items_in_state_do_not_make_the_targets_own_price_conflict() -> None:
    # Before rows, the three page-owned prices disagreed (`conflict`, never sent to role C). A lone state value has the
    # evidence bucket `state`, so the target's own price publishes.
    state: JsonValue = {"product": {"cost": "€19.90"}, "related": RELATED_ROWS}

    result = _extract(_page(TARGET, state=state, body="€19.90 · Related: €5.00 €7.00"))

    assert _price(result) == ("published", None, {"amount": "19.90", "currency": "EUR"})
    assert _kept(result) == [TARGET_PRICE]
    assert "not_owned" in _rejections(result)


# --- structured data ---


def test_related_products_offers_in_json_ld_are_not_the_targets() -> None:
    target = {**TARGET, "isRelatedTo": [_related(2, "5.00"), _related(3, "7.00")], "isSimilarTo": _related(4, "9.00")}

    result = _extract(_page(target, body="€5.00 €7.00 €9.00"))

    assert _price(result) == ("missing", "not_owned", None)


# --- a rating stated apart (OD-4) ---

RATED = SCHEMA.model_copy(
    update={
        "fields": {
            **SCHEMA.fields,
            "rating": FieldSpec(
                type=FieldType.NUMBER, description="d", schema_org="Product.aggregateRating.ratingValue"
            ),
        }
    }
)
WIDGET = (
    '<div itemscope itemtype="https://schema.org/AggregateRating">'
    '<meta itemprop="ratingValue" content="4.5"><meta itemprop="reviewCount" content="8"></div>'
)


def _rating(html: str) -> tuple[str, str | None, JsonValue]:
    result = _extract(html, RATED)
    assert result.entity is not None
    outcome = result.entity["rating"]
    return outcome.status, outcome.reason, outcome.value


def test_a_lone_rating_stated_apart_is_the_one_products_and_no_one_elses() -> None:
    assert _rating(_page(TARGET, microdata=WIDGET))[::2] == ("published", "4.5")
    # A rating in another entity rates that entity; with two products, or two ratings stating other values, the page
    # does not say which item a rating apart is of.
    store = {"@type": "Organization", "name": "Shop", "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4}}
    assert _rating(_page(TARGET, store))[:2] == ("missing", "not_owned")
    assert _rating(_page(TARGET, _related(2, "5.00"), microdata=WIDGET))[0] != "published"
    other = WIDGET.replace("4.5", "3.9")
    assert _rating(_page(TARGET, microdata=WIDGET + other))[:2] == ("missing", "not_owned")
