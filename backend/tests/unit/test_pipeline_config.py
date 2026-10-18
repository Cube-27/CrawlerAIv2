"""Active mode in the pipeline (SPEC-08 §4.8, ARCHITECTURE §8.4): with a site's active config, `extract_page` runs the
engine executor on the page's one parse, the config's candidates resolve with the collectors' in the bucket of their
field's status, and role C is asked only for fields the config does not run.

Pages and configs are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.core.ids import uuid7
from crawlerai.db.models import FieldStatus, PageKind, SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.pipeline import (
    EngineData,
    GapReply,
    GapRequest,
    ListingGapReply,
    ListingGapRequest,
    extract_page,
)
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult, LLMCallRecord
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

# The `parses` fixture (tests/unit/conftest.py): parser constructions by name, each with `calls` and `inputs`.
Parses = Mapping[str, Any]

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
CALL = LLMCallRecord(
    prompt_kind="c_extract_detail",
    provider="provider-a",
    model="model-a",
    request_hash="0" * 64,
    tokens_in=9,
    tokens_out=3,
)
PRICE: JsonValue = {"amount": "19.90", "currency": "EUR"}


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
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
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


class FakeRoleC:
    """Answers each asked detail field with a grounded `llm` candidate of the target, and records every request."""

    def __init__(self, listing_reply: ListingGapReply | None = None) -> None:
        self.requests: list[GapRequest] = []
        self.listing_requests: list[ListingGapRequest] = []
        self._listing_reply = listing_reply or ListingGapReply(candidates=(), llm_calls=())

    async def detail(self, request: GapRequest) -> GapReply:
        self.requests.append(request)
        candidates = tuple(
            Candidate(
                field=name,
                entity_id=request.target.id,
                source_kind="llm",
                raw="19.90 EUR",
                normalized=Ok(PRICE),
                locator="text:0-9",
                independent=True,
            )
            for name in request.missing
        )
        return GapReply(candidates=candidates, llm_calls=(CALL,))

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        self.listing_requests.append(request)
        return self._listing_reply


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


def test_without_a_config_the_page_is_extracted_cold() -> None:
    result = _extract(_html({"@type": "Product", "name": "Widget One"}), None)
    assert result.mode == "adhoc"


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


def test_config_candidates_resolve_with_the_collectors() -> None:
    # A config value is learned from the page's other sources, so agreeing with them makes no `agreed` value, and the
    # structured value it agrees with is the one published.
    config = _config({"title": _steps("normalize-space(//h1)", "corroborated")})
    result = _extract(_html({"@type": "Product", "name": "Widget One", "url": PAGE_URL}), config)
    assert result.entity is not None
    title = result.entity["title"]
    assert (title.value, title.evidence, title.source_kind) == ("Widget One", "structured", "jsonld")


def test_covered_fields_are_never_asked_of_role_c() -> None:
    config = _config(
        {"title": _steps("normalize-space(//h1)"), "price": _steps('normalize-space(//p[@class="price"])')}
    )
    role_c = FakeRoleC()
    result = _extract(_html(body=PRICE_TEXT), config, role_c=role_c)
    assert (role_c.requests, result.llm_calls) == ([], ())
    assert result.outcome == "extracted"


def test_a_covered_required_field_the_config_misses_stays_missing() -> None:
    # §8.4: role C runs only for fields the config has no steps for; a step that stops matching is drift's to catch.
    config = _config(
        {"title": _steps("normalize-space(//h1)"), "price": _steps('normalize-space(//p[@class="price"])')}
    )
    role_c = FakeRoleC()
    result = _extract(_html(), config, role_c=role_c)
    assert role_c.requests == []
    assert result.entity is not None
    assert (result.entity["price"].status, result.outcome) == ("missing", "partial")


# Absent fields (D-1341): required fields the learning pages never stated.


def test_an_absent_field_is_not_asked_of_role_c_and_is_missing_as_absent() -> None:
    role_c = FakeRoleC()
    config = _config({"title": _steps("normalize-space(//h1)")}, absent=("price",))

    result = _extract(_html(), config, role_c=role_c)

    # The optional sku alone never makes role C run.
    assert (role_c.requests, result.llm_calls) == ([], ())
    assert result.entity is not None
    price = result.entity["price"]
    assert (price.status, price.reason, result.outcome) == ("missing", "absent", "partial")


def test_role_c_still_asks_for_the_other_missing_fields_beside_an_absent_one() -> None:
    role_c = FakeRoleC()

    _extract(_html(), _config({}, absent=("price",)), role_c=role_c)

    (request,) = role_c.requests
    assert request.missing == ("title", "sku")


def test_an_absent_field_a_page_states_publishes() -> None:
    offer = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    config = _config({"title": _steps("normalize-space(//h1)")}, absent=("price",))

    result = _extract(_html({"@type": "Product", "name": "Widget One", "offers": offer}), config)

    assert _published(result)["price"] == (PRICE, "structured")


def test_role_c_is_asked_only_for_the_fields_the_config_does_not_cover() -> None:
    role_c = FakeRoleC()
    result = _extract(_html(), _config({"title": _steps("normalize-space(//h1)")}), role_c=role_c)
    (request,) = role_c.requests
    assert request.missing == ("price", "sku")
    assert result.llm_calls == (CALL,)
    assert _published(result)["price"] == (PRICE, "llm_grounded")


def test_a_suspended_field_falls_back_to_role_c() -> None:
    # §4.9: a suspended field's pages fall back to cold-mode resolution, role C allowed.
    config = _config(
        {
            "title": _steps("normalize-space(//h1)"),
            "price": _steps('normalize-space(//p[@class="price"])', "suspended"),
        }
    )
    role_c = FakeRoleC()
    result = _extract(_html(body=PRICE_TEXT), config, role_c=role_c)
    assert [r.missing for r in role_c.requests] == [("price", "sku")]
    assert not any(c.source_kind == "config" and c.field == "price" for c in result.candidates)


def test_a_config_page_is_parsed_once_per_parser(parses: Parses) -> None:
    config = _config({"title": _steps("normalize-space(//h1)"), "sku": _steps("string(//h1/@data-sku)")})
    _extract(_html({"@type": "Product", "name": "Widget One"}, body=PRICE_TEXT), config)
    assert parses["selectolax"].calls == 1
    assert parses["lxml"].calls == 1


# --- listings ---

LISTING_URL = "https://shop.example.test/c/widgets"
LISTING = _schema(
    "listing",
    title=TITLE,
    url=FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
    page_title=FieldSpec(type=FieldType.TEXT, description="d", scope="page"),
)
CARDS = "".join(f'<div class="card"><h2>Widget {n}</h2><a href="/p/{n}">open</a></div>' for n in (1, 2, 3))
ROWS = {
    "row": {"xpath": '//div[@class="card"]'},
    "fields": {
        "title": _steps("normalize-space(h2)"),
        "url": {"steps": [{"xpath": "string(a/@href)", "post": [{"absolutize_url": {}}]}], "status": "uncorroborated"},
    },
    "next": None,
}


def _rows(result: ExtractionResult) -> list[dict[str, tuple[JsonValue, str | None]]]:
    return [{name: (o.value, o.evidence) for name, o in row.items() if o.status == "published"} for row in result.rows]


def test_without_structured_rows_the_configs_rows_are_the_listings() -> None:
    role_c = FakeRoleC()
    result = _extract(_html(body=CARDS), _config({}, page_kind="listing", listing=ROWS), LISTING, role_c, LISTING_URL)
    assert _rows(result) == [
        {
            "title": (f"Widget {n}", "config_uncorroborated"),
            "url": (f"https://shop.example.test/p/{n}", "config_uncorroborated"),
        }
        for n in (1, 2, 3)
    ]
    # The config runs the row fields, so role C is asked for no rows (and so for no page field either).
    assert (role_c.listing_requests, result.outcome, result.mode) == ([], "extracted", "config")


def test_structured_rows_win_over_the_configs() -> None:
    items = [
        {"@type": "ListItem", "position": n, "item": {"@type": "Product", "name": f"Item {n}", "url": f"/p/{n}"}}
        for n in (7, 8, 9)
    ]
    page = _html({"@type": "ItemList", "itemListElement": items}, body=CARDS)
    result = _extract(page, _config({}, page_kind="listing", listing=ROWS), LISTING, None, LISTING_URL)
    assert [row["title"] for row in _rows(result)] == [(f"Item {n}", "structured") for n in (7, 8, 9)]


def test_a_listing_config_without_rows_leaves_the_blocks_missing_row_fields_to_role_c() -> None:
    brand = FieldSpec(type=FieldType.TEXT, description="d")
    schema = LISTING.model_copy(update={"fields": {**LISTING.fields, "brand": brand}})
    cards = "".join(
        f'<li class="card"><h3><a href="/p/{n}">Widget {n}</a></h3><span>{n}.50 EUR</span><p>Acme {n}</p></li>'
        for n in (1, 2, 3)
    )
    reply = ListingGapReply(
        candidates=(
            Candidate(
                field="brand",
                entity_id="item_block:0:0",
                source_kind="llm",
                raw="Acme 1",
                normalized=Ok("Acme 1"),
                locator="text:9-15",
                independent=True,
            ),
        ),
        llm_calls=(CALL,),
    )
    role_c = FakeRoleC(reply)
    config = _config({"page_title": _steps("normalize-space(//h1)")}, page_kind="listing")
    result = _extract(_html(body=f"<ul>{cards}</ul>"), config, schema, role_c, LISTING_URL)
    (request,) = role_c.listing_requests
    # This order ranks no block reading, so each block is asked for the row fields its row does not publish but the
    # item URL; the page field the config runs is not asked again.
    assert [block.fields for block in request.blocks] == [("title", "brand")] * 3
    assert request.page_missing == ()
    assert [row.get("brand") for row in _rows(result)] == [("Acme 1", "llm_grounded"), None, None]
