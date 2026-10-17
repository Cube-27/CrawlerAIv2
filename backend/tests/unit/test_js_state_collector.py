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
from crawlerai.collect.js_state import JsStateCollector, state_documents
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
PRODUCT = "jsonld:0:$"
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


def _prices(page: ParsedPage, *others: Candidate) -> list[tuple[str, bool]]:
    # A text field takes any visible string, `€19.99` too, so price tests look at the price field only.
    return [(c.entity_id, c.independent) for c in _collect(page, *others).candidates if c.field == "price"]


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


def test_a_visible_value_of_a_checkable_field_without_candidates_is_owned_by_the_page_and_independent() -> None:
    result = _collect(_state({"items": [{"cost": "€19.99"}]}, body="Now €19.99"))

    assert result.candidates == (
        _candidate(
            "price",
            "€19.99",
            EUR_19_99,
            locator=f"js_state:{SCRIPT}:$['items'][0]['cost']",
            independent=True,
        ),
    )


def test_a_visible_value_of_a_text_field_without_candidates_is_not_admitted() -> None:
    # Any visible string normalizes as text, so visibility alone does not say the leaf is the title.
    page = _state({"label": "Synthetic Widget", "cost": "€5.00"}, body="Synthetic Widget €5.00")

    assert [(c.field, c.locator) for c in _collect(page).candidates] == [("price", f"js_state:{SCRIPT}:$['cost']")]


def test_a_text_field_admits_by_equality() -> None:
    jsonld_title = _candidate(
        "title", "Synthetic Widget", Ok("Synthetic Widget"), source_kind="jsonld", locator=PRODUCT, independent=True
    ).model_copy(update={"entity_id": PRODUCT})

    result = _collect(_state({"name": "Synthetic  Widget"}), jsonld_title)

    assert [(c.field, c.entity_id, c.independent) for c in result.candidates] == [("title", PRODUCT, False)]


def test_a_value_neither_equal_nor_visible_is_not_admitted() -> None:
    result = _collect(_state({"a": "Hidden Name", "b": "€5.00", "c": "€7.00"}, body="Other text €7.00"))

    assert [c.locator for c in result.candidates] == [f"js_state:{SCRIPT}:$['c']"]


def test_a_field_with_candidates_admits_by_equality_only() -> None:
    # `was` is visible and a valid price, but the field has a JSON-LD price it does not equal.
    page = _state({"was": "€24.99", "cost": "€19.99"}, body="€24.99")

    assert _prices(page, JSONLD_PRICE) == [("jsonld:0:$['offers']", False)]


def test_a_value_both_equal_and_visible_is_not_independent() -> None:
    assert _prices(_state({"cost": "€19.99"}, body="€19.99"), JSONLD_PRICE) == [("jsonld:0:$['offers']", False)]


def test_a_candidate_that_did_not_normalize_still_makes_the_field_admit_by_equality_only() -> None:
    invalid = JSONLD_PRICE.model_copy(update={"normalized": Invalid("no_currency")})
    page = _state({"cost": "€19.99"}, body="€19.99")

    assert _prices(page) == [("page", True)]
    assert _prices(page, invalid) == []


def test_candidates_of_the_same_source_kind_are_not_anchors() -> None:
    own = JSONLD_PRICE.model_copy(update={"source_kind": "js_state", "locator": "js_state:/html[1]/script[1]:$"})

    assert _prices(_state({"cost": "€19.99"}, body="€19.99"), own) == [("page", True)]


def test_a_value_equal_to_candidates_of_two_entities_is_admitted_once_for_each() -> None:
    other_offer = JSONLD_PRICE.model_copy(update={"entity_id": "jsonld:1:$['offers']", "locator": "jsonld:1:$"})
    same_offer_og = JSONLD_PRICE.model_copy(update={"source_kind": "og", "locator": "meta:product:price:amount"})

    result = _collect(_state({"cost": "€19.99"}), JSONLD_PRICE, other_offer, same_offer_og)

    assert [c.entity_id for c in result.candidates] == ["jsonld:0:$['offers']", "jsonld:1:$['offers']"]


def test_booleans_null_and_unnormalizable_values_are_not_candidates() -> None:
    result = _collect(_state({"a": True, "b": None, "c": 7, "d": "", "e": "€5.00"}, body="true null 7 €5.00"))

    assert [c.locator for c in result.candidates] == [f"js_state:{SCRIPT}:$['e']"]


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


@pytest.mark.parametrize(
    "script",
    [
        'go({"was": "€5.00"});',  # no assignment
        'var f = x => ({"was": "€5.00"});',  # an initializer that is not JSON
        'var n = "€5.00";',  # a scalar initializer is a script variable, not state
    ],
)
def test_script_code_that_is_not_an_assignment_of_json_is_not_state(script: str) -> None:
    page = ParsedPage(
        f'<html><head><script>{script}</script><script>var s = {{"cost": "€5.00"}}</script></head>'
        "<body>€5.00</body></html>"
    )

    assert [c.locator for c in _collect(page).candidates] == ["js_state:/html[1]/head[1]/script[2]:$['cost']"]


