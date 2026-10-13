"""Records as the API returns them (SPEC-07 §4.4, ARCHITECTURE §13.1, INV-22, INV-27): `scrape` answers with them, and
`/v1/records` and replay will (PR 8).

Every schema field is a member, published or not, with the §13.1 attributes (`value`, `status`, `evidence`,
`confidence`, `calibrated`, `locator`) and `reason`, `source_kind`, `derived_by` from `field_meta`. The value is the
record's published value, unchanged (INV-27), and `None` for a field that did not publish.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.db.models import ExtractionMode, RecordId
from crawlerai.resolve.records import FieldMeta, RecordDraft
from crawlerai.resolve.types import Probability


class RecordField(FieldMeta):
    value: JsonValue


class ScrapedRecord(BaseModel):
    """A record (§6 `record`): `complete` when every required field and group published (§10), and its confidence,
    the minimum over the required fields, `None` when any of them is uncalibrated."""

    model_config = ConfigDict(frozen=True)

    id: RecordId
    mode: ExtractionMode
    complete: bool
    confidence: Probability | None
    fields: dict[str, RecordField]

    @classmethod
    def of(cls, record_id: RecordId, draft: RecordDraft, *, mode: ExtractionMode, confidence: float | None) -> Self:
        fields = {
            name: RecordField(**meta.model_dump(), value=draft.data.get(name))
            for name, meta in draft.field_meta.items()
        }
        return cls(id=record_id, mode=mode, complete=draft.complete, confidence=confidence, fields=fields)
