"""Records (SPEC-05 §4.10, ARCHITECTURE §6 `record`, §10 "Incomplete pages", INV-22, INV-27): what an entity's
field outcomes become.

`data` holds the published values and nothing else; `field_meta` says, for every schema field, how it resolved. A
page whose required fields and groups all publish is `extracted` and its record `complete`. Otherwise a caller-supplied
URL still gets its record, `complete=false`, with outcome `partial`, and a crawl-discovered URL gets `no_match` and no
record. Records only serialize what resolution published (INV-27).
"""

import hashlib
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.collect.locator import LocatorText
from crawlerai.db.models import SiteId, SourceKind
from crawlerai.resolve.evidence import required_fields
from crawlerai.resolve.types import Derivation, Evidence, FieldOutcome, FieldSet, FieldStatus, Probability
from crawlerai.schemas.types import SchemaDef

PageOutcome = Literal["extracted", "partial", "no_match"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldMeta(_Model):
    """`record.field_meta[field]` (§6): the field's outcome without its candidates."""

    status: FieldStatus
    reason: str | None
    evidence: Evidence | None
    confidence: Probability | None
    calibrated: bool
    source_kind: SourceKind | None
    locator: LocatorText | None
    derived_by: Derivation | None

    @classmethod
    def of(cls, outcome: FieldOutcome) -> "FieldMeta":
        return cls.model_validate(outcome.model_dump(include=set(cls.model_fields)))


class RecordDraft(_Model):
    """A `record` row's content before storage gives it ids and a version."""

    entity_key: str
    data: dict[str, JsonValue]
    field_meta: dict[str, FieldMeta]
    complete: bool


def entity_key(site_id: SiteId, canonical_url: str) -> str:
    """`sha256(site_id + canonical url)` (§4.10), hex: the entity's identity across runs of one site. A UUID has one
    length, so the concatenation is unambiguous."""
    return hashlib.sha256(f"{site_id}{canonical_url}".encode()).hexdigest()


def is_complete(schema: SchemaDef, fields: Mapping[str, FieldOutcome]) -> bool:
    """§10: every required field publishes, and every required group has a member that publishes."""
    published = {name for name, outcome in fields.items() if outcome.status == "published"}
    required = all(name in published for name, spec in schema.fields.items() if spec.required)
    return required and all(published.intersection(group) for group in schema.required_groups)


def record_confidence(schema: SchemaDef, fields: Mapping[str, FieldOutcome]) -> float | None:
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
    if fields.keys() != schema.fields.keys():
        raise ValueError(f"field outcomes {sorted(fields)} do not match the schema's {sorted(schema.fields)}")
    complete = is_complete(schema, fields)
    if not complete and not caller_supplied:
        return "no_match", None
    record = RecordDraft(
        entity_key=entity_key(site_id, canonical_url),
        data={name: outcome.value for name, outcome in fields.items() if outcome.status == "published"},
        field_meta={name: FieldMeta.of(outcome) for name, outcome in fields.items()},
        complete=complete,
    )
    return ("extracted" if complete else "partial"), record
