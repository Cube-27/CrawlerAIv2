"""The embedded JSON state collector (SPEC-05 §4.5, ARCHITECTURE §8.1): JSON in inline scripts, admitted only by
equality to another source kind's candidate (not independent, owned by that candidate's entity) or, for a field with no
such candidate whose type has a checkable syntax, by visibility in the page text (independent, owned by the page, or by
the array row holding it)."""

import json
from datetime import UTC, datetime
from html import escape

import pytest
from pydantic import JsonValue

from crawlerai.collect.admission import Admitted
from crawlerai.collect.base import ARRAY_ROW, PAGE, Candidate, Entity
from crawlerai.collect.js_state import JsStateCollector
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Context, NormalizeResult, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    },
)
SCRIPT = "/html[1]/head[1]/script[1]"


def _page(script: str, body: str = "", script_type: str | None = None) -> ParsedPage:
    type_attribute = "" if script_type is None else f' type="{script_type}"'
    return ParsedPage(f"<html><head><script{type_attribute}>{script}</script></head><body>{escape(body)}</body></html>")


def _state(document: JsonValue, body: str = "") -> ParsedPage:
    return _page(f"window.__STATE__ = {json.dumps(document)};", body)


def _candidate(
    field: str,
    raw: JsonValue,
    normalized: NormalizeResult,
    *,
    source_kind: SourceKind = "js_state",
    entity_id: str = "page",
    locator: str,
    independent: bool,
) -> Candidate:
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind=source_kind,
        raw=raw,
        normalized=normalized,
        locator=locator,
        independent=independent,
    )


EUR_19_99 = Ok({"amount": "19.99", "currency": "EUR"})
JSONLD_PRICE = _candidate(
    "price",
    {"price": "19.99", "priceCurrency": "EUR"},
    EUR_19_99,
    source_kind="jsonld",
    entity_id="jsonld:0:$['offers']",
    locator="jsonld:0:$['offers']",
    independent=True,
)


def _collect(page: ParsedPage, *others: Candidate) -> Admitted:
    return JsStateCollector().collect(page, SCHEMA, CTX, others)


def test_a_value_equal_to_another_kinds_candidate_is_owned_by_its_entity_and_not_independent() -> None:
    # Not visible: equality alone admits it. Equality is the field type's (SPEC-04), not the raw string's.
    result = _collect(_state({"p": {"cost": "€19.99"}}), JSONLD_PRICE)

    assert result == Admitted(
        candidates=(
            _candidate(
                "price",
                "€19.99",
                EUR_19_99,
                entity_id="jsonld:0:$['offers']",
                locator=f"js_state:{SCRIPT}:$['p']['cost']",
                independent=False,
            ),
        )
    )


# The script-reading tests probe with a visible price: a price is admitted by visibility alone (§8.1).
@pytest.mark.parametrize(
    "script",
    [
        'window.__S = {"cost": "€5.00"};',
        'var s={"cost": "€5.00"}',
        'let s = {"cost": "€5.00"}; init(s);',
        'if (x) { go(); }\nconst s =\n {"cost": "€5.00"}\n;',
    ],
)
def test_the_json_after_an_assignment_is_the_state(script: str) -> None:
    result = _collect(_page(script, body="€5.00"))

    assert [(c.field, c.locator) for c in result.candidates] == [("price", f"js_state:{SCRIPT}:$['cost']")]


# Array rows (Appendix A #55): an object item of an array of two or more objects is one of a set of items.
ROWS = "js_state:0:$['items']"


def test_a_visible_value_in_an_array_row_is_owned_by_its_row() -> None:
    document: JsonValue = {
        "items": [{"url": "/p/1", "cost": "€19.99"}, {"url": "https://other.example.test/p/2", "cost": "€5"}]
    }

    result = _collect(_state(document, body="Now €19.99, also €5.00"))

    assert [(c.entity_id, c.independent) for c in result.candidates if c.field == "price"] == [
        (f"{ROWS}[0]", True),
        (f"{ROWS}[1]", True),
    ]
    assert result.entities == (
        Entity(id=f"{ROWS}[0]", types=(ARRAY_ROW,), urls=(PAGE_URL,), parent=PAGE),
        Entity(id=f"{ROWS}[1]", types=(ARRAY_ROW,), urls=("https://other.example.test/p/2",), parent=PAGE),
    )


# One value repeated under many paths (D-1343): one candidate per field, normalized value and owner.
