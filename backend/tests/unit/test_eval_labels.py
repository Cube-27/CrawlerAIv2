"""Eval page labels (evaluation spec): the jsonb document round-trips, and every invalid document is refused
with the field and the reason, all errors at once."""

import copy
from typing import Any

import pytest

from crawlerai.eval.labels import (
    InvalidLabels,
    LabelError,
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
            "value": [
                {
                    "text": "Springfield, DE",
                    "locality": "Springfield",
                    "region": None,
                    "country": "DE",
                    "remote_flag": False,
                }
            ],
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
            },
            "stale": False,
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
        (_detail(label_version=3), {LabelError("label_version", "Input should be 1 or 2")}),
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
