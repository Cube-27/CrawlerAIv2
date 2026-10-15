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


def test_defaults_are_optional_row_fields() -> None:
    field = SchemaDocument.model_validate(_document({"title": _text()})).fields["title"]

    assert (field.required, field.scope) == (False, "row")


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

    assert SchemaDocument.model_validate(document).fields["tags"].item is not None


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
    ["Product", "product.sku", "Product.Sku", "Product.sku+", "Product.sku+price+priceCurrency", "Product..sku"],
)
def test_malformed_schema_org_paths_are_rejected(path: str) -> None:
    assert "schema_org" in _rejection(_document({"f": _text(schema_org=path)}))


@pytest.mark.parametrize("vocab", ["ItemAvailability", "schema:itemAvailability", "type:Availability", "x:y"])
def test_malformed_vocab_references_are_rejected(vocab: str) -> None:
    assert "vocab" in _rejection(_document({"f": {"type": "enum", "description": "d", "vocab": vocab}}))


@pytest.mark.parametrize("name", ["Title", "1st", "title-text", "a" * 65, ""])
def test_field_names_are_lowercase_snake_case(name: str) -> None:
    assert "fields" in _rejection(_document({name: _text()}))


def test_unknown_keys_are_rejected() -> None:
    assert "optional" in _rejection(_document({"f": _text(optional=True)}))


def _core(document: SchemaDocument) -> dict[str, str]:
    return {name: spec.type.value for name, spec in document.fields.items() if spec.required}


def test_the_presets_are_exactly_the_section_5_3_documents() -> None:
    presets = {preset.name: preset for preset in load_presets()}

    assert sorted(presets) == ["commerce_detail", "commerce_listing", "job_detail", "job_listing"]
    # commerce_detail 2: `brand` optional (owner, Appendix A #35); 3: the optional row-mapped `variants` (SPEC-13 §4.7).
    assert {name: preset.version for name, preset in presets.items()} == {
        "commerce_detail": 3,
        "commerce_listing": 1,
        "job_detail": 1,
        "job_listing": 1,
    }
    assert _core(presets["commerce_detail"]) == {
        "title": "text",
        "price": "money",
        "availability": "enum",
        "url": "url",
        "image_url": "image_url",
    }
    assert presets["commerce_detail"].fields["brand"].type.value == "text"
    assert presets["commerce_detail"].required_groups == [["sku", "gtin"]]
    assert presets["commerce_detail"].fields["availability"].vocab == "schema:ItemAvailability"
    variants = presets["commerce_detail"].fields["variants"]
    assert (variants.row_mapped, variants.required, variants.key) == (True, False, ["gtin", "sku", "url"])
    assert {n: s.scheme for n, s in presets["commerce_detail"].fields.items() if s.scheme} == {
        "sku": "sku",
        "gtin": "gtin",
    }
    assert _core(presets["job_detail"]) == {
        "title": "text",
        "company": "text",
        "locations": "list",
        "description": "long_text",
        "apply_url": "url",
        "date_posted": "date",
    }
    assert presets["job_detail"].fields["locations"].item.type is FieldType.LOCATION  # type: ignore[union-attr]
    assert presets["job_detail"].fields["apply_url"].schema_org == "JobPosting.url"  # D-0015
    for listing, optional in (("commerce_listing", "price"), ("job_listing", "location")):
        fields = presets[listing].fields
        assert _core(presets[listing]) == {"title": "text", "url": "url"}
        assert sorted(fields) == sorted(["title", "url", optional, "next_page_url"])
        assert {n for n, s in fields.items() if s.scope == "page"} == {"next_page_url"}


def test_every_preset_field_maps_to_schema_org_except_page_navigation() -> None:
    unmapped = {
        (preset.name, name) for preset in load_presets() for name, spec in preset.fields.items() if not spec.schema_org
    }

    assert unmapped == {("commerce_listing", "next_page_url"), ("job_listing", "next_page_url")}
