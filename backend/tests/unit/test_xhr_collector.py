"""The captured network JSON collector (SPEC-05 §4.5): each captured body is a JSON document, admitted by the same rule
as embedded JSON state, and addressed by its index in the bundle."""

import hashlib
import json
from datetime import UTC, datetime

from crawlerai.collect.admission import Admitted
from crawlerai.collect.base import Candidate
from crawlerai.collect.xhr import XhrCollector
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import NetworkBody, network_file

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={"url": FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url")},
)
OG_URL = Candidate(
    field="url",
    entity_id="page",
    source_kind="og",
    raw=PAGE_URL,
    normalized=Ok(PAGE_URL),
    locator="meta:og:url",
    independent=True,
)


def _collect(network: tuple[bytes, ...], *others: Candidate, body: str = "") -> Admitted:
    page = ParsedPage(f"<html><body><p>{body}</p></body></html>", network)
    return XhrCollector().collect(page, SCHEMA, CTX, others)


def test_a_body_value_equal_to_another_kinds_candidate_is_admitted_and_not_independent() -> None:
    # The relative URL resolves against the page's base URL to the same URL (SPEC-04 url equality).
    result = _collect((b'{"x": 1}', b'{"data": {"href": "/p/1"}}'), OG_URL)

    assert result == Admitted(
        candidates=(
            Candidate(
                field="url",
                entity_id="page",
                source_kind="xhr",
                raw="/p/1",
                normalized=Ok(PAGE_URL),
                locator="xhr:1:$['data']['href']",
                independent=False,
            ),
        )
    )


def test_a_visible_body_value_of_a_field_without_candidates_is_independent() -> None:
    result = _collect((b'["https://shop.example.test/p/2"]',), body="see https://shop.example.test/p/2")

    assert [(c.locator, c.entity_id, c.independent) for c in result.candidates] == [("xhr:0:$[0]", "page", True)]


def test_a_body_that_is_not_utf8_json_is_skipped_with_a_diagnostic_and_keeps_its_index() -> None:
    result = _collect((b"<html>", b"\xff[]", b'["/p/1"]'), OG_URL)

    assert [c.locator for c in result.candidates] == ["xhr:2:$[0]"]
    assert [d.split(":", 2)[:2] for d in result.diagnostics] == [["xhr", "0"], ["xhr", "1"]]


# --- listing rows from captured calls (Appendix A #58) ---

LISTING = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic_listing",
    page_kind="listing",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
        "price": FieldSpec(type=FieldType.MONEY, description="d"),
        "next_page_url": FieldSpec(type=FieldType.URL, description="d", scope="page"),
    },
)
_PRICES = ["€12.50", "€7.25", "€30.00", "€4.10"]


def _call(index: int, url: str, body: object) -> tuple[NetworkBody, bytes]:
    data = json.dumps(body).encode()
    entry = NetworkBody(
        url=url,
        status=200,
        content_type="application/json",
        sha256=hashlib.sha256(data).hexdigest(),
        file=network_file(index),
        method="GET",
    )
    return entry, data


def _listing_page(*calls: tuple[NetworkBody, bytes], shown: list[str]) -> ParsedPage:
    html = "<html><body><ul>" + "".join(f"<li>{text}</li>" for text in shown) + "</ul></body></html>"
    return ParsedPage(html, tuple(data for _, data in calls), tuple(entry for entry, _ in calls))


def _products(prices: list[str]) -> list[dict[str, object]]:
    return [{"id": i, "name": f"Lamp model {i}", "price": price} for i, price in enumerate(prices)]


def test_a_listings_call_gives_one_row_per_item_with_the_fields_its_rows_prove() -> None:
    call = _call(0, "https://api.example.test/products?page=1", {"total": 4, "items": _products(_PRICES)})
    # The last item's price is not shown: the path its three shown prices prove reads it all the same.
    shown = [f"Lamp model {i} {price}" for i, price in enumerate(_PRICES[:3])] + ["Lamp model 3"]

    result = XhrCollector().collect(_listing_page(call, shown=shown), LISTING, CTX, ())

    rows = [f"xhr:0:$['items'][{i}]" for i in range(4)]
    assert [(row.id, row.types, row.parent) for row in result.rows] == [(row, ("array_row",), None) for row in rows]
    assert [row.id for row in result.entities] == rows
    prices = [(c.entity_id, c.raw, c.locator, c.independent) for c in result.candidates if c.field == "price"]
    assert prices == [(row, price, f"{row}['price']", True) for row, price in zip(rows, _PRICES, strict=True)]
    # Text admits by equality only, and nothing else names the titles.
    assert [c for c in result.candidates if c.field == "title"] == []


def test_the_calls_of_one_endpoint_give_the_rows_of_each_in_capture_order() -> None:
    first = _call(0, "https://api.example.test/products?page=1", {"items": _products(_PRICES[:3])})
    second = _call(1, "https://api.example.test/products?page=2", {"items": _products(["€1.99", "€2.99", "€3.99"])})
    shown = [*_PRICES[:3], "€1.99", "€2.99", "€3.99"]

    result = XhrCollector().collect(_listing_page(first, second, shown=shown), LISTING, CTX, ())

    assert [row.id for row in result.rows] == [f"xhr:{n}:$['items'][{i}]" for n in (0, 1) for i in range(3)]


def test_rows_whose_fields_nothing_proves_are_not_rows_and_the_call_is_admitted_as_before() -> None:
    call = _call(0, "https://api.example.test/products", {"items": _products(["", "", ""])})

    result = XhrCollector().collect(_listing_page(call, shown=[f"Lamp model {i}" for i in range(3)]), LISTING, CTX, ())

    assert (result.rows, result.candidates) == ((), ())


def test_a_detail_page_reads_no_rows() -> None:
    call = _call(0, "https://api.example.test/products", {"items": _products(_PRICES)})
    page = _listing_page(call, shown=_PRICES)

    result = XhrCollector().collect(page, SCHEMA, CTX, ())

    assert result.rows == ()
