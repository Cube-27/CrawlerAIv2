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
    COUNT = "count"
    NUMBER = "number"
    LIST = "list"
    OBJECT = "object"


Scope = Literal["row", "page"]
IdentifierScheme = Literal["gtin", "isbn", "mpn", "sku", "custom"]

# Schema and field names are keys in records, configs and API payloads: lowercase snake case, as the presets use.
NAME_PATTERN = r"[a-z][a-z0-9_]{0,63}"
Name = Annotated[str, StringConstraints(pattern=rf"^{NAME_PATTERN}$")]
# schema.org naming conventions: types are UpperCamelCase, properties lowerCamelCase. A path starts at a type and
# follows properties; `+` joins a second property of the last type into one atomic value (`Offer.price+priceCurrency`).
# `|` separates up to four alternatives, whose candidates are pooled (SPEC-13 §4.1): `Product.sku|Offer.sku`.
_ALTERNATIVE = r"[A-Z][A-Za-z0-9]*(\.[a-z][A-Za-z0-9]*)+(\+[a-z][A-Za-z0-9]*)?"
MAX_ALTERNATIVES = 4
SchemaOrgPath = Annotated[
    str, StringConstraints(pattern=rf"^{_ALTERNATIVE}(\|{_ALTERNATIVE}){{0,{MAX_ALTERNATIVES - 1}}}$")
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
    `item` for `list`, `fields` for `object`. A `list` of `object` with a `schema_org` path is row-mapped (SPEC-13
    §4.2): the path names the row entities, and `key` names the sub-fields that identify a row.
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
    key: list[Name] | None = None

    @property
    def row_mapped(self) -> bool:
        """A `list` of `object` whose rows a `schema_org` path finds (SPEC-13 §4.2)."""
        return self.schema_org is not None and self.item is not None and self.item.type is FieldType.OBJECT

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
        if self.schema_org is not None and self.item is not None and self.item.type is FieldType.OBJECT:
            _check_row_mapping(self.schema_org, self.item, self.key or [])
        elif self.key is not None:
            raise ValueError("`key` is only for a list of objects with a `schema_org` path (a row-mapped field)")
        return self


# A row's key identifies it: an identifier identifies a thing by definition (GS1, ISO 2108, a seller's sku), and a URL
# identifies a resource (RFC 3986 §1.1).
_KEY_TYPES = (FieldType.IDENTIFIER, FieldType.URL)
MAX_KEY = 3


def _check_row_mapping(row_path: str, item: FieldSpec, key: list[str]) -> None:
    """SPEC-13 §4.2: the row path names nodes, so it joins no value (`+`); the item's sub-fields are leaf values, each
    with its own path; `key` names one to three distinct identifier or url sub-fields."""
    fields = item.fields or {}
    if "+" in row_path:
        raise ValueError("a row path names the row entities, not a value: no `+`")
    if item.schema_org is not None:
        raise ValueError("the item of a row-mapped field has no `schema_org`: the list's path names its rows")
    if nested := sorted(n for n, s in fields.items() if s.type in (FieldType.LIST, FieldType.OBJECT)):
        raise ValueError(f"the sub-fields of a row-mapped field are leaf values, not lists or objects: {nested}")
    if not 1 <= len(key) <= MAX_KEY or len(set(key)) != len(key):
        raise ValueError(f"a row-mapped field's `key` names 1 to {MAX_KEY} distinct sub-fields")
    for name in key:
        sub = fields.get(name)
        if sub is None or sub.type not in _KEY_TYPES:
            raise ValueError(f"`key` names {name!r}, which is not an identifier or url sub-field")


_PARAMETER_OWNER = {
    "vocab": FieldType.ENUM,
    "scheme": FieldType.IDENTIFIER,
    "item": FieldType.LIST,
    "fields": FieldType.OBJECT,
}


class SchemaContent(_Model):
    """A schema document as a caller writes it, without its name."""

    page_kind: PageKind
    required_groups: list[list[Name]] = []
    fields: dict[Name, FieldSpec] = Field(min_length=1)


class SchemaDocument(SchemaContent):
    """A schema as written (a preset file, an API body): everything but the row's identity and lifecycle.

    §4.2 rules checked here: every field and object sub-field is described (role C reads the description; a list
    item is described by its field); nesting is at most `MAX_DEPTH`; a detail page has one entity, so every field is
    `row`; each `required_groups` group names at least one top-level field and only those.
    """

    name: Name

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
    """A `schema_def` row (ARCHITECTURE §6): a document plus where it came from and whether it is in use. One row per
    name, edited in place."""

    id: SchemaId
    origin: SchemaOrigin
    status: SchemaStatus


class SchemaChanges(_Model):
    """What the registry's `update_schema` changes; anything left `None` is kept as stored."""

    page_kind: PageKind | None = None
    fields: dict[Name, FieldSpec] | None = None
    required_groups: list[list[Name]] | None = None
