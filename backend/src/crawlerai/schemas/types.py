"""The schema document (SPEC-04 §4.2, ARCHITECTURE §5): field types, field specs and the schema itself.

A schema is data, so these models are the boundary every schema crosses, whether it comes from a preset file, the
API or a role S draft: a document that validates here is one the normalizers and the resolver can run.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from crawlerai.db.models import PageKind, SchemaId, SchemaOrigin, SchemaStatus


class FieldType(StrEnum):
    """The §5.1 field types. A type is added here only together with its normalizer module (C8)."""

    TEXT = "text"
    LONG_TEXT = "long_text"
    MONEY = "money"
    ENUM = "enum"
    URL = "url"
    IMAGE_URL = "image_url"
    IDENTIFIER = "identifier"
    DATE = "date"
    DATETIME = "datetime"
    LOCATION = "location"
    RANGE = "range"
    LIST = "list"
    OBJECT = "object"


Scope = Literal["row", "page"]
IdentifierScheme = Literal["gtin", "isbn", "mpn", "sku", "custom"]

# Schema and field names are keys in records, configs and API payloads: lowercase snake case, as the presets use.
Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
# schema.org naming conventions: types are UpperCamelCase, properties lowerCamelCase. A path starts at a type and
# follows properties; `+` joins a second property of the last type into one atomic value (`Offer.price+priceCurrency`).
SchemaOrgPath = Annotated[
    str, StringConstraints(pattern=r"^[A-Z][A-Za-z0-9]*(\.[a-z][A-Za-z0-9]*)+(\+[a-z][A-Za-z0-9]*)?$")
]
# `schema:<Enumeration>` names a schema.org enumeration (a type, so UpperCamelCase); `type:<name>` names a
# language-tagged vocabulary in `crawlerai.normalize.vocab`.
VocabRef = Annotated[str, StringConstraints(pattern=r"^(schema:[A-Z][A-Za-z0-9]*|type:[a-z][a-z0-9_]*)$")]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

MAX_DEPTH = 3
"""Nesting depth (§5.1): a top-level field is depth 1, and each `list.item` or `object.fields` level adds one."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldSpec(_Model):
    """One field of a schema, or the item of a list.

    The parameters a type needs are present exactly for that type: `vocab` for `enum`, `scheme` for `identifier`,
    `item` for `list`, `fields` for `object`.
    """

    type: FieldType
    description: Description | None = None
    required: bool = False
    scope: Scope = "row"
    schema_org: SchemaOrgPath | None = None
    vocab: VocabRef | None = None
    scheme: IdentifierScheme | None = None
    item: "FieldSpec | None" = None
    fields: "dict[Name, FieldSpec] | None" = None

    @model_validator(mode="after")
    def _parameters_match_type(self) -> Self:
        for name, owner in _PARAMETER_OWNER.items():
            present = getattr(self, name) is not None
            if self.type is owner and not present:
                raise ValueError(f"type {owner} needs `{name}`")
            if present and self.type is not owner:
                raise ValueError(f"`{name}` is only for type {owner}, not {self.type}")
        if self.fields is not None and not self.fields:
            raise ValueError("type object needs at least one sub-field")
        return self


_PARAMETER_OWNER = {
    "vocab": FieldType.ENUM,
    "scheme": FieldType.IDENTIFIER,
    "item": FieldType.LIST,
    "fields": FieldType.OBJECT,
}


class SchemaDocument(_Model):
    """A schema as written (a preset file, an API body): everything but the row's identity and lifecycle.

    §4.2 rules checked here: every field and object sub-field is described (role C reads the description; a list
    item is described by its field); nesting is at most `MAX_DEPTH`; a detail page has one entity, so every field is
    `row`; each `required_groups` group names at least one top-level field and only those.
    """

    name: Name
    version: int = Field(ge=1)
    page_kind: PageKind
    required_groups: list[list[Name]] = []
    fields: dict[Name, FieldSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        for name, spec in self.fields.items():
            _check_field(name, spec, depth=1, described=True)
            if self.page_kind == "detail" and spec.scope == "page":
                raise ValueError(f"{name}: a detail page has one entity, so every field is `row` (§5.2)")
        for group in self.required_groups:
            if not group:
                raise ValueError("a required group names at least one field")
            if unknown := sorted(set(group) - self.fields.keys()):
                raise ValueError(f"required group {group} names unknown fields {unknown}")
        return self


def _check_field(path: str, spec: FieldSpec, *, depth: int, described: bool) -> None:
    if depth > MAX_DEPTH:
        raise ValueError(f"{path}: nested deeper than {MAX_DEPTH} levels (§5.1)")
    if described and spec.description is None:
        raise ValueError(f"{path}: every field needs a description (§5.2)")
    if spec.item is not None:
        _check_field(f"{path}.item", spec.item, depth=depth + 1, described=False)
    for name, sub in (spec.fields or {}).items():
        _check_field(f"{path}.{name}", sub, depth=depth + 1, described=True)


class SchemaDef(SchemaDocument):
    """A `schema_def` row (ARCHITECTURE §6): a document plus where it came from and whether it is in use. Rows are
    immutable per (name, version); a change is a new version."""

    id: SchemaId
    origin: SchemaOrigin
    status: SchemaStatus


class SchemaChanges(_Model):
    """What the registry's `new_version` changes; anything left `None` is carried over from the latest version."""

    page_kind: PageKind | None = None
    fields: dict[Name, FieldSpec] | None = None
    required_groups: list[list[Name]] | None = None
