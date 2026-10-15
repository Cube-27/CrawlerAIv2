"""The schema document rules (SPEC-04 §4.2) and the preset files (§5.3)."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldType, SchemaDocument


def _document(fields: dict[str, Any], **top: Any) -> dict[str, Any]:
    return {"name": "s", "version": 1, "page_kind": "detail", "fields": fields, **top}


def _text(**spec: Any) -> dict[str, Any]:
    return {"type": "text", "description": "d", **spec}


def _rejection(document: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as error:
        SchemaDocument.model_validate(document)
    return str(error.value)


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"type": "enum", "description": "d"}, "needs `vocab`"),
        ({"type": "identifier", "description": "d"}, "needs `scheme`"),
        ({"type": "list", "description": "d"}, "needs `item`"),
        ({"type": "object", "description": "d"}, "needs `fields`"),
        ({"type": "object", "description": "d", "fields": {}}, "at least one sub-field"),
        (_text(vocab="schema:ItemAvailability"), "`vocab` is only for type enum"),
        (_text(scheme="sku"), "`scheme` is only for type identifier"),
        (_text(item={"type": "text"}), "`item` is only for type list"),
        ({"type": "identifier", "description": "d", "scheme": "ean"}, "scheme"),
        ({"type": "quantity", "description": "d"}, "type"),
    ],
)
def test_type_parameters_are_present_exactly_for_their_type(spec: dict[str, Any], message: str) -> None:
    assert message in _rejection(_document({"f": spec}))


def test_every_field_and_object_sub_field_needs_a_description() -> None:
    assert "title: every field needs a description" in _rejection(_document({"title": {"type": "text"}}))
    nested = {"type": "object", "description": "d", "fields": {"locality": {"type": "text"}}}
    assert "place.locality: every field needs a description" in _rejection(_document({"place": nested}))


def test_a_list_item_is_described_by_its_field() -> None:
    document = _document({"tags": {"type": "list", "description": "d", "item": {"type": "text"}}})

    item = SchemaDocument.model_validate(document).fields["tags"].item
    assert item is not None
    assert (item.type, item.description) == (FieldType.TEXT, None)


def test_a_blank_description_is_rejected() -> None:
    assert "description" in _rejection(_document({"title": _text(description="   ")}))


def test_nesting_is_at_most_three_levels() -> None:
    three = {"type": "list", "description": "d", "item": {"type": "object", "fields": {"name": _text()}}}
    four = {
        "type": "list",
        "description": "d",
        "item": {"type": "object", "fields": {"names": {"type": "list", "description": "d", "item": {"type": "text"}}}},
    }

    assert SchemaDocument.model_validate(_document({"rows": three})).fields["rows"].type is FieldType.LIST
    assert "rows.item.names.item: nested deeper than 3 levels" in _rejection(_document({"rows": four}))


def test_a_detail_schema_has_row_fields_only() -> None:
    assert "every field is `row`" in _rejection(_document({"next": _text(scope="page")}))
    listing = _document({"next": _text(scope="page")}, page_kind="listing")
    assert SchemaDocument.model_validate(listing).fields["next"].scope == "page"


@pytest.mark.parametrize(
    ("groups", "message"),
    [([[]], "at least one field"), ([["sku", "upc"]], "unknown fields ['upc']")],
)
def test_required_groups_name_existing_fields(groups: list[list[str]], message: str) -> None:
    assert message in _rejection(_document({"sku": _text()}, required_groups=groups))


@pytest.mark.parametrize(
    "path",
    ["Product", "product.sku", "Product.sku+price+priceCurrency"],
)
def test_malformed_schema_org_paths_are_rejected(path: str) -> None:
    assert "schema_org" in _rejection(_document({"f": _text(schema_org=path)}))


@pytest.mark.parametrize("vocab", ["ItemAvailability", "x:y"])
def test_malformed_vocab_references_are_rejected(vocab: str) -> None:
    assert "vocab" in _rejection(_document({"f": {"type": "enum", "description": "d", "vocab": vocab}}))


@pytest.mark.parametrize("name", ["Title", "1st", "a" * 65])
def test_field_names_are_lowercase_snake_case(name: str) -> None:
    assert "fields" in _rejection(_document({name: _text()}))


def test_unknown_keys_are_rejected() -> None:
    assert "optional" in _rejection(_document({"f": _text(optional=True)}))


def test_every_preset_field_maps_to_schema_org_except_page_navigation() -> None:
    unmapped = {
        (preset.name, name) for preset in load_presets() for name, spec in preset.fields.items() if not spec.schema_org
    }

    assert unmapped == {("commerce_listing", "next_page_url"), ("job_listing", "next_page_url")}
