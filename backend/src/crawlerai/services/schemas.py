"""The schemas service (SPEC-07 §4.6, §4.7): what `/v1/schemas` and the MCP schema tools do, over a connection.

Callers write `user` schemas, whose schema.org paths and enumerations the pinned vocabulary must define. A schema is
one row per name, edited in place (ARCHITECTURE §5.2); an edit sends its learned configs back to learning
(`progressive.relearn_schema`), and a delete retires it. Presets change only through their files and
`crawlerai schemas sync` (§5.3, D-0242), so callers can neither take a preset's name nor edit or
retire a preset.
"""

from collections.abc import Mapping, Sequence
from functools import cache

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.labels import labelled
from crawlerai.collect.schema_org_map import pinned_reference_errors
from crawlerai.config_ir.progressive import relearn_schema
from crawlerai.core.errors import Refusal
from crawlerai.core.validation import field_error
from crawlerai.db.models import SchemaId, SchemaStatus
from crawlerai.schemas import registry
from crawlerai.schemas.registry import SchemaExists, SchemaNotFound
from crawlerai.schemas.types import (
    FieldLabels,
    FieldSpec,
    Name,
    SchemaChanges,
    SchemaContent,
    SchemaDef,
    SchemaDocument,
)


class NewSchema(SchemaContent):
    name: Name


class SchemaConflict(Refusal):
    """The request is valid but the stored schemas don't allow it: a taken or preset name, a change to a preset or a
    retired schema."""


class InvalidSchema(Refusal):
    """The document breaks a schema rule (SPEC-04 §4.2); `errors` are (field path, reason) pairs, `""` for the whole
    document."""

    def __init__(self, errors: Sequence[tuple[str, str]]) -> None:
        super().__init__("the schema document is invalid")
        self.errors = list(errors)

    @classmethod
    def of(cls, error: ValidationError) -> "InvalidSchema":
        return cls([field_error(e) for e in error.errors()])


def _check_references(fields: Mapping[str, FieldSpec]) -> None:
    """Refuse `fields` naming a schema.org type, property or enumeration the pinned vocabulary lacks (schemas spec,
    "schema.org paths"; `pinned_reference_errors`)."""
    if errors := pinned_reference_errors(fields):
        raise InvalidSchema(errors)


async def create(conn: AsyncConnection, schema: NewSchema) -> SchemaDef:
    try:
        return await registry.create(conn, _document(schema), "user")
    except SchemaExists as e:
        raise SchemaConflict(f"schema {schema.name} exists; edit it instead") from e


def _document(schema: NewSchema) -> SchemaDocument:
    """`schema` as a new user schema's document: a preset name or a broken document is refused."""
    if schema.name in _preset_names():
        raise SchemaConflict(f"{schema.name} is a preset name; presets change only through their files")
    try:
        document = SchemaDocument.model_validate(schema.model_dump())
    except ValidationError as e:
        raise InvalidSchema.of(e) from e
    _check_references(document.fields)
    return document


async def inline(conn: AsyncConnection, schema: NewSchema) -> SchemaDef:
    """The stored schema an inline schema (a `scrape` request's) stands for: the schema of that name when it has the
    same document and is active, else a new `user` schema. An inline schema never edits a stored one (§5.2): a name
    whose schema differs or is retired is a `SchemaConflict`."""
    stored = await _stored_or_created(conn, schema)
    if (stored.page_kind, stored.required_groups, stored.fields) != (
        schema.page_kind,
        schema.required_groups,
        schema.fields,
    ):
        raise SchemaConflict(
            f"schema {schema.name} differs from the inline schema; edit it, or name the inline schema differently"
        )
    if stored.status == "retired":
        raise SchemaConflict(f"schema {schema.name} is retired")
    return stored


async def _stored_or_created(conn: AsyncConnection, schema: NewSchema) -> SchemaDef:
    if (stored := await registry.find(conn, schema.name)) is not None:
        return stored
    try:
        return await registry.create(conn, _document(schema), "user")
    except SchemaExists:
        # Another request stored the name first: its insert committed before ours hit the unique name, and READ
        # COMMITTED lets this statement see it. The same document reuses it, as it would have.
        return await registry.get(conn, schema.name)


async def get(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    return await registry.get_by_id(conn, schema_id)


async def list_all(
    conn: AsyncConnection, *, name: str | None = None, status: SchemaStatus | None = None
) -> list[SchemaDef]:
    return await registry.list_schemas(conn, name=name, status=status)


async def update(conn: AsyncConnection, schema_id: SchemaId, content: SchemaContent) -> SchemaDef:
    """Replace the schema's document with `content`, in place, and send what was learned for the old document back to
    learning. A retired schema or a preset is refused."""
    current = await _changeable(conn, schema_id)
    if current.status == "retired":
        raise SchemaConflict(f"schema {current.name} is retired")
    _check_references(content.fields)
    try:
        edited = await registry.update_schema(conn, current, SchemaChanges.model_validate(content.model_dump()))
    except ValidationError as e:
        raise InvalidSchema.of(e) from e
    if edited != current:
        await relearn_schema(conn, schema_id)
    return edited


async def set_labels(conn: AsyncConnection, schema_id: SchemaId, labels: FieldLabels) -> SchemaDef:
    """Replace the schema's label synonyms (`SchemaDef.labels`), a preset's too: they are no part of its document, so
    nothing is learned again. A retired schema is refused, and so is a field it lacks or no label can name."""
    current = await registry.get_by_id(conn, schema_id)
    if current.status == "retired":
        raise SchemaConflict(f"schema {current.name} is retired")
    if unknown := sorted(n for n in labels if n not in current.fields or not labelled(current.fields[n])):
        raise InvalidSchema([(f"labels.{name}", "no labelled field of the schema has this name") for name in unknown])
    stored = await registry.store_labels(conn, schema_id, labels)
    if stored is None:
        raise SchemaNotFound(f"no schema with id {schema_id}")
    return stored


async def sync_presets(conn: AsyncConnection, presets: Sequence[SchemaDocument] | None = None) -> list[SchemaDef]:
    """Upsert the preset files, or `presets` (`crawlerai schemas sync`, §5.3), and send each changed preset's sites
    back to learning; the presets inserted or changed. Raises `registry.PresetConflict`."""
    written = await registry.sync_presets(conn, presets)
    for schema in written:
        await relearn_schema(conn, schema.id)
    return written


async def retire(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    await _changeable(conn, schema_id)
    return await registry.retire(conn, schema_id)


async def _changeable(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    current = await registry.get_by_id(conn, schema_id)
    if current.origin == "preset":
        raise SchemaConflict(f"{current.name} is a preset; presets change only through their files")
    return current


@cache
def _preset_names() -> Sequence[str]:
    # The preset files ship with the package, so they don't change while it runs.
    return tuple(preset.name for preset in registry.load_presets())
