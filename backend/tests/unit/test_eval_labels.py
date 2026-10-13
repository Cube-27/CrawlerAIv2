"""Eval page labels (SPEC-03 §4.3, §4.11): the jsonb document round-trips, and every invalid document is refused
with the field and the reason, all errors at once."""

import copy
from typing import Any

import pytest
from pydantic import JsonValue, ValidationError

from crawlerai.eval.labels import (
    InvalidLabels,
    LabelError,
    field_specs,
    parse_labels,
)
from crawlerai.schemas.types import FieldSpec, FieldType

DETAIL_SPECS: dict[str, FieldSpec] = {
    "title": FieldSpec(type=FieldType.TEXT),
    "price": FieldSpec(type=FieldType.MONEY),
    "brand": FieldSpec(type=FieldType.TEXT),
    "locations": FieldSpec(type=FieldType.LIST, item=FieldSpec(type=FieldType.LOCATION)),
}

LISTING_SPECS: dict[str, FieldSpec] = {
    "title": FieldSpec(type=FieldType.TEXT),
    "url": FieldSpec(type=FieldType.URL),
    "pagination_url": FieldSpec(type=FieldType.URL, scope="page"),
}

DETAIL: dict[str, Any] = {
    "label_version": 1,
    "status": "checked",
    "labeler": "labeler-a",
    "checker": "checker-b",
    "prefill_source": "llm:model-x",
    "fields": {
        "title": {"value": "Synthetic kettle", "absent": False, "locator": "xpath://h1", "distractors": []},
        "price": {
            "value": {"amount": "19.90", "currency": "EUR"},
            "absent": False,
            "locator": "text:120-128",
            "distractors": [{"amount": "24.90", "currency": "EUR"}],
        },
        "brand": {"value": None, "absent": True, "locator": None, "distractors": []},
        "locations": {
            "value": [{"locality": "Springfield", "region": None, "country": "DE", "remote_flag": False}],
            "absent": False,
            "locator": "jsonld:/jobLocation",
            "distractors": [],
        },
    },
    "rows": [],
    "notes": "price shown twice; second is a bundle",
}

LISTING: dict[str, Any] = {
    "label_version": 1,
    "status": "labeled",
    "labeler": "labeler-a",
    "checker": None,
    "prefill_source": None,
    "fields": {
        "pagination_url": {
            "value": "https://shop.example.test/c?page=2",
            "absent": False,
            "locator": None,
            "distractors": [],
        },
    },
    "rows": [
        {
            "fields": {
                "title": {"value": "Item one", "absent": False, "locator": None, "distractors": []},
                "url": {"value": "https://shop.example.test/p/1", "absent": False, "locator": None, "distractors": []},
            }
        },
    ],
    "notes": "",
}


@pytest.mark.parametrize(
    ("raw", "page_kind", "specs"), [(DETAIL, "detail", DETAIL_SPECS), (LISTING, "listing", LISTING_SPECS)]
)
def test_labels_round_trip_through_json(raw: dict[str, Any], page_kind: Any, specs: dict[str, FieldSpec]) -> None:
    labels = parse_labels(raw, page_kind, specs)

    assert labels.model_dump(mode="json") == raw


def test_a_draft_may_be_partial_and_unattributed() -> None:
    raw: JsonValue = {"label_version": 1, "status": "draft", "prefill_source": "none", "fields": {}}

    labels = parse_labels(raw, "detail", DETAIL_SPECS)

    assert (labels.status, labels.labeler, labels.fields, labels.rows) == ("draft", None, {}, ())


def _errors(
    raw: dict[str, Any], page_kind: Any = "detail", specs: dict[str, FieldSpec] = DETAIL_SPECS
) -> set[LabelError]:
    with pytest.raises(InvalidLabels) as caught:
        parse_labels(raw, page_kind, specs)
    return set(caught.value.errors)


def _detail(**changes: Any) -> dict[str, Any]:
    raw = copy.deepcopy(DETAIL)
    raw.update(changes)
    return raw


