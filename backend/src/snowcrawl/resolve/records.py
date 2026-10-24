"""Records: what an entity's
field outcomes become.

`data` holds the published values and nothing else; `field_meta` says, for every schema field, how it resolved. A
page whose required fields and groups all publish is `extracted` and its record `complete`. Otherwise a caller-supplied
URL still gets its record, `complete=false`, with outcome `partial`, and a crawl-discovered URL gets `no_match` and no
record. Either way a record needs the page to state its entity: a page none of whose required fields or group members
has a candidate read from it, beyond the page's own address, is `no_match` with no record (`states_entity`), unless
its content is unreadable to the engine (`content.signals.UNREADABLE`): an extraction miss is `partial`, never
`no_match`. A listing's rows are records each, judged the same way (`assemble_listing`). Records only serialize what
resolution published.
"""

from collections.abc import Mapping, Sequence
from typing import Final, Literal, Protocol, get_args

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from snowcrawl.collect.locator import LocatorText, PageUrlDerivation
from snowcrawl.collect.schema_org_map import item_url_fields
from snowcrawl.db.models import RecordDelta, SiteId, SourceKind
from snowcrawl.normalize.base import Basis
from snowcrawl.resolve.evidence import required_fields
from snowcrawl.resolve.types import Derivation, Evidence, FieldOutcome, FieldSet, FieldStatus, Probability
from snowcrawl.schemas.types import SchemaDef
from snowcrawl.storage.capture_bundle import sha256_hex

PageOutcome = Literal["extracted", "partial", "no_match"]
# The derivations that publish the page's own address (RFC 6596 canonical link, RFC 9110 §15.4 final URL): every page,
# a maintenance or error page a request was redirected to included, has one, so it states no entity.
_PAGE_ADDRESS: Final = frozenset(get_args(PageUrlDerivation))
# The screening rejections of a value that is no evidence about the page's own item (`resolve.preference`, §8.2 rules 3
# and 4): another entity owns it, or the request URL carries it and the page does not show it.
_NOT_THE_ITEMS: Final = frozenset({"not_owned", "url_param"})


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _absent(value: object) -> bool:
    return value is None


class SubFieldMeta(_Model):
    """A row sub-field's outcome without its candidates."""

    status: FieldStatus
    reason: str | None
    evidence: Evidence | None
    confidence: Probability | None
    calibrated: bool
    source_kind: SourceKind | None
    locator: LocatorText | None
    # A published money value's weaker currency evidence (`page`, `locale`, `unknown`); left out
    # when the value states its currency.
    basis: Basis | None = Field(default=None, exclude_if=_absent)

    @classmethod
    def of(cls, outcome: FieldOutcome) -> "SubFieldMeta":
        return cls(**{name: getattr(outcome, name) for name in SubFieldMeta.model_fields})


class RowMeta(_Model):
    """A published row's sub-field outcomes, aligned with the field's value by index."""

    fields: dict[str, SubFieldMeta]


class DroppedRowMeta(_Model):
    """A row that did not publish: its row entities' locators and the reason."""

    locators: list[LocatorText]
    reason: str


class FieldMeta(SubFieldMeta):
    """`record.field_meta[field]`: the field's outcome without its candidates. A row-mapped field adds `items` and
    `dropped`; other fields have neither key, so the shape is additive."""

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


class FieldChange(_Model):
    """A field whose published value differs from the entity's previous record: both values as published, None for a
    side that published none."""

    field: str
    previous: JsonValue
    value: JsonValue


# A named schema (OpenAPI component), so the SDKs' generated enum has a name of its own.
type DeltaKind = RecordDelta


class Delta(_Model):
    """What a job's record is against the entity's previous record under the same schema:
    `new`, `changed` with its changed fields in schema order, or `same`."""

    kind: DeltaKind
    changes: list[FieldChange] = Field(default_factory=list)


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
            # The values as the page states them (`FieldOutcome.published`), never a canonical rewrite of them.
            data={name: outcome.published for name, outcome in fields.items() if outcome.status == "published"},
            field_meta={name: FieldMeta.of(outcome) for name, outcome in fields.items()},
            complete=is_complete(schema, fields),
        )


class RecordDraft(RecordContent):
    """A `record` row's content before storage gives it ids and a version."""

    entity_key: str


