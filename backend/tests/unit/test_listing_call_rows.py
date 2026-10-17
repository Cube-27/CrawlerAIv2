"""A listing's rows beside its structured rows (SPEC-05 §4.7 "Listings", Appendix A #59): call rows join the structured
row of their item and fill the fields it lacks, extend the listing with the items its listing blocks show, and items
a grown document states as microdata are rows beside the ones its script lists.

Pages are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_FILE, load_precedence
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    Headers,
    NetworkBody,
    network_file,
    sha256_hex,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld"
DATA = EngineData(
    vocabulary=Vocabulary.read(_FIXTURES),
    orders=load_precedence(Path(__file__).parents[2] / "data" / PRECEDENCE_FILE),
    calibration=None,
)
SITE = "https://shop.example.test"
LISTING_URL = f"{SITE}/c/widgets"
LISTING = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="listing",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "url": FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    },
)


def _url(n: int) -> str:
    return f"{SITE}/p/{n}"


def _product(n: int, *, price: bool = True) -> dict[str, Any]:
    node: dict[str, Any] = {"@type": "Product", "name": f"Widget {n}", "url": _url(n)}
    if price:
        node["offers"] = {"@type": "Offer", "price": f"{n}.50", "priceCurrency": "EUR"}
    return node


def _item_list(*items: Mapping[str, Any]) -> str:
    elements = [{"@type": "ListItem", "position": i + 1, "item": item} for i, item in enumerate(items)]
    node = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": elements}
    return f'<script type="application/ld+json">{json.dumps(node)}</script>'


def _card(n: int, *, microdata: bool = False) -> str:
    if microdata:
        return (
            f'<li class="card" itemscope itemtype="https://schema.org/Product">'
            f'<a itemprop="url" href="/p/{n}"><span itemprop="name">Widget {n}</span></a> <span>€{n}.50</span></li>'
        )
    return f'<li class="card"><a href="/p/{n}">Widget {n}</a> <span>€{n}.50</span></li>'


def _call_rows(numbers: Sequence[int]) -> list[dict[str, Any]]:
    return [{"href": f"/p/{n}", "label": f"Widget {n}", "price": f"€{n}.50"} for n in numbers]


def _page(head: str, cards: str, calls: Sequence[list[dict[str, Any]]] = (), aside: str = "") -> CaptureBundle:
    raw = f'<html lang="en"><head>{head}</head><body><h1>All widgets</h1><ul>{cards}</ul>{aside}</body></html>'.encode()
    bodies = [json.dumps({"results": rows}).encode() for rows in calls]
    entries = tuple(
        NetworkBody(
            url=f"https://api.example.test/widgets?page={i + 1}",
            status=200,
            content_type="application/json",
            sha256=sha256_hex(data),
            file=network_file(i),
            method="GET",
        )
        for i, data in enumerate(bodies)
    )
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=LISTING_URL,
        final_url=LISTING_URL,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="browser",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=entries,
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=raw, network=tuple(bodies))


def _extract(bundle: CaptureBundle) -> ExtractionResult:
    return asyncio.run(extract_page(bundle, LISTING, None, None, data=DATA))


def _rows(result: ExtractionResult) -> list[dict[str, JsonValue]]:
    return [{name: o.value for name, o in row.items() if o.status == "published"} for row in result.rows]


def _expected(n: int) -> dict[str, JsonValue]:
    return {"title": f"Widget {n}", "url": _url(n), "price": {"amount": f"{n}.50", "currency": "EUR"}}


def test_a_call_row_fills_the_field_its_structured_row_lacks() -> None:
    head = _item_list(*(_product(n, price=False) for n in (1, 2, 3)))
    cards = "".join(_card(n) for n in (1, 2, 3))

    result = _extract(_page(head, cards, [_call_rows([1, 2, 3])]))

    assert _rows(result) == [_expected(n) for n in (1, 2, 3)]
    # The call's value keeps its kind and bucket; the structured data's stays the structured data's.
    assert {(row["price"].source_kind, row["price"].evidence) for row in result.rows} == {("xhr", "network")}
    assert {row["title"].source_kind for row in result.rows} == {"jsonld"}


def test_a_call_row_matching_two_structured_rows_or_shared_by_two_call_rows_fills_nothing() -> None:
    head = _item_list(*(_product(n, price=False) for n in (1, 2, 3)))
    cards = "".join(_card(n) for n in (1, 2, 3))
    # Two call rows name item 1; items 2 and 3 have one each.
    rows = [*_call_rows([1, 2, 3]), {"href": "/p/1", "label": "Widget 1 again", "price": "€9.50"}]

    result = _extract(_page(head, cards, [rows]))

    assert [set(row) for row in _rows(result)] == [
        {"title", "url"},
        {"title", "url", "price"},
        {"title", "url", "price"},
    ]


def test_call_rows_of_items_the_listing_shows_beyond_its_script_extend_the_rows() -> None:
    # The script states the first batch; a load-more's call brought the second, shown as blocks of the same list.
    head = _item_list(*(_product(n) for n in (1, 2, 3)))
    cards = "".join(_card(n) for n in range(1, 7))

    result = _extract(_page(head, cards, [_call_rows([4, 5, 6])]))

    assert [row["url"] for row in _rows(result)] == [_url(n) for n in range(1, 7)]
    # The item URLs are proved by the listing's links; the prices, which the script states for other items, admit by
    # equality only (`collect.admission`), so the later rows carry their URLs and are partial.
    assert [set(row) for row in _rows(result)][3:] == [{"url"}] * 3
    assert {row["url"].source_kind for row in result.rows[3:]} == {"xhr"}


def test_call_rows_of_items_outside_the_listing_blocks_are_not_rows() -> None:
    # Related items shown in a block group of their own, apart from the listing's.
    head = _item_list(*(_product(n) for n in (1, 2, 3)))
    cards = "".join(_card(n) for n in (1, 2, 3))
    aside = "<aside><ol>" + "".join(f'<li><a href="/p/{n}">Widget {n}</a> <b>€{n}.50</b></li>' for n in (7, 8, 9))
    aside += "</ol></aside>"

    result = _extract(_page(head, cards, [_call_rows([7, 8, 9])], aside=aside))

    assert [row["url"] for row in _rows(result)] == [_url(n) for n in (1, 2, 3)]


def test_microdata_items_of_a_grown_list_are_rows_beside_the_listed_ones() -> None:
    head = _item_list(*(_product(n) for n in (1, 2, 3)))
    cards = "".join(_card(n, microdata=n > 3) for n in range(1, 7))

    result = _extract(_page(head, cards))

    assert [(row["title"], row["url"]) for row in _rows(result)] == [(f"Widget {n}", _url(n)) for n in range(1, 7)]


def test_microdata_items_merged_with_listed_ones_are_one_row_each() -> None:
    head = _item_list(*(_product(n) for n in (1, 2, 3)))
    cards = "".join(_card(n, microdata=True) for n in range(1, 7))

    result = _extract(_page(head, cards))

    assert [row["url"] for row in _rows(result)] == [_url(n) for n in range(1, 7)]