def _detail_field(name: str, **changes: Any) -> dict[str, Any]:
    raw = copy.deepcopy(DETAIL)
    raw["fields"][name].update(changes)
    return raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_detail(label_version=2), {LabelError("label_version", "Input should be 1")}),
        (
            _detail(checker="labeler-a"),
            {LabelError("", "a checked page is checked by someone other than its labeler")},
        ),
        (
            _detail(checker=" Labeler-A "),
            {LabelError("", "a checked page is checked by someone other than its labeler")},
        ),
        (
            _detail(checker=None),
            {LabelError("", "a checked page is checked by someone other than its labeler")},
        ),
        (_detail(status="labeled"), {LabelError("", "only a checked page names a checker")}),
        (
            _detail(status="labeled", labeler=None, checker=None),
            {LabelError("", "a labeled or checked page names its labeler")},
        ),
        (_detail(labeler="  "), {LabelError("labeler", "String should have at least 1 character")}),
        (_detail(prefill_source="model-x"), {LabelError("prefill_source", "must be 'none' or 'llm:<model>'")}),
        (_detail(extra="x"), {LabelError("extra", "Extra inputs are not permitted")}),
        (_detail_field("brand", value="Acme"), {LabelError("fields.brand", "an absent field has no value")}),
        (_detail_field("brand", locator="xpath://p"), {LabelError("fields.brand", "an absent field has no locator")}),
        (_detail_field("title", value=None), {LabelError("fields.title", "a present field has a value")}),
        (
            _detail_field("title", locator="css:h1"),
            {LabelError("fields.title.locator", "must be 'xpath:…', 'jsonld:…' or 'text:<start>-<end>'")},
        ),
        (
            _detail_field("title", locator="text:128-120"),
            {LabelError("fields.title.locator", "text offsets need start < end")},
        ),
        (
            _detail_field("price", distractors=[{"amount": "19.90", "currency": "EUR"}]),
            {LabelError("fields.price.distractors[0]", "a distractor equals the value")},
        ),
        (
            _detail_field("title", distractors=[None]),
            {LabelError("fields.title.distractors[0]", "a distractor has a value")},
        ),
    ],
)
def test_invalid_labels_are_refused_with_field_and_reason(raw: dict[str, Any], expected: set[LabelError]) -> None:
    assert _errors(raw) == expected


def test_every_error_is_reported_at_once() -> None:
    raw = copy.deepcopy(DETAIL)
    raw["fields"]["colour"] = raw["fields"].pop("brand")
    raw["rows"] = [{"fields": {}}]

    assert _errors(raw) == {
        LabelError("fields.colour", "not a field of the schema"),
        LabelError("fields.brand", "not labeled; mark it absent if the page does not show it"),
        LabelError("rows", "only listing pages have rows"),
    }


def test_listing_fields_are_placed_by_scope() -> None:
    raw = copy.deepcopy(LISTING)
    raw["fields"]["title"] = raw["rows"][0]["fields"].pop("title")
    raw["rows"][0]["fields"]["pagination_url"] = raw["fields"].pop("pagination_url")

    assert _errors(raw, "listing", LISTING_SPECS) == {
        LabelError("fields.title", "a row field belongs in rows"),
        LabelError("rows[0].fields.pagination_url", "a page field belongs in fields"),
        LabelError("fields.pagination_url", "not labeled; mark it absent if the page does not show it"),
        LabelError("rows[0].fields.title", "not labeled; mark it absent if the page does not show it"),
    }


def test_detail_pages_ignore_scope() -> None:
    raw = copy.deepcopy(DETAIL)
    specs = {**DETAIL_SPECS, "brand": FieldSpec(type=FieldType.TEXT, scope="page")}

    assert parse_labels(raw, "detail", specs).fields["brand"].absent is True


def test_field_specs_read_a_schema_documents_fields() -> None:
    fields: dict[str, JsonValue] = {
        "next_page_url": {"type": "url", "scope": "page", "description": "Next page"},
        "salary": {"type": "object", "fields": {"base": {"type": "money", "required": True}}, "description": "Pay"},
    }

    assert field_specs(fields) == {
        "next_page_url": FieldSpec(type=FieldType.URL, scope="page", description="Next page"),
        "salary": FieldSpec(
            type=FieldType.OBJECT,
            description="Pay",
            fields={"base": FieldSpec(type=FieldType.MONEY, required=True)},
        ),
    }


def test_field_specs_reject_a_field_that_is_not_a_field_spec() -> None:
    fields: dict[str, JsonValue] = {"sku": {"type": "identifier"}}

    with pytest.raises(ValidationError):
        field_specs(fields)
