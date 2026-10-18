"""Records (resolution spec, INV-22, INV-27): what an entity's
field outcomes become.

`data` holds the published values and nothing else; `field_meta` says, for every schema field, how it resolved. A
page whose required fields and groups all publish is `extracted` and its record `complete`. Otherwise a caller-supplied
URL still gets its record, `complete=false`, with outcome `partial`, and a crawl-discovered URL gets `no_match` and no
record. A listing's rows are records each, judged the same way (`assemble_listing`). Records only serialize what
resolution published (INV-27).
"""

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from crawlerai.collect.locator import LocatorText
from crawlerai.collect.schema_org_map import parse_paths
from crawlerai.db.models import SiteId, SourceKind
from crawlerai.normalize.base import Basis
from crawlerai.resolve.evidence import required_fields
from crawlerai.resolve.types import Derivation, Evidence, FieldOutcome, FieldSet, FieldStatus, Probability
from crawlerai.schemas.types import FieldType, SchemaDef
from crawlerai.storage.capture_bundle import sha256_hex

PageOutcome = Literal["extracted", "partial", "no_match"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _absent(value: object) -> bool:
    return value is None


class SubFieldMeta(_Model):
    """A row sub-field's outcome without its candidates (variants spec, INV-34)."""

    status: FieldStatus
    reason: str | None
    evidence: Evidence | None
    confidence: Probability | None
    calibrated: bool
    source_kind: SourceKind | None
    locator: LocatorText | None
    # A published money value's weaker currency evidence (`page`, `locale`, `unknown`: resolution spec); left out
    # when the value states its currency.
    basis: Basis | None = Field(default=None, exclude_if=_absent)

    @classmethod
    def of(cls, outcome: FieldOutcome) -> "SubFieldMeta":
        return cls(**{name: getattr(outcome, name) for name in SubFieldMeta.model_fields})


class RowMeta(_Model):
    """A published row's sub-field outcomes, aligned with the field's value by index (variants spec)."""

    fields: dict[str, SubFieldMeta]


class DroppedRowMeta(_Model):
    """A row that did not publish: its row entities' locators and the reason (variants spec)."""

    locators: list[LocatorText]
    reason: str


class FieldMeta(SubFieldMeta):
    """`record.field_meta[field]` (§6): the field's outcome without its candidates. A row-mapped field adds `items` and
    `dropped` (variants spec); other fields have neither key, so the shape is additive."""

    derived_by: Derivation | None
    items: list[RowMeta] | None = Field(default=None, exclude_if=_absent)
    dropped: list[DroppedRowMeta] | None = Field(default=None, exclude_if=_absent)

    @classmethod
    def of(cls, outcome: FieldOutcome) -> "FieldMeta":
        items = None
        if outcome.items is not None:
            items = [RowMeta(fields={n: SubFieldMeta.of(o) for n, o in row.fields.items()}) for row in outcome.items]
        dropped = None
        if outcome.dropped is not None:
            dropped = [DroppedRowMeta(locators=list(row.locators), reason=row.reason) for row in outcome.dropped]
        return cls(**dict(SubFieldMeta.of(outcome)), derived_by=outcome.derived_by, items=items, dropped=dropped)


class RecordContent(_Model):
    """What an entity's field outcomes make of a record: the published values, every field's meta, completeness."""

    data: dict[str, JsonValue]
    field_meta: dict[str, FieldMeta]
    complete: bool

    @classmethod
    def of(cls, schema: SchemaDef, fields: FieldSet) -> "RecordContent":
        if fields.keys() != schema.fields.keys():
            raise ValueError(f"field outcomes {sorted(fields)} do not match the schema's {sorted(schema.fields)}")
        return cls(
            data={name: outcome.value for name, outcome in fields.items() if outcome.status == "published"},
            field_meta={name: FieldMeta.of(outcome) for name, outcome in fields.items()},
            complete=is_complete(schema, fields),
        )


class RecordDraft(RecordContent):
    """A `record` row's content before storage gives it ids and a version."""

    entity_key: str


def entity_key(site_id: SiteId, canonical_url: str) -> str:
    """`sha256(site_id + canonical url)` (§4.10), hex: the entity's identity across runs of one site. A UUID has one
    length, so the concatenation is unambiguous."""
    return sha256_hex(f"{site_id}{canonical_url}".encode())


def is_complete(schema: SchemaDef, fields: Mapping[str, FieldOutcome]) -> bool:
    """§10: every required field publishes, and every required group has a member that publishes."""
    published = {name for name, outcome in fields.items() if outcome.status == "published"}
    required = all(name in published for name, spec in schema.fields.items() if spec.required)
    return required and all(published.intersection(group) for group in schema.required_groups)


class Assessed(Protocol):
    """What a record's confidence reads of a field: a `FieldOutcome`, or the `FieldMeta` a stored record keeps."""

    @property
    def status(self) -> FieldStatus: ...
    @property
    def confidence(self) -> float | None: ...
    @property
    def calibrated(self) -> bool: ...


def record_confidence(schema: SchemaDef, fields: Mapping[str, Assessed]) -> float | None:
    """§10: the minimum confidence over the required fields that published, and `None` if any of them is
    uncalibrated (or none published)."""
    needed = required_fields(schema)
    published = [outcome for name, outcome in fields.items() if name in needed and outcome.status == "published"]
    if not published or not all(outcome.calibrated for outcome in published):
        return None
    return min(outcome.confidence for outcome in published if outcome.confidence is not None)


def assemble(
    schema: SchemaDef, fields: FieldSet, *, site_id: SiteId, canonical_url: str, caller_supplied: bool
) -> tuple[PageOutcome, RecordDraft | None]:
    """The page's outcome and its record, if it gets one (§4.10). `canonical_url` is the target's canonicalized URL;
    `caller_supplied` is true for `scrape`, `batch_scrape` and `extract` URLs, false for crawl-discovered ones."""
    content = RecordContent.of(schema, fields)
    if not content.complete and not caller_supplied:
        return "no_match", None
    record = RecordDraft(entity_key=entity_key(site_id, canonical_url), **dict(content))
    return ("extracted" if content.complete else "partial"), record


def assemble_listing(
    schema: SchemaDef,
    page_fields: FieldSet,
    rows: Sequence[FieldSet],
    *,
    site_id: SiteId,
    page_url: str,
    caller_supplied: bool,
) -> tuple[PageOutcome, tuple[RecordDraft, ...]]:
    """A listing's outcome and its records (§4.10): one per row, holding the row's fields and the page's, keyed by
    the row's URL (`_row_key`); a URL listed twice is one record, the first. Each row keeps or loses its record as a
    detail page does. `extracted` when every row is complete, `no_match` when no record is kept (or there is no row),
    else `partial`."""
    records: dict[str, RecordDraft] = {}
    complete = bool(rows)
    for position, row in enumerate(rows, start=1):
        fields = {**page_fields, **row}
        key = _row_key(schema, row) or f"{page_url}#{position}"
        outcome, record = assemble(schema, fields, site_id=site_id, canonical_url=key, caller_supplied=caller_supplied)
        complete = complete and outcome == "extracted"
        if record is not None:
            records.setdefault(record.entity_key, record)
    if not records:
        return "no_match", ()
    return ("extracted" if complete else "partial"), tuple(records.values())


def row_url_fields(schema: SchemaDef) -> list[str]:
    """The names of the schema's row fields that hold a row's URL, in order: a field of type url whose path is `T.url`
    in every alternative (schema.org Thing.url, "URL of the item")."""
    return [
        name
        for name, spec in schema.fields.items()
        if spec.scope == "row"
        and spec.type is FieldType.URL
        and spec.schema_org is not None
        and all(path.steps == ("url",) and path.joined is None for path in parse_paths(spec.schema_org))
    ]


def _row_key(schema: SchemaDef, row: FieldSet) -> str | None:
    """The row's published URL: the first of `row_url_fields` it publishes. Without one, the row's position on the page
    stands in."""
    for name in row_url_fields(schema):
        outcome = row.get(name)
        if outcome is not None and isinstance(outcome.value, str):
            return outcome.value
    return None
