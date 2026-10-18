"""The API recipe collector (SPEC-09 §4.8): an `api` capture's JSON read through the recipe's map, each value an `api`
candidate located as `api:<recipe id>:<normalized path>`, owned by the page on a detail page and by the rows the
recipe's `rows` query selects on a listing.

The documents are synthetic.
"""

import json
from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.collect.api import ApiCollector
from crawlerai.collect.base import PAGE
from crawlerai.collect.config import Executed
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

CTX = Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url="https://shop.example.test/p/1")
DETAIL_MAP = {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"}


def _schema(page_kind: PageKind, **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields=fields,
    )


DETAIL = _schema(
    "detail",
    title=FieldSpec(type=FieldType.TEXT, description="d", required=True),
    price=FieldSpec(type=FieldType.MONEY, description="d"),
)
LISTING = _schema(
    "listing",
    title=FieldSpec(type=FieldType.TEXT, description="d", required=True),
    category=FieldSpec(type=FieldType.TEXT, description="d", scope="page"),
)


def _collect(document: object, schema: SchemaDef, collector: ApiCollector) -> Executed:
    return collector.collect(ParsedPage(json.dumps(document)), schema, CTX)


def _values(executed: Executed) -> list[tuple[str, str, str, JsonValue]]:
    return [
        (c.field, c.entity_id, c.locator, c.normalized.value if isinstance(c.normalized, Ok) else None)
        for c in executed.candidates
    ]


def test_a_detail_page_values_are_api_candidates_of_the_page() -> None:
    document = {"data": {"name": "Desk Lamp", "price": 19.5, "currency": "EUR"}}

    executed = _collect(document, DETAIL, ApiCollector("cfg1", DETAIL_MAP))

    assert executed.rows == ()
    assert {c.source_kind for c in executed.candidates} == {"api"}
    assert all(c.independent for c in executed.candidates)
    assert _values(executed) == [
        ("title", PAGE, "api:cfg1:$['data']['name']", "Desk Lamp"),
        ("price", PAGE, "api:cfg1:$['data']['price']+$['data']['currency']", {"amount": "19.5", "currency": "EUR"}),
    ]
    assert executed.diagnostics == ()


def test_a_listing_reads_row_fields_relative_to_each_row_and_page_fields_at_the_root() -> None:
    document = {"category": "Lamps", "items": [{"name": "Desk Lamp"}, "not an object", {"name": "Floor Lamp"}]}
    collector = ApiCollector("cfg1", {"title": "$['name']", "category": "$['category']"}, rows="$['items'][*]")

    executed = _collect(document, LISTING, collector)

    assert [(row.id, row.types, row.parent) for row in executed.rows] == [
        ("api:cfg1:$['items'][0]", ("ListItem",), None),
        ("api:cfg1:$['items'][2]", ("ListItem",), None),
    ]
    assert _values(executed) == [
        ("category", PAGE, "api:cfg1:$['category']", "Lamps"),
        ("title", "api:cfg1:$['items'][0]", "api:cfg1:$['items'][0]['name']", "Desk Lamp"),
        ("title", "api:cfg1:$['items'][2]", "api:cfg1:$['items'][2]['name']", "Floor Lamp"),
    ]
