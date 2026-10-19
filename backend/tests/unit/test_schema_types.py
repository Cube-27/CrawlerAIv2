"""The schema document rules (schemas spec) and the preset files (§5.3)."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.schemas.types import SchemaDocument


def _document(fields: dict[str, Any], **top: Any) -> dict[str, Any]:
    return {"name": "s", "page_kind": "detail", "fields": fields, **top}


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


def test_a_row_path_takes_no_predicates() -> None:
    # Schemas spec, "Row-mapped lists and key": row discovery follows the row path's steps alone.
    sku = {"type": "identifier", "scheme": "sku", "description": "d", "schema_org": "Product.sku"}
    rows = {
        "type": "list",
        "description": "d",
        "schema_org": "ProductGroup.hasVariant{sku}",
        "item": {"type": "object", "fields": {"sku": sku}},
        "key": ["sku"],
    }

    assert "no `{…}` predicates" in _rejection(_document({"variants": rows}))
