"""Helpers the adapter tests share: the candidates an adapter's shapes give a recorded answer."""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from crawlerai.adapters.base import Adapter, AdapterMatch
from crawlerai.collect.adapter import AdapterCollector
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

FIXTURES = Path(__file__).parents[1] / "fixtures"
VOCABULARY = Vocabulary.read(FIXTURES / "synthetic" / "schemaorg_vocabulary.jsonld")
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))


def field(type_: FieldType, path: str, *, item: FieldType | None = None) -> FieldSpec:
    return FieldSpec(
        type=type_,
        description="d",
        schema_org=path,
        scheme="custom" if type_ is FieldType.IDENTIFIER else None,
        item=None if item is None else FieldSpec(type=item),
    )


# The JobPosting properties every job adapter maps, as fields of a schema (the names are the schema's own).
JOB_FIELDS = {
    "title": field(FieldType.TEXT, "JobPosting.title"),
    "url": field(FieldType.URL, "JobPosting.url"),
    "description": field(FieldType.LONG_TEXT, "JobPosting.description"),
    "date_posted": field(FieldType.DATE, "JobPosting.datePosted"),
    "employment_type": field(FieldType.TEXT, "JobPosting.employmentType"),
    "locations": field(FieldType.LIST, "JobPosting.jobLocation", item=FieldType.LOCATION),
    "identifier": field(FieldType.IDENTIFIER, "JobPosting.identifier"),
    "salary": field(FieldType.RANGE, "JobPosting.baseSalary"),
    "company": field(FieldType.TEXT, "JobPosting.hiringOrganization.name"),
}


def candidates(
    adapter: Adapter, match: AdapterMatch, body: str, fields: dict[str, FieldSpec] | None = None
) -> dict[tuple[str, str], JsonValue]:
    """The normalized-input values (`raw`) of `adapter`'s candidates from `body`, by (entity id, field)."""
    schema = SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="jobs",
        page_kind=match.page_kind,
        fields=JOB_FIELDS if fields is None else fields,
    )
    result = AdapterCollector(adapter, match, VOCABULARY).collect(ParsedPage(body), schema, CTX)
    return {(c.entity_id, c.field): c.raw for c in result.candidates}
