"""A schema document's `schema_org` paths and `schema:` enum references are checked against the pinned schema.org
vocabulary (SPEC-04 §4.2): a stand-in vocabulary pins what is checked; the presets are checked against the real file
when it is fetched."""

from pathlib import Path

import pytest
from pydantic import JsonValue

from crawlerai.collect import schema_org_map
from crawlerai.collect.schema_org_map import Vocabulary, reference_errors
from crawlerai.core.engine_version import engine_data_dir
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldSpec, FieldType
from crawlerai.services import schemas as schemas_service
from crawlerai.services.schemas import InvalidSchema, NewSchema


def _cls(name: str, parent: str | None = None) -> dict[str, JsonValue]:
    node: dict[str, JsonValue] = {"@id": f"schema:{name}", "@type": "rdfs:Class"}
    if parent is not None:
        node["rdfs:subClassOf"] = {"@id": f"schema:{parent}"}
    return node


def _prop(name: str) -> dict[str, JsonValue]:
    return {"@id": f"schema:{name}", "@type": "rdf:Property"}


VOCABULARY = Vocabulary.parse(
    {
        "@graph": [
            _cls("Thing"),
            _cls("Product", "Thing"),
            _cls("Offer", "Thing"),
            _cls("Enumeration", "Thing"),
            _cls("ItemAvailability", "Enumeration"),
            *map(_prop, ("name", "description", "offers", "price", "priceCurrency")),
        ]
    }
)


def _text(path: str | None) -> FieldSpec:
    return FieldSpec(type=FieldType.TEXT, schema_org=path)


def _errors(**fields: FieldSpec) -> list[tuple[str, str]]:
    return reference_errors(fields, VOCABULARY)


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("Widget.description", "Widget is not a schema.org type"),
        ("Product.colour", "colour is not a schema.org property"),
        ("Product.offers.cost", "cost is not a schema.org property"),
        ("Product.offers.price+currency", "currency is not a schema.org property"),
        ("Product.name|Gadget.description", "Gadget is not a schema.org type"),
    ],
)
def test_a_path_naming_a_term_the_vocabulary_lacks_is_refused_with_its_reason(path: str, reason: str) -> None:
    assert _errors(title=_text(path)) == [("fields.title.schema_org", reason)]


def test_a_document_is_refused_by_the_service_with_every_error_at_its_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schema_org_map, "default_vocabulary", lambda: VOCABULARY)
    schema = NewSchema.model_validate(
        {
            "name": "synthetic",
            "page_kind": "detail",
            "fields": {
                "title": {"type": "text", "description": "Title", "schema_org": "Product.name"},
                "colour": {"type": "text", "description": "Colour", "schema_org": "Product.colour"},
            },
        }
    )

    with pytest.raises(InvalidSchema) as refused:
        schemas_service._document(schema)

    assert refused.value.errors == [("fields.colour.schema_org", "colour is not a schema.org property")]


def test_the_presets_name_only_terms_of_the_pinned_vocabulary() -> None:
    data = engine_data_dir()
    path = None if data is None else Path(data) / "schemaorg" / "schemaorg-all-https.jsonld"
    if path is None or not path.is_file():
        pytest.skip("the schema.org file is not fetched: run `crawlerai data fetch`")
    pinned = Vocabulary.read(path)

    assert {p.name: reference_errors(p.fields, pinned) for p in load_presets()} == {p.name: [] for p in load_presets()}
