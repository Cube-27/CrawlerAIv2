"""The schema registry (SPEC-04 §4.1): `schema_def` rows read and written as validated documents.

Rows are immutable per (name, version) (ARCHITECTURE §5.2): nothing here updates a row's document; a change is
`new_version`. Every document is validated as a `SchemaDocument` before it is written, so a stored row always
parses.
"""

import json
from collections.abc import Sequence
from importlib.resources import files
from typing import Any

from sqlalchemy import Row, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.db.models import SchemaId, SchemaOrigin, SchemaStatus
from crawlerai.schemas.types import SchemaChanges, SchemaDef, SchemaDocument


class SchemaNotFound(Exception):
    pass


class SchemaExists(Exception):
    """`create` was given a name that already has a schema, or two writers raced for the same version."""


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


async def list_schemas(conn: AsyncConnection, *, status: SchemaStatus | None = None) -> list[SchemaDef]:
    """Every version of every schema, by name then version; only those in `status` when it is given."""
    query = select(*_COLUMNS).order_by(SchemaRow.name, SchemaRow.version)
    if status is not None:
        query = query.where(SchemaRow.status == status)
    return [_from_row(row) for row in (await conn.execute(query)).all()]


async def create(conn: AsyncConnection, document: SchemaDocument, origin: SchemaOrigin) -> SchemaDef:
    """Insert a new schema at version 1. A name that already has a schema raises `SchemaExists`: changing a schema
    is `new_version`."""
    if document.version != 1:
        raise ValueError(f"a new schema starts at version 1, not {document.version}")
    if await _latest_version(conn, document.name) is not None:
        raise SchemaExists(f"schema {document.name} exists; add a version instead")
    return await _insert(conn, document, origin)


async def new_version(conn: AsyncConnection, name: str, changes: SchemaChanges, origin: SchemaOrigin) -> SchemaDef:
    """Insert version latest + 1 of `name`: the latest version's document with `changes` applied, validated as a
    whole. Earlier versions stay as they are, since records and configs reference them (§5.2)."""
    latest_version = await _latest_version(conn, name)
    if latest_version is None:
        raise SchemaNotFound(f"no schema {name}")
    latest = await get(conn, name, latest_version)
    document = SchemaDocument.model_validate(
        {
            "name": name,
            "version": latest_version + 1,
            "page_kind": changes.page_kind or latest.page_kind,
            "fields": changes.fields if changes.fields is not None else latest.fields,
            "required_groups": (
                changes.required_groups if changes.required_groups is not None else latest.required_groups
            ),
        }
    )
    return await _insert(conn, document, origin)


async def _latest_version(conn: AsyncConnection, name: str) -> int | None:
    latest: int | None = (
        await conn.execute(select(func.max(SchemaRow.version)).where(SchemaRow.name == name))
    ).scalar_one()
    return latest


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
    pending = []
    for preset in load_presets() if presets is None else presets:
        rows = (await conn.execute(select(*_COLUMNS).where(SchemaRow.name == preset.name))).all()
        stored = {row.version: row for row in rows}
        newest = max((row.version for row in rows if row.origin == "preset"), default=0)
        if preset.version < newest:
            raise PresetConflict(f"preset {preset.name} is version {preset.version}; version {newest} is stored")
        row = stored.get(preset.version)
        if row is None:
            pending.append(preset)
        elif row.origin != "preset" or _document(row) != preset:
            raise PresetConflict(
                f"{preset.name} version {preset.version} is stored with other contents; bump the preset's version"
            )
    return [await _insert(conn, preset, "preset") for preset in pending]


def _document(row: Row[Any]) -> SchemaDocument:
    return SchemaDocument.model_validate(
        {key: row._mapping[key] for key in ("name", "version", "page_kind", "fields", "required_groups")}
    )
