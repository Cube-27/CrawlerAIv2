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
    return {"fields": {"sku": sub(sku if sku else None), "price": sub(money), "url": sub(url)}}


VARIANTS: dict[str, Any] = {
    "absent": False,
    "rows": [row("W-11"), row("W-12", "12.00")],
    "distractor_keys": [{"field": "sku", "value": "X-7"}],
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


def test_version_1_labels_stay_valid_and_leave_the_row_field_unlabeled() -> None:
    doc = {k: v for k, v in DOC.items() if k != "lists"} | {"label_version": 1}

    labels = parse_labels(doc, "detail", SPECS)

    assert (list(labels.fields), labels.lists) == (["title"], {})


@pytest.mark.parametrize(
    ("variants", "reason"),
    [
        ({"absent": True, "rows": [row("W-11")]}, "an absent field has no rows"),
        ({"absent": False, "rows": []}, "a present field has a row"),
    ],
)
def test_absent_and_rows_agree(variants: dict[str, Any], reason: str) -> None:
    assert errors(with_list(variants)) == {LabelError("lists.variants", reason)}


def test_listing_pages_have_no_row_mapped_labels() -> None:
    listing = {"title": FieldSpec.model_validate({"type": "text"})}
    doc = DOC | {"fields": {}, "rows": [{"fields": {"title": sub("Synthetic widget")}}]}

    with pytest.raises(InvalidLabels) as e:
        parse_labels(doc, "listing", listing)

    assert set(e.value.errors) == {LabelError("lists", "only detail pages have row-mapped fields")}
