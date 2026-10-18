"""The item layer's align step (listings spec, "Rows from blocks"): which document a block leads to, what names it, and
which values it gives, from structure, types and standards only. Pages are synthetic (RFC 2606 names)."""

from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.collect.items.align import AMBIGUOUS_IN_BLOCK, Items, align
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Ambiguous, Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://jobs.example.test/search"
CTX = Context(html_lang="en", captured_at=datetime(2026, 10, 18, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
_TITLE = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
_URL = FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url")
_PRICE = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")


def _schema(page_kind: str = "listing", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        name="t_listing",
        origin="user",
        status="active",
        page_kind=page_kind,  # type: ignore[arg-type]
        fields=fields or {"title": _TITLE, "url": _URL, "price": _PRICE},
    )


LISTING = _schema()


def _groups(body: str, schema: SchemaDef = LISTING) -> tuple[Items, ...]:
    return align(ParsedPage(f"<html><body><h1>Results</h1>{body}</body></html>"), schema, CTX)


def _rows(body: str, schema: SchemaDef = LISTING) -> list[dict[str, JsonValue]]:
    groups = _groups(body, schema)
    if not groups:
        return []
    first = groups[0]
    return [
        {
            c.field: c.normalized.value
            for c in first.candidates
            if c.entity_id == block.entity.id and isinstance(c.normalized, Ok)
        }
        for block in first.blocks
    ]


def _repeat(block: str, n: int = 4) -> str:
    return "<ul>" + "".join(block.format(i=i) for i in range(n)) + "</ul>"


def _url(path: str) -> str:
    return f"https://jobs.example.test{path}"


def test_a_block_linking_to_its_item_and_its_seller_takes_the_link_its_heading_holds() -> None:
    # HTML Standard §4.3.6: a heading labels the content it heads.
    body = _repeat('<li class="r"><h2><a href="/job/{i}">Job {i}</a></h2><a href="/employer/{i}">Employer {i}</a></li>')

    assert [row["url"] for row in _rows(body)] == [_url(f"/job/{i}") for i in range(4)]


def test_sections_each_holding_a_list_of_items_are_no_items_themselves() -> None:
    section = (
        '<section class="dept"><h2>Department {d}</h2><ul>'
        + "".join(
            f'<li class="job"><a href="/job/{{d}}-{n}">Job {{d}}-{n}</a><span>Remote</span></li>' for n in range(4)
        )
        + "</ul></section>"
    )
    body = "".join(section.format(d=d) for d in range(3))

    rows = _rows(body)
    assert len(rows) == 4
    assert all(str(row["url"]).startswith(_url("/job/")) for row in rows)


def test_a_struck_former_price_is_not_the_price_and_two_shown_prices_decline() -> None:
    # HTML Standard §4.5.4 `s`, §4.7.2 `del`: text no longer accurate.
    struck = '<li class="c"><a href="/p/{i}">Kettle {i}</a><del>{i}9.99 EUR</del> <span>1{i}.50 EUR</span></li>'
    two = '<li class="c"><a href="/p/{i}">Kettle {i}</a><span>{i}9.99 EUR</span> <span>1{i}.50 EUR</span></li>'

    assert [row["price"] for row in _rows(_repeat(struck))] == [
        {"amount": f"1{i}.50", "currency": "EUR"} for i in range(4)
    ]
    (group,) = _groups(_repeat(two))
    prices = [c.normalized for c in group.candidates if c.field == "price"]
    assert len(prices) == 4
    assert all(isinstance(p, Ambiguous) and p.reason == AMBIGUOUS_IN_BLOCK for p in prices)
