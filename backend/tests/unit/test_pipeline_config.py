"""Active mode in the pipeline: with a site's active config, `extract_page` runs the
engine executor on the page's one parse, the config's candidates resolve with the collectors' in the bucket of their
field's status, and role C is asked only for fields the config does not run.

Pages and configs are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.core.ids import uuid7
from crawlerai.db.models import FieldStatus, PageKind, SchemaId, SourceKind
from crawlerai.resolve.pipeline import (
    EngineData,
    extract_page,
)
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle
from tests.support.captures import capture
from tests.support.role_c import PRICE, FakeRoleC

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)


def _schema(page_kind: PageKind = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields=fields,
    )


TITLE = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
PRODUCT = _schema(
    title=TITLE,
    price=FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"),
    sku=FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku"),
)
PRICE_TEXT = '<p class="price">19.90 EUR</p>'


def _steps(xpath: str, status: FieldStatus = "uncorroborated") -> dict[str, Any]:
    return {"steps": [{"xpath": xpath}], "status": status}


def _config(
    fields: Mapping[str, dict[str, Any]],
    *,
    page_kind: PageKind = "detail",
    listing: dict[str, Any] | None = None,
    absent: tuple[str, ...] = (),
) -> EngineExecutor:
    document = {
        "ir_version": "1",
        "site": "shop.example.test",
        "schema": {"name": "synthetic", "digest": "0" * 64},
        "page_kind": page_kind,
        "fetch": {"method": "http"},
        "fields": dict(fields),
        "listing": listing,
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "test",
        },
        "absent": list(absent),
    }
    return EngineExecutor(ExtractionConfigIR.model_validate(document), VOCABULARY)


def _html(*nodes: Mapping[str, Any], body: str = "") -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **n})}</script>'
        for n in nodes
    )
    return f'<html lang="en"><head>{blocks}</head><body><h1>Widget One</h1>{body}</body></html>'


def _bundle(body: str, url: str = PAGE_URL) -> CaptureBundle:
    raw = body.encode()
    return capture(raw, url=url)


def _extract(
    body: str,
    config: EngineExecutor | None,
    schema: SchemaDef = PRODUCT,
    role_c: FakeRoleC | None = None,
    url: str = PAGE_URL,
) -> ExtractionResult:
    return asyncio.run(extract_page(_bundle(body, url), schema, config, role_c, data=DATA))


def _published(result: ExtractionResult) -> dict[str, tuple[JsonValue, str | None]]:
    assert result.entity is not None
    return {name: (o.value, o.evidence) for name, o in result.entity.items() if o.status == "published"}


# --- detail pages ---


def test_a_config_value_publishes_in_its_fields_status_bucket() -> None:
    config = _config(
        {
            "title": _steps("normalize-space(//h1)", "corroborated"),
            "price": _steps('normalize-space(//p[@class="price"])', "operator"),
        }
    )
    result = _extract(_html(body=PRICE_TEXT), config)
    assert result.mode == "config"
    # §10: `operator` fields take the `config_uncorroborated` bucket until labels show they need their own.
    assert _published(result) == {
        "title": ("Widget One", "config_corroborated"),
        "price": (PRICE, "config_uncorroborated"),
    }
    assert result.outcome == "extracted"
    assert [c.locator for c in result.candidates if c.source_kind == "config"] == [
        "config:title:0:normalize-space(//h1)",
        'config:price:0:normalize-space(//p[@class="price"])',
    ]


# Absent fields: required fields the learning pages never stated.


# --- listings ---
