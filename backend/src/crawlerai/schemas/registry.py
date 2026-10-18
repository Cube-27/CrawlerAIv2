"""The schema registry (SPEC-04 §4.1): `schema_def` rows read and written as validated documents.

One row per schema name, edited in place (ARCHITECTURE §5.2). An edit's callers send the site configs learned for the
old document back to learning (`config_ir.progressive.relearn_schema`).
Every document is validated as a `SchemaDocument` before it is written, so a stored row always parses.
"""

import json
from collections.abc import Sequence
from importlib.resources import files
from typing import Any

from sqlalchemy import Row, insert, null, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.errors import Refusal
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.db.models import SchemaId, SchemaOrigin, SchemaStatus
from crawlerai.schemas.types import FieldLabels, SchemaChanges, SchemaDef, SchemaDocument


class SchemaNotFound(Refusal):
    pass


class SchemaExists(Exception):
    """`create` was given a name that already has a schema, or two writers raced for the same name."""


class PresetConflict(Exception):
    """A preset file names a schema stored under that name by a caller, not as a preset."""


_COLUMNS = (
    SchemaRow.id,
    SchemaRow.name,
    SchemaRow.page_kind,
    SchemaRow.fields,
    SchemaRow.required_groups,
    SchemaRow.origin,
    SchemaRow.status,
    SchemaRow.labels,
)


def _from_row(row: Row[Any]) -> SchemaDef:
    return SchemaDef.model_validate(row._asdict())


async def find(conn: AsyncConnection, name: str) -> SchemaDef | None:
    row = (await conn.execute(select(*_COLUMNS).where(SchemaRow.name == name))).one_or_none()
    return None if row is None else _from_row(row)


async def get(conn: AsyncConnection, name: str) -> SchemaDef:
    found = await find(conn, name)
    if found is None:
        raise SchemaNotFound(f"no schema {name}")
    return found


async def get_by_id(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    row = (await conn.execute(select(*_COLUMNS).where(SchemaRow.id == schema_id))).one_or_none()
    if row is None:
        raise SchemaNotFound(f"no schema with id {schema_id}")
    return _from_row(row)


async def list_schemas(
    conn: AsyncConnection, *, name: str | None = None, status: SchemaStatus | None = None
) -> list[SchemaDef]:
    """Every schema, by name; only `name` and those in `status` when given."""
    query = select(*_COLUMNS).order_by(SchemaRow.name)
    if name is not None:
        query = query.where(SchemaRow.name == name)
    if status is not None:
        query = query.where(SchemaRow.status == status)
    return [_from_row(row) for row in (await conn.execute(query)).all()]


async def create(conn: AsyncConnection, document: SchemaDocument, origin: SchemaOrigin) -> SchemaDef:
    """Insert a new, active schema. A name that already has a schema raises `SchemaExists`: changing a schema is
    `update`."""
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
        raise SchemaExists(f"schema {document.name} exists") from e
    return _from_row(row)


async def update_schema(conn: AsyncConnection, current: SchemaDef, changes: SchemaChanges) -> SchemaDef:
    """Apply `changes` to the stored schema `current` in place, validated as a whole document; `current` itself when
    the document stays the same. Raises pydantic's `ValidationError` for a document that breaks a schema rule. What
    was learned for the old document is the caller's to send back to learning (`progressive.relearn_schema`)."""
    document = SchemaDocument.model_validate({**_document(current), **changes.model_dump(exclude_none=True)})
    return await _write_if_changed(conn, current, document)


async def retire(conn: AsyncConnection, schema_id: SchemaId) -> SchemaDef:
    """Set the schema's status to `retired`. The row stays: records and configs reference it."""
    row = (
        await conn.execute(
            update(SchemaRow).where(SchemaRow.id == schema_id).values(status="retired").returning(*_COLUMNS)
        )
    ).one_or_none()
    if row is None:
        raise SchemaNotFound(f"no schema with id {schema_id}")
    return _from_row(row)


async def store_labels(
    conn: AsyncConnection, schema: SchemaDef, labels: FieldLabels, *, drafted: bool = False
) -> SchemaDef | None:
    """Store the label synonyms (`SchemaDef.labels`) of `schema`'s document and return the stored schema: only while
    the row still holds that document (labels of other fields are no labels of these), and with `drafted` only while
    it has none, so of two drafts the first stays. None when nothing was stored."""
    document = schema.model_dump(mode="json", include={"fields", "required_groups"}, exclude_none=True)
    query = update(SchemaRow).where(
        SchemaRow.id == schema.id,
        SchemaRow.page_kind == schema.page_kind,
        SchemaRow.fields == document["fields"],
        SchemaRow.required_groups == document["required_groups"],
    )
    if drafted:
        query = query.where(SchemaRow.labels.is_(None))
    row = (await conn.execute(query.values(labels=labels).returning(*_COLUMNS))).one_or_none()
    return None if row is None else _from_row(row)


async def _write_if_changed(conn: AsyncConnection, current: SchemaDef, document: SchemaDocument) -> SchemaDef:
    """Write `document` over the stored one when it differs. Label synonyms were drafted for the old document's fields,
    so they go with it, to be drafted again (`SchemaDef.labels`)."""
    if document.model_dump(exclude_none=True) == _document(current):
        return current
    values = document.model_dump(mode="json", exclude_none=True, exclude={"name"}) | {"labels": null()}
    query = update(SchemaRow).where(SchemaRow.id == current.id).values(**values).returning(*_COLUMNS)
    return _from_row((await conn.execute(query)).one())


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
    """Upsert each preset file's document (§4.2), and return the rows inserted or changed. A changed preset is edited
    in place like any schema (`update_schema`), and is the caller's to relearn. A preset name a caller's schema holds
    is `PresetConflict`, and nothing is written."""
    presets = load_presets() if presets is None else presets
    query = select(*_COLUMNS).where(SchemaRow.name.in_({preset.name for preset in presets}))
    stored = {row.name: _from_row(row) for row in (await conn.execute(query)).all()}
    if taken := sorted(name for name, row in stored.items() if row.origin != "preset"):
        raise PresetConflict(f"preset names {taken} are stored as other schemas")
    written = []
    for preset in presets:
        row = stored.get(preset.name)
        if row is None:
            written.append(await create(conn, preset, "preset"))
        elif (edited := await _write_if_changed(conn, row, preset)) != row:
            written.append(edited)
    return written


def _document(schema: SchemaDef) -> dict[str, Any]:
    """The document part of a stored schema, without its identity and lifecycle."""
    return schema.model_dump(include=set(SchemaDocument.model_fields), exclude_none=True)
