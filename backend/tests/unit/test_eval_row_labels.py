"""Row-mapped field labels (SPEC-13 §4.10, SPEC-03 §4.3): `label_version` 2 labels a `list<object>` field with a key
as rows under `lists`; version 1 labels stay valid and leave it unlabeled."""

import copy
from typing import Any

import pytest

from crawlerai.eval.labels import InvalidLabels, LabelError, parse_labels
from crawlerai.schemas.types import FieldSpec

SPECS: dict[str, FieldSpec] = {
    "title": FieldSpec.model_validate({"type": "text"}),
    "variants": FieldSpec.model_validate(
        {
            "type": "list",
            "schema_org": "ProductGroup.hasVariant|Product.offers",
            "key": ["sku", "url"],
            "item": {
                "type": "object",
                "fields": {
                    "sku": {"type": "identifier", "scheme": "sku", "schema_org": "Product.sku|Offer.sku"},
                    "price": {"type": "money", "schema_org": "Offer.price+priceCurrency"},
                    "url": {"type": "url", "schema_org": "Product.url|Offer.url"},
                },
            },
        }
    ),
}


def sub(value: Any = None) -> dict[str, Any]:
    return {"absent": True} if value is None else {"value": value, "absent": False}


def row(sku: str | None, price: str | None = "10.00", url: str | None = None) -> dict[str, Any]:
    money = {"amount": price, "currency": "EUR"} if price is not None else None
    return {
        "fields": {"sku": sub({"scheme": "sku", "value": sku} if sku else None), "price": sub(money), "url": sub(url)}
    }


VARIANTS: dict[str, Any] = {
    "absent": False,
    "rows": [row("W-11"), row("W-12", "12.00")],
    "distractor_keys": [{"field": "sku", "value": {"scheme": "sku", "value": "X-7"}}],
}

DOC: dict[str, Any] = {
    "label_version": 2,
    "status": "checked",
    "labeler": "labeler-a",
    "checker": "checker-b",
    "fields": {"title": sub("Synthetic widget")},
    "lists": {"variants": VARIANTS},
}


def errors(doc: dict[str, Any], specs: dict[str, FieldSpec] = SPECS) -> set[LabelError]:
    with pytest.raises(InvalidLabels) as e:
        parse_labels(doc, "detail", specs)
    return set(e.value.errors)


def with_list(variants: dict[str, Any], **doc: Any) -> dict[str, Any]:
    return copy.deepcopy(DOC) | {"lists": {"variants": variants}} | doc


def test_a_version_2_document_round_trips() -> None:
    labels = parse_labels(DOC, "detail", SPECS)

    assert labels.model_dump(mode="json", exclude_defaults=True) == DOC | {"lists": {"variants": VARIANTS}}
    assert len(labels.lists["variants"].rows) == 2


def test_version_1_labels_stay_valid_and_leave_the_row_field_unlabeled() -> None:
    doc = {k: v for k, v in DOC.items() if k != "lists"} | {"label_version": 1}

    assert parse_labels(doc, "detail", SPECS).lists == {}


def test_version_1_labels_cannot_label_rows() -> None:
    assert errors(DOC | {"label_version": 1}) == {LabelError("lists", "row-mapped fields need label_version 2")}


def test_a_complete_version_2_document_labels_every_row_field() -> None:
    doc = {k: v for k, v in DOC.items() if k != "lists"}

    assert errors(doc) == {LabelError("lists.variants", "not labeled; mark it absent if the page does not show it")}


def test_a_draft_may_leave_the_row_field_and_sub_fields_unlabeled() -> None:
    partial = {"fields": {"sku": sub({"scheme": "sku", "value": "W-11"})}}
    draft = with_list({"absent": False, "rows": [partial]}, status="draft", checker=None)

    assert parse_labels(draft, "detail", SPECS).status == "draft"
    assert parse_labels({k: v for k, v in draft.items() if k != "lists"}, "detail", SPECS).lists == {}


def test_every_sub_field_of_a_complete_row_is_labeled() -> None:
    partial = {"fields": {"sku": sub({"scheme": "sku", "value": "W-11"})}}

    assert errors(with_list({"absent": False, "rows": [partial]})) == {
        LabelError("lists.variants.rows[0].fields.price", "not labeled; mark it absent if the page does not show it"),
        LabelError("lists.variants.rows[0].fields.url", "not labeled; mark it absent if the page does not show it"),
    }


def test_a_row_names_only_sub_fields() -> None:
    extra = row("W-11")
    extra["fields"]["colour"] = sub("Red")

    assert errors(with_list({"absent": False, "rows": [extra]})) == {
        LabelError("lists.variants.rows[0].fields.colour", "not a sub-field of variants")
    }


def test_a_row_field_is_labeled_in_lists_not_fields() -> None:
    doc = copy.deepcopy(DOC)
    doc["fields"]["variants"] = sub([{"sku": "W-11"}])

    assert errors(doc) == {LabelError("fields.variants", "a row-mapped field belongs in lists")}


def test_only_row_mapped_fields_are_labeled_in_lists() -> None:
    doc = copy.deepcopy(DOC)
    doc["lists"]["title"] = VARIANTS

    assert errors(doc) == {LabelError("lists.title", "not a row-mapped field of the schema")}


@pytest.mark.parametrize(
    ("variants", "reason"),
    [
        ({"absent": True, "rows": [row("W-11")]}, "an absent field has no rows"),
        ({"absent": False, "rows": []}, "a present field has a row"),
    ],
)
def test_absent_and_rows_agree(variants: dict[str, Any], reason: str) -> None:
    assert errors(with_list(variants)) == {LabelError("lists.variants", reason)}


def test_a_distractor_key_names_a_key_sub_field_and_no_row_s_key() -> None:
    price = {"field": "price", "value": {"amount": "10.00", "currency": "EUR"}}
    own = {"field": "sku", "value": {"scheme": "sku", "value": "W-11"}}

    assert errors(with_list(VARIANTS | {"distractor_keys": [price, own]})) == {
        LabelError("lists.variants.distractor_keys[0]", "not a key sub-field of variants"),
        LabelError("lists.variants.distractor_keys[1]", "a distractor key equals a row's key"),
    }


def test_listing_pages_have_no_row_mapped_labels() -> None:
    listing = {"title": FieldSpec.model_validate({"type": "text"})}
    doc = DOC | {"fields": {}, "rows": [{"fields": {"title": sub("Synthetic widget")}}]}

    with pytest.raises(InvalidLabels) as e:
        parse_labels(doc, "listing", listing)

    assert set(e.value.errors) == {LabelError("lists", "only detail pages have row-mapped fields")}
