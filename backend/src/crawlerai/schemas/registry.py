"""The schema registry (SPEC-04 §4.1): `schema_def` rows read and written as validated documents.

Rows are immutable per (name, version) (ARCHITECTURE §5.2): nothing here updates a row's document; a change is
`new_version`. Only a row's lifecycle changes in place (`retire`). Every document is validated as a `SchemaDocument`
before it is written, so a stored row always parses.
"""

import json
from collections.abc import Sequence
from importlib.resources import files
from typing import Any

from sqlalchemy import Row, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.db.models import SchemaId, SchemaOrigin, SchemaStatus
from crawlerai.schemas.types import SchemaChanges, SchemaDef, SchemaDocument


class SchemaNotFound(Exception):
    pass


class SchemaExists(Exception):
    """`create` was given a name that already has a schema, or two writers raced for the same version."""


class NotLatest(Exception):
    """`new_version` was asked to build on a version that is no longer the latest one: someone else added a version
    since it was read."""

    def __init__(self, latest: SchemaDef) -> None:
        super().__init__(f"schema {latest.name} is at version {latest.version}")
        self.latest = latest


class PresetConflict(Exception):
    """A preset file disagrees with the database: its stored version has other contents, or it is older than a
    stored preset version. A changed preset needs a version bump (§4.2)."""


_COLUMNS = (
    SchemaRow.id,
    SchemaRow.name,
    SchemaRow.version,
    SchemaRow.page_kind,
    SchemaRow.fields,
    SchemaRow.required_groups,
    SchemaRow.origin,
    SchemaRow.status,
)


def _from_row(row: Row[Any]) -> SchemaDef:
    return SchemaDef.model_validate(row._asdict())


async def get(conn: AsyncConnection, name: str, version: int) -> SchemaDef:
    row = (
        await conn.execute(select(*_COLUMNS).where(SchemaRow.name == name, SchemaRow.version == version))
    ).one_or_none()
    if row is None:
        raise SchemaNotFound(f"no schema {name} version {version}")
    return _from_row(row)


async def get_by_id(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    row = (await conn.execute(select(*_COLUMNS).where(SchemaRow.id == schema_id))).one_or_none()
    if row is None:
        raise SchemaNotFound(f"no schema with id {schema_id}")
    return _from_row(row)


async def list_schemas(
    conn: AsyncConnection, *, name: str | None = None, status: SchemaStatus | None = None
) -> list[SchemaDef]:
    """Every version of every schema, by name then version; only those of `name` and in `status` when given."""
    query = select(*_COLUMNS).order_by(SchemaRow.name, SchemaRow.version)
    if name is not None:
        query = query.where(SchemaRow.name == name)
    if status is not None:
        query = query.where(SchemaRow.status == status)
    return [_from_row(row) for row in (await conn.execute(query)).all()]


async def create(conn: AsyncConnection, document: SchemaDocument, origin: SchemaOrigin) -> SchemaDef:
    """Insert a new schema at version 1. A name that already has a schema raises `SchemaExists`: changing a schema
    is `new_version`."""
    if document.version != 1:
        raise ValueError(f"a new schema starts at version 1, not {document.version}")
    if await _latest(conn, document.name) is not None:
        raise SchemaExists(f"schema {document.name} exists; add a version instead")
    return await _insert(conn, document, origin)


async def new_version(
    conn: AsyncConnection, name: str, changes: SchemaChanges, origin: SchemaOrigin, *, base_version: int | None = None
) -> SchemaDef:
    """Insert version latest + 1 of `name`: the latest version's document with `changes` applied, validated as a
    whole. Earlier versions stay as they are, since records and configs reference them (§5.2).

    `base_version` is the version the caller's changes were made to; when another version has been added since,
    `NotLatest`. Two writers racing from the same base both read it as latest, and the second insert is
    `SchemaExists`."""
    latest = await _latest(conn, name)
    if latest is None:
        raise SchemaNotFound(f"no schema {name}")
    if base_version is not None and latest.version != base_version:
        raise NotLatest(latest)
    document = SchemaDocument.model_validate(
        {**_document(latest), "version": latest.version + 1, **changes.model_dump(exclude_none=True)}
    )
    return await _insert(conn, document, origin)


async def retire(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    """Set one version's status to `retired`. The row stays: records and configs reference it (§5.2)."""
    row = (
        await conn.execute(
            update(SchemaRow).where(SchemaRow.id == schema_id).values(status="retired").returning(*_COLUMNS)
        )
    ).one_or_none()
    if row is None:
        raise SchemaNotFound(f"no schema with id {schema_id}")
    return _from_row(row)


async def _latest(conn: AsyncConnection, name: str) -> SchemaDef | None:
    query = select(*_COLUMNS).where(SchemaRow.name == name).order_by(SchemaRow.version.desc()).limit(1)
    row = (await conn.execute(query)).one_or_none()
    return None if row is None else _from_row(row)


async def _insert(conn: AsyncConnection, document: SchemaDocument, origin: SchemaOrigin) -> SchemaDef:
    values = document.model_dump(mode="json", exclude_none=True)
    try:
        # A savepoint, so a lost race leaves the caller's transaction usable.
        async with conn.begin_nested():
            row = (
                await conn.execute(
                    insert(SchemaRow).values(**values, origin=origin, status="active").returning(*_COLUMNS)
                )
            ).one()
    except IntegrityError as e:
        raise SchemaExists(f"schema {document.name} version {document.version} exists") from e
    return _from_row(row)


def load_presets() -> list[SchemaDocument]:
    """The preset documents shipped in `crawlerai/schemas/presets/` (§5.3), by name. A file is named after its
    schema."""
    presets = []
    for entry in sorted(files("crawlerai.schemas").joinpath("presets").iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".json"):
            continue
        document = SchemaDocument.model_validate(json.loads(entry.read_text(encoding="utf-8")))
        if entry.name != f"{document.name}.json":
            raise PresetConflict(f"preset file {entry.name} holds schema {document.name}")
        presets.append(document)
    return presets


async def sync_presets(conn: AsyncConnection, presets: Sequence[SchemaDocument] | None = None) -> list[SchemaDef]:
    """Insert each preset whose (name, version) is not stored yet, and return the rows inserted.

    A preset already stored must be stored as written, and must not be older than a stored preset version of its
    name; otherwise `PresetConflict`, and nothing is inserted. That is the version-bump rule (§4.2): a preset file
    changes only together with its version.
    """
    presets = load_presets() if presets is None else presets
    query = select(*_COLUMNS).where(SchemaRow.name.in_({preset.name for preset in presets}))
    stored: dict[tuple[str, int], SchemaDef] = {
        (row.name, row.version): _from_row(row) for row in (await conn.execute(query)).all()
    }
    pending = []
    for preset in presets:
        newest = max(
            (v for (name, v), row in stored.items() if name == preset.name and row.origin == "preset"), default=0
        )
        if preset.version < newest:
            raise PresetConflict(f"preset {preset.name} is version {preset.version}; version {newest} is stored")
        row = stored.get((preset.name, preset.version))
        if row is None:
            pending.append(preset)
        elif row.origin != "preset" or _document(row) != preset.model_dump(exclude_none=True):
            raise PresetConflict(
                f"{preset.name} version {preset.version} is stored with other contents; bump the preset's version"
            )
    return [await _insert(conn, preset, "preset") for preset in pending]


def _document(schema: SchemaDef) -> dict[str, Any]:
    """The document part of a stored schema, without its identity and lifecycle."""
    return schema.model_dump(include=set(SchemaDocument.model_fields), exclude_none=True)
