"""The check that sends an HTTP detail page to the browser (owner #48): a page for a schema that requires a price, with
no Offer and no price candidate in its capture.

Pages are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId
from crawlerai.resolve.pipeline import EngineData, lacks_offer_data
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
DATA = EngineData(
    vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ("jsonld", "microdata", "og")), calibration=None
)
PAGE_URL = "https://shop.example.test/p/1"
TITLE = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")


def _schema(*, price_required: bool = True, page_kind: PageKind = "detail") -> SchemaDef:
    price = FieldSpec(
        type=FieldType.MONEY, description="d", required=price_required, schema_org="Offer.price+priceCurrency"
    )
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields={"title": TITLE, "price": price},
    )


def _bundle(*nodes: dict[str, Any], body: str = "") -> CaptureBundle:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **n})}</script>'
        for n in nodes
    )
    raw = f'<html lang="en"><head>{blocks}</head><body><h1>Widget One</h1>{body}</body></html>'.encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=PAGE_URL,
        final_url=PAGE_URL,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=raw, network=())


PRODUCT = {"@type": "Product", "name": "Widget One", "url": PAGE_URL}


def test_a_product_without_any_offer_or_price_lacks_offer_data() -> None:
    assert lacks_offer_data(_bundle(PRODUCT), _schema(), DATA) is True


def test_a_page_without_structured_data_lacks_offer_data() -> None:
    assert lacks_offer_data(_bundle(body="<p>Widget One, made of wood.</p>"), _schema(), DATA) is True


@pytest.mark.parametrize(
    "offers",
    [
        pytest.param({"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}, id="priced"),
        # An Offer that states no price still says the page holds its offer: its price is missing, not unrendered.
        pytest.param({"@type": "Offer", "availability": "https://schema.org/InStock"}, id="unpriced"),
        pytest.param({"@type": "AggregateOffer", "lowPrice": "10", "priceCurrency": "EUR"}, id="aggregate"),
    ],
)
def test_a_page_with_an_offer_holds_offer_data(offers: dict[str, Any]) -> None:
    assert lacks_offer_data(_bundle({**PRODUCT, "offers": offers}), _schema(), DATA) is False


def test_a_price_candidate_outside_an_offer_holds_offer_data() -> None:
    # An Open Graph product price is a `money` candidate with no Offer entity behind it.
    amount = '<meta property="product:price:amount" content="19.90">'
    currency = '<meta property="product:price:currency" content="EUR">'
    assert lacks_offer_data(_bundle(PRODUCT, body=amount + currency), _schema(), DATA) is False


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(_schema(price_required=False), id="price-optional"),
        pytest.param(_schema(page_kind="listing"), id="listing"),
    ],
)
def test_only_a_detail_schema_that_requires_a_price_asks(schema: SchemaDef) -> None:
    assert lacks_offer_data(_bundle(PRODUCT), schema, DATA) is False
