"""The schemas service (SPEC-07 §4.6, §4.7): what `/v1/schemas` and the MCP schema tools do, over a connection.

Callers write `user` schemas. A schema is immutable per version (ARCHITECTURE §5.2), so an edit adds a version on
top of the latest one and a delete retires one version; rows stay, since records and configs reference them.
Presets change only through their files and `crawlerai schemas sync` (§5.3, D-0242), so callers can neither take a
preset's name nor edit or retire a preset.
"""

from collections.abc import Sequence
from functools import cache

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.errors import Refusal
from crawlerai.core.validation import field_error
from crawlerai.db.models import SchemaId, SchemaStatus
from crawlerai.schemas import registry
from crawlerai.schemas.registry import NotLatest, SchemaExists
from crawlerai.schemas.types import Name, SchemaChanges, SchemaContent, SchemaDef, SchemaDocument


class NewSchema(SchemaContent):
    name: Name


class SchemaConflict(Refusal):
    """The request is valid but the stored schemas don't allow it: a taken or preset name, an edit to a version that
    is not the latest or is retired, a change to a preset."""


class InvalidSchema(Refusal):
    """The document breaks a schema rule (SPEC-04 §4.2); `errors` are (field path, reason) pairs, `""` for the whole
    document."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__("the schema document is invalid")
        self.errors = [field_error(e) for e in error.errors()]


async def create(conn: AsyncConnection, schema: NewSchema) -> SchemaDef:
    if schema.name in _preset_names():
        raise SchemaConflict(f"{schema.name} is a preset name; presets change only through their files")
    try:
        document = SchemaDocument.model_validate({**schema.model_dump(), "version": 1})
    except ValidationError as e:
        raise InvalidSchema(e) from e
    try:
        return await registry.create(conn, document, "user")
    except SchemaExists as e:
        raise SchemaConflict(f"schema {schema.name} exists; edit its latest version instead") from e


async def inline(conn: AsyncConnection, schema: NewSchema) -> SchemaDef:
    """The stored schema an inline schema (a `scrape` request's) stands for: its name's latest version when that
    has the same document and is active, else a new `user` schema at version 1. An inline schema never edits a
    stored one (§5.2): a name whose latest version differs or is retired is a `SchemaConflict`."""
    versions = await registry.list_schemas(conn, name=schema.name)
    if not versions:
        return await create(conn, schema)
    latest = versions[-1]
    if (latest.page_kind, latest.required_groups, latest.fields) != (
        schema.page_kind,
        schema.required_groups,
        schema.fields,
    ):
        raise SchemaConflict(
            f"schema {schema.name} version {latest.version} differs from the inline schema; edit it, or name the "
            "inline schema differently"
        )
    if latest.status == "retired":
        raise SchemaConflict(f"schema {schema.name} version {latest.version} is retired")
    return latest


async def get(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    return await registry.get_by_id(conn, schema_id)


async def list_all(
    conn: AsyncConnection, *, name: str | None = None, status: SchemaStatus | None = None
) -> list[SchemaDef]:
    return await registry.list_schemas(conn, name=name, status=status)


async def update(conn: AsyncConnection, schema_id: SchemaId, content: SchemaContent) -> SchemaDef:
    """Add the version after `schema_id` with `content` as its whole document; `schema_id` must be the latest
    version, so an edit never silently drops a version someone else added."""
    current = await _changeable(conn, schema_id)
    if current.status == "retired":
        raise SchemaConflict(f"schema {current.name} version {current.version} is retired")
    changes = SchemaChanges.model_validate(content.model_dump())
    try:
        return await registry.new_version(conn, current.name, changes, "user", base_version=current.version)
    except NotLatest as e:
        latest = e.latest
        raise SchemaConflict(
            f"schema {current.name}: the latest version is {latest.version} ({latest.id}); edit that one"
        ) from e
    except SchemaExists as e:
        raise SchemaConflict(f"schema {current.name}: another version was added at the same time") from e
    except ValidationError as e:
        raise InvalidSchema(e) from e


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
