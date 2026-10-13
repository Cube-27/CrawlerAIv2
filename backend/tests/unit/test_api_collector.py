"""The API recipe collector (SPEC-09 §4.8): an `api` capture's JSON read through the recipe's map, each value an `api`
candidate located as `api:<recipe id>:<normalized path>`, owned by the page on a detail page and by the rows the
recipe's `rows` query selects on a listing.

The documents are synthetic.
"""

import json
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.api import ApiCollector, read_map
from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.config import Executed
from crawlerai.collect.locator import parse_locator
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
        version=1,
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


def _collect(document: JsonValue, schema: SchemaDef, collector: ApiCollector) -> Executed:
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


def test_a_value_absent_or_not_one_scalar_gives_no_candidate() -> None:
    document = {"data": {"name": ["A", "B"], "price": 3}}  # no currency: the joined money entry reads nothing

    executed = _collect(document, DETAIL, ApiCollector("cfg1", DETAIL_MAP))

    assert executed.candidates == ()


def test_a_body_that_is_not_json_is_a_diagnostic() -> None:
    executed = ApiCollector("cfg1", DETAIL_MAP).collect(ParsedPage("<html></html>"), DETAIL, CTX)

    assert (executed.rows, executed.candidates) == ((), ())
    assert len(executed.diagnostics) == 1
    assert executed.diagnostics[0].startswith("api:cfg1: not JSON")


def test_a_map_field_outside_the_schema_is_a_diagnostic() -> None:
    collector = ApiCollector("cfg1", {"title": "$['data']['name']", "colour": "$['data']['colour']"})

    executed = _collect({"data": {"name": "Lamp", "colour": "red"}}, DETAIL, collector)

    assert [c.field for c in executed.candidates] == ["title"]
    assert executed.diagnostics == ("api:cfg1:colour: not a field of the schema",)


def test_a_listing_reads_row_fields_relative_to_each_row_and_page_fields_at_the_root() -> None:
    document = {"category": "Lamps", "items": [{"name": "Desk Lamp"}, "not an object", {"name": "Floor Lamp"}]}
    collector = ApiCollector("cfg1", {"title": "$['name']", "category": "$['category']"}, rows="$['items'][*]")

    executed = _collect(document, LISTING, collector)

    assert [(row.id, row.kind, row.parent) for row in executed.rows] == [
        ("api:cfg1:$['items'][0]", "ListItem", None),
        ("api:cfg1:$['items'][2]", "ListItem", None),
    ]
    assert _values(executed) == [
        ("category", PAGE, "api:cfg1:$['category']", "Lamps"),
        ("title", "api:cfg1:$['items'][0]", "api:cfg1:$['items'][0]['name']", "Desk Lamp"),
        ("title", "api:cfg1:$['items'][2]", "api:cfg1:$['items'][2]['name']", "Floor Lamp"),
    ]


def test_an_empty_rows_selection_gives_no_rows() -> None:
    collector = ApiCollector("cfg1", {"title": "$['name']"}, rows="$['items'][*]")

    executed = _collect({"items": []}, LISTING, collector)

    assert (executed.rows, executed.candidates) == ((), ())


_SCALARS = st.one_of(st.text(max_size=20), st.integers(), st.floats(allow_nan=False, allow_infinity=False))
_KEYS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8)


@given(st.dictionaries(_KEYS, _SCALARS, min_size=1, max_size=6))
def test_every_candidate_locator_names_the_recipe_and_reads_back_its_raw_value(document: dict[str, JsonValue]) -> None:
    schema = _schema("detail", **{f"f{i}": FieldSpec(type=FieldType.TEXT, description="d") for i in range(len(document))})
    collector = ApiCollector("r-7", {f"f{i}": f"$['{key}']" for i, key in enumerate(document)})

    executed = _collect(document, schema, collector)

    candidates: list[Candidate] = list(executed.candidates)
    assert len(candidates) == len(document)
    for found in candidates:
        locator = parse_locator(found.locator)
        assert locator.scheme == "api"
        assert locator.parts[0] == "r-7"
        assert read_map(locator.parts[1], document) == found.raw
