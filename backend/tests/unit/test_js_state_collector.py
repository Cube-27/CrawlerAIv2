"""The embedded JSON state collector (SPEC-05 §4.5, ARCHITECTURE §8.1): JSON in inline scripts, admitted only by
equality to another source kind's candidate (not independent, owned by that candidate's entity) or, for a field with no
such candidate, by visibility in the page text (independent, owned by the page)."""

import json
from datetime import UTC, datetime
from html import escape

import pytest
from pydantic import JsonValue

from crawlerai.collect.admission import Admitted
from crawlerai.collect.base import Candidate
from crawlerai.collect.js_state import JsStateCollector
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
    version=1,
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


def test_a_visible_value_of_a_field_without_candidates_is_owned_by_the_page_and_independent() -> None:
    result = _collect(_state({"items": [{"label": "Synthetic Widget"}]}, body="Synthetic Widget"))

    assert result.candidates == (
        _candidate(
            "title",
            "Synthetic Widget",
            Ok("Synthetic Widget"),
            locator=f"js_state:{SCRIPT}:$['items'][0]['label']",
            independent=True,
        ),
    )


def test_a_value_neither_equal_nor_visible_is_not_admitted() -> None:
    result = _collect(_state({"a": "Hidden Name", "b": "€5.00"}, body="Other text"))

    assert result == Admitted(candidates=())


def test_a_field_with_candidates_admits_by_equality_only() -> None:
    # Visible and a valid price, but the field has a JSON-LD price it does not equal.
    assert _prices(_state({"was": "€24.99"}, body="€24.99"), JSONLD_PRICE) == []


def test_a_value_both_equal_and_visible_is_not_independent() -> None:
    assert _prices(_state({"cost": "€19.99"}, body="€19.99"), JSONLD_PRICE) == [("jsonld:0:$['offers']", False)]


def test_a_candidate_that_did_not_normalize_still_makes_the_field_admit_by_equality_only() -> None:
    invalid = JSONLD_PRICE.model_copy(update={"normalized": Invalid("no_currency")})

    assert _prices(_state({"cost": "€19.99"}, body="€19.99"), invalid) == []


def test_candidates_of_the_same_source_kind_are_not_anchors() -> None:
    own = JSONLD_PRICE.model_copy(update={"source_kind": "js_state", "locator": "js_state:/html[1]/script[1]:$"})

    assert _prices(_state({"cost": "€19.99"}, body="€19.99"), own) == [("page", True)]


def test_a_value_equal_to_candidates_of_two_entities_is_admitted_once_for_each() -> None:
    other_offer = JSONLD_PRICE.model_copy(update={"entity_id": "jsonld:1:$['offers']", "locator": "jsonld:1:$"})
    same_offer_og = JSONLD_PRICE.model_copy(update={"source_kind": "og", "locator": "meta:product:price:amount"})

    result = _collect(_state({"cost": "€19.99"}), JSONLD_PRICE, other_offer, same_offer_og)

    assert [c.entity_id for c in result.candidates] == ["jsonld:0:$['offers']", "jsonld:1:$['offers']"]


def test_booleans_null_and_unnormalizable_values_are_not_candidates() -> None:
    result = _collect(_state({"a": True, "b": None, "c": 7, "d": ""}, body="true null 7"))

    assert result.candidates == ()


@pytest.mark.parametrize(
    "script",
    [
        'window.__S = {"name": "Synthetic Widget"};',
        'var s={"name": "Synthetic Widget"}',
        'let s = {"name": "Synthetic Widget"}; init(s);',
        'if (x) { go(); }\nconst s =\n {"name": "Synthetic Widget"}\n;',
    ],
)
def test_the_json_after_the_first_assignment_is_the_state(script: str) -> None:
    result = _collect(_page(script, body="Synthetic Widget"))

    assert [(c.field, c.locator) for c in result.candidates] == [("title", f"js_state:{SCRIPT}:$['name']")]


@pytest.mark.parametrize(
    "script",
    [
        'if (a == {"name": "Synthetic Widget"}) {}',
        'var f = x => ({"name": "Synthetic Widget"});',
        'var n = "Synthetic Widget";',  # a scalar initializer is a script variable, not state
        'go({"name": "Synthetic Widget"});',
        'window.s = JSON.parse(\'{"name": "Synthetic Widget"}\');',
    ],
)
def test_script_code_that_is_not_an_assignment_of_json_is_not_state(script: str) -> None:
    result = _collect(_page(script, body="Synthetic Widget"))

    assert result == Admitted(candidates=())


def test_only_the_first_assignment_of_a_script_is_read() -> None:
    script = 'window.a = {"x": 1}; window.b = {"name": "Synthetic Widget"};'

    assert _collect(_page(script, body="Synthetic Widget")).candidates == ()


def test_an_application_json_script_is_a_document() -> None:
    page = _page('{"name": "Synthetic Widget"}', body="Synthetic Widget", script_type="application/json")

    assert [c.locator for c in _collect(page).candidates] == [f"js_state:{SCRIPT}:$['name']"]


def test_an_invalid_application_json_script_is_skipped_with_a_diagnostic() -> None:
    page = _page('{"name": NaN}', body="Synthetic Widget", script_type="application/json")

    result = _collect(page)

    assert result.candidates == ()
    assert result.diagnostics == (f"js_state:{SCRIPT}: invalid JSON (NaN is not JSON)",)


def test_json_ld_blocks_are_not_state() -> None:
    page = _page('{"name": "Synthetic Widget"}', body="Synthetic Widget", script_type="application/ld+json")

    assert _collect(page) == Admitted(candidates=())


def test_each_script_is_addressed_by_its_own_xpath() -> None:
    page = ParsedPage(
        "<html><head><script>var a = 1;</script></head><body><p>Synthetic Widget</p>"
        '<script>window.s = {"name": "Synthetic Widget"}</script></body></html>'
    )

    assert [c.locator for c in _collect(page).candidates] == ["js_state:/html[1]/body[1]/script[1]:$['name']"]