@pytest.mark.parametrize(
    "script",
    [
        'window.a = {"cost": "€5.00"}; window.b = {"was": "€5.00"};',
        'var n = 1; var f = x => x; window.a = {"cost": "€5.00"}; window.b = {"was": "€5.00"};',
    ],
)
def test_every_assignment_of_json_in_a_script_is_read_in_order(script: str) -> None:
    assert [c.locator for c in _collect(_page(script, body="€5.00")).candidates] == [
        f"js_state:{SCRIPT}:$['cost']",
        f"js_state:{SCRIPT}:$['was']",
    ]


def test_an_assignment_written_inside_a_state_value_is_not_read() -> None:
    script = 'window.a = {"code": "var b = [1, 2]"};'

    assert [d.data for d in state_documents(_page(script), [])] == [{"code": "var b = [1, 2]"}]


def test_an_application_json_script_is_a_document() -> None:
    page = _page('{"cost": "€5.00"}', body="€5.00", script_type="application/json")

    assert [c.locator for c in _collect(page).candidates] == [f"js_state:{SCRIPT}:$['cost']"]


def test_an_invalid_application_json_script_is_skipped_with_a_diagnostic() -> None:
    page = _page('{"name": NaN}', body="€5.00", script_type="application/json")

    result = _collect(page)

    assert result.candidates == ()
    assert result.diagnostics == (f"js_state:{SCRIPT}: invalid JSON (NaN is not JSON)",)


def test_json_ld_blocks_are_not_state() -> None:
    page = ParsedPage(
        '<html><head><script type="application/ld+json">{"was": "€5.00"}</script>'
        '<script type="application/json">{"cost": "€5.00"}</script></head><body>€5.00</body></html>'
    )

    assert [c.locator for c in _collect(page).candidates] == ["js_state:/html[1]/head[1]/script[2]:$['cost']"]


def test_each_script_is_addressed_by_its_own_xpath() -> None:
    page = ParsedPage(
        "<html><head><script>var a = 1;</script></head><body><p>€5.00</p>"
        '<script>window.s = {"cost": "€5.00"}</script></body></html>'
    )

    assert [c.locator for c in _collect(page).candidates] == ["js_state:/html[1]/body[1]/script[1]:$['cost']"]


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


def test_one_object_in_an_array_is_not_a_row() -> None:
    result = _collect(_state({"offers": [{"cost": "€19.99"}], "tags": ["a", {"cost": "€5.00"}]}, body="€19.99 €5.00"))

    assert _prices(_state({"offers": [{"cost": "€19.99"}]}, body="€19.99")) == [(PAGE, True)]
    assert [c.entity_id for c in result.candidates] == [PAGE, PAGE]
    assert result.entities == ()


def test_a_value_admitted_by_equality_in_a_row_keeps_its_anchors_owner() -> None:
    page = _state({"items": [{"cost": "€19.99"}, {"cost": "€5.00"}]}, body="€19.99 €5.00")

    result = _collect(page, JSONLD_PRICE)

    assert [(c.entity_id, c.independent) for c in result.candidates] == [("jsonld:0:$['offers']", False)]
    assert result.entities == ()


def test_a_rows_urls_stop_at_its_nested_rows_and_a_nested_row_names_its_parent() -> None:
    document: JsonValue = {
        "items": [
            {"link": "/p/9", "image": "https://cdn.example.test/9.jpg", "sizes": [{"u": "/p/9?s=1"}, {"cost": "€7"}]},
            {"link": "/p/8"},
        ]
    }

    result = _collect(_state(document, body="€7.00"))

    outer, inner = f"{ROWS}[0]", f"{ROWS}[0]['sizes'][1]"
    assert [c.entity_id for c in result.candidates] == [inner]
    assert result.entities == (
        Entity(
            id=outer,
            types=(ARRAY_ROW,),
            urls=("https://shop.example.test/p/9", "https://cdn.example.test/9.jpg"),
            parent=PAGE,
        ),
        Entity(id=inner, types=(ARRAY_ROW,), urls=(), parent=outer),
    )


def test_rows_of_two_documents_in_one_script_are_two_entities() -> None:
    script = 'window.a = [{"cost": "€5.00"}, {}]; window.b = [{"cost": "€5.00"}, {}];'

    result = _collect(_page(script, body="€5.00"))

    assert [c.entity_id for c in result.candidates] == ["js_state:0:$[0]", "js_state:1:$[0]"]
    assert [e.id for e in result.entities] == ["js_state:0:$[0]", "js_state:1:$[0]"]