def entity_key(site_id: SiteId, canonical_url: str) -> str:
    """`sha256(site_id + canonical url)`, hex: the entity's identity across runs of one site. A UUID has one
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
    schema: SchemaDef,
    fields: FieldSet,
    *,
    site_id: SiteId,
    canonical_url: str,
    caller_supplied: bool,
    unreadable: bool,
) -> tuple[PageOutcome, RecordDraft | None]:
    """The page's outcome and its record, if it gets one. `canonical_url` is the target's canonicalized URL;
    `caller_supplied` is true for `scrape`, `batch_scrape` and `extract` URLs, false for crawl-discovered ones;
    `unreadable` is true for a page whose content the engine cannot read (`content.signals.unreadable`), which states
    its entity where the engine sees nothing of it."""
    content = RecordContent.of(schema, fields)
    if not (unreadable or states_entity(schema, fields)) or (not content.complete and not caller_supplied):
        return "no_match", None
    record = RecordDraft(entity_key=entity_key(site_id, canonical_url), **dict(content))
    return ("extracted" if content.complete else "partial"), record


def states_entity(schema: SchemaDef, fields: Mapping[str, FieldOutcome], *, row: bool = False) -> bool:
    """Whether the page states the schema's entity: a field it needs (`required_fields`; any field of a schema that
    needs none) has a candidate read from the page, published or not (resolution may reject it), beyond a value derived
    from its own address (`_PAGE_ADDRESS`). A page that is not the entity asked for (a maintenance or error page served
    for it) may still state prose as a description; it states none of what identifies the item, so it gets no record.
    With `row`, a listing's row states its item by a row field only: the needed row fields, else any row field (the
    page's fields are every row's)."""
    in_scope = frozenset(name for name, spec in schema.fields.items() if not row or spec.scope == "row")
    needed = (required_fields(schema) & in_scope) or in_scope
    return any(_read_from_page(outcome) for name, outcome in fields.items() if name in needed)


def _read_from_page(outcome: FieldOutcome) -> bool:
    """Whether the field has a candidate from the page: a published value, or one resolution kept or rejected for a
    reason other than its being no evidence about the item (`_NOT_THE_ITEMS`). A field whose value is the page's own
    address (`_PAGE_ADDRESS`) has none: its other candidates named another document or lost to that address."""
    if outcome.derived_by in _PAGE_ADDRESS:
        return False
    rejected = any(reason not in _NOT_THE_ITEMS for _, reason in outcome.rejected)
    return outcome.status == "published" or bool(outcome.kept) or rejected


def assemble_listing(
    schema: SchemaDef,
    page_fields: FieldSet,
    rows: Sequence[FieldSet],
    *,
    site_id: SiteId,
    page_url: str,
    caller_supplied: bool,
) -> tuple[PageOutcome, tuple[RecordDraft, ...]]:
    """A listing's outcome and its records: one per row, holding the row's fields and the page's, keyed by
    the row's URL (`_row_key`); a URL listed twice is one record, the first. Each row keeps or loses its record as a
    detail page does. `extracted` when every row is complete, `no_match` when no record is kept (or there is no row),
    else `partial`."""
    records: dict[str, RecordDraft] = {}
    complete = bool(rows)
    for position, row in enumerate(rows, start=1):
        fields = {**page_fields, **row}
        key = _row_key(schema, row) or f"{page_url}#{position}"
        outcome, record = assemble(
            schema, fields, site_id=site_id, canonical_url=key, caller_supplied=caller_supplied, unreadable=False
        )
        if not states_entity(schema, row, row=True):
            outcome, record = "no_match", None
        complete = complete and outcome == "extracted"
        if record is not None:
            records.setdefault(record.entity_key, record)
    if not records:
        return "no_match", ()
    return ("extracted" if complete else "partial"), tuple(records.values())


def _row_key(schema: SchemaDef, row: FieldSet) -> str | None:
    """The row's published URL: the first of its item URL fields (`collect.schema_org_map.item_url_fields`) it
    publishes. Without one, the row's position on the page stands in."""
    for name in item_url_fields(schema):
        outcome = row.get(name)
        if outcome is not None and isinstance(outcome.value, str):
            return outcome.value
    return None
