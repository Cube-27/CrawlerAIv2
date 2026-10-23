"""Listing induction: a listing's row selector and row-field
steps induced from the item layer's blocks across the sample, verified by the engine executor. Pages are synthetic
(`example.test`)."""

from datetime import UTC, datetime
from pathlib import Path

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.executor import EngineExecutor, row_id
from crawlerai.config_ir.induction import Published, SamplePage
from crawlerai.config_ir.listing_induction import (
    ListingInduction,
    induce_listing,
)
from crawlerai.config_ir.model import ExtractionConfigIR, ListingSpec
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import SchemaDef

BASE = "https://shop.example.test/list"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=BASE, page_url=BASE)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
SCHEMA = SchemaDef.model_validate(
    {
        "id": SchemaId(uuid7()),
        "origin": "user",
        "status": "active",
        "name": "synthetic_listing",
        "page_kind": "listing",
        "fields": {
            "title": {"type": "text", "required": True, "description": "d", "schema_org": "Product.name"},
            "url": {"type": "url", "required": True, "description": "d", "schema_org": "Product.url"},
            "badge": {"type": "text", "description": "d"},
        },
    }
)


def _card(page: int, n: int) -> str:
    item = f"{page}-{n}"
    return (
        f"<li class='card'><a href='/p/{item}'><h3>Item {item}</h3></a>"
        f"<img src='/i/{item}.jpg' alt='Item {item}'><span class='badge'>Tag {item}</span></li>"
    )


def _html(page: int, cards: int = 4) -> str:
    grid = "".join(_card(page, n) for n in range(cards))
    return f"<html><body><nav><a href='/'>Home</a></nav><ul class='grid'>{grid}</ul></body></html>"


def _row(page: int, n: int, *, badge: bool) -> dict[str, Published]:
    item = f"{page}-{n}"
    row = {
        "title": Published(f"Item {item}", "dom:/html/body/ul/li/a/h3"),
        "url": Published(f"https://shop.example.test/p/{item}", "dom:/html/body/ul/li/a"),
    }
    if badge:  # a value only role C stated, grounded as a span of the cleaned text
        row["badge"] = Published(f"Tag {item}", "text:0-5")
    return row


def _sample(page: int, *, badge: bool = True, cards: int = 4) -> SamplePage:
    rows = tuple(_row(page, n, badge=badge) for n in range(cards))
    return SamplePage(ParsedPage(_html(page, cards)), CTX, {}, rows)


SAMPLE = [_sample(page) for page in range(1, 4)]


def _induced() -> ListingInduction:
    return induce_listing(SCHEMA, SAMPLE, VOCABULARY)


def _rows(listing: ListingSpec, html: str) -> list[dict[str, object]]:
    ir = ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": SCHEMA.name, "digest": "0" * 64},
            "page_kind": "listing",
            "fetch": {"method": "http"},
            "fields": {},
            "listing": listing.model_dump(by_alias=True),
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )
    executed = EngineExecutor(ir, VOCABULARY).execute(ParsedPage(html), SCHEMA, CTX)
    rows: dict[str, dict[str, object]] = {row_id(n): {} for n in range(len(executed.rows))}
    for c in executed.candidates:
        if isinstance(c.normalized, Ok) and c.entity_id in rows:
            rows[c.entity_id][c.field] = c.normalized.value
    return list(rows.values())


def test_every_row_field_is_induced_and_reproduces_on_a_page_learning_never_read() -> None:
    induced = _induced()
    assert induced.listing is not None
    assert (set(induced.listing.fields), induced.to_synthesize) == ({"title", "url", "badge"}, {})
    rows = _rows(induced.listing, _html(9, cards=5))
    assert rows[4] == {"title": "Item 9-4", "url": "https://shop.example.test/p/9-4", "badge": "Tag 9-4"}
    assert len(rows) == 5


def test_published_rows_no_block_holds_do_not_keep_a_field_from_being_induced() -> None:
    # A source listing more items than the page shows: rows past the grid's cards are left to validation.
    sample = [
        SamplePage(s.page, CTX, {}, (*s.rows, *(_row(page, n, badge=True) for n in range(4, 8))))
        for page, s in enumerate(SAMPLE, start=1)
    ]
    induced = induce_listing(SCHEMA, sample, VOCABULARY)
    assert induced.listing is not None
    assert (set(induced.listing.fields), induced.to_synthesize) == ({"title", "url", "badge"}, {})
