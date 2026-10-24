"""Records: published values only in `data`,
`field_meta` for every field, `complete`, the entity key, `partial` for caller-supplied URLs and `no_match` with no
record for crawl-discovered ones."""

import hashlib
import uuid
from typing import Any

from snowcrawl.collect.base import Candidate
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import SchemaId, SiteId
from snowcrawl.normalize.base import Ok
from snowcrawl.resolve.records import (
    assemble,
    assemble_listing,
    entity_key,
)
from snowcrawl.resolve.types import FieldOutcome
from snowcrawl.schemas.types import FieldSpec, FieldType, SchemaDef

SITE = SiteId(uuid.UUID("01900000-0000-7000-8000-0000000000aa"))
URL = "https://shop.example.test/p/1"
LOCATOR = "jsonld:0:$['sku']"


def _published(value: str = "A-1", confidence: float | None = 0.99, *, calibrated: bool = True) -> FieldOutcome:
    chosen = Candidate(
        field="f",
        entity_id="jsonld:0:$",
        source_kind="jsonld",
        raw=value,
        normalized=Ok(value),
        locator=LOCATOR,
        independent=True,
    )
    return FieldOutcome(
        status="published",
        reason=None,
        value=value,
        evidence="structured",
        confidence=confidence,
        calibrated=calibrated,
        source_kind="jsonld",
        locator=LOCATOR,
        derived_by=None,
        chosen=chosen,
        rejected=(),
    )


def _unpublished(status: Any = "missing", reason: str = "no_candidates") -> FieldOutcome:
    return FieldOutcome(
        status=status,
        reason=reason,
        value=None,
        evidence=None,
        confidence=None,
        calibrated=False,
        source_kind=None,
        locator=None,
        derived_by=None,
        chosen=None,
        rejected=(),
    )


def _schema(groups: list[list[str]] | None = None) -> SchemaDef:
    def spec(*, required: bool = False) -> FieldSpec:
        return FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", required=required)

    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="s",
        page_kind="detail",
        required_groups=groups or [],
        fields={"sku": spec(required=True), "gtin": spec(), "mpn": spec()},
    )


def test_a_complete_page_is_extracted_with_its_published_values() -> None:
    fields = {"sku": _published("A-1"), "gtin": _published("4006381333931"), "mpn": _unpublished()}

    outcome, record = assemble(
        _schema(), fields, site_id=SITE, canonical_url=URL, caller_supplied=False, unreadable=False
    )

    assert outcome == "extracted"
    assert record is not None
    assert record.complete is True
    assert record.data == {"sku": "A-1", "gtin": "4006381333931"}  # published fields only
    assert record.entity_key == hashlib.sha256(f"{SITE}{URL}".encode()).hexdigest()


def test_a_page_with_no_candidate_for_a_needed_field_beyond_its_own_address_has_no_record() -> None:
    """A maintenance or error page served for the URL: prose, and the page's own address, but no candidate the record
    needs read from the page. A needed field's candidate resolution rejected is an extraction miss, `partial`, unless
    it is no evidence about the item (another entity's value)."""
    address = _published(URL).model_copy(update={"derived_by": "final_url", "source_kind": "derived"})
    schema = _schema([["sku", "mpn"]])
    stating = {"sku": _published("A-1"), "gtin": _unpublished(), "mpn": _unpublished()}
    candidate = _published().chosen
    assert candidate is not None

    def rejected(reason: str) -> FieldOutcome:
        return _unpublished(reason=reason).model_copy(update={"rejected": ((candidate, reason),)})

    def outcome(fields: dict[str, FieldOutcome]) -> str:
        return assemble(schema, fields, site_id=SITE, canonical_url=URL, caller_supplied=True, unreadable=False)[0]

    assert assemble(
        schema, {**stating, "sku": address}, site_id=SITE, canonical_url=URL, caller_supplied=True, unreadable=False
    ) == ("no_match", None)
    assert outcome({**stating, "sku": _unpublished(), "gtin": _published()}) == "no_match"
    assert outcome({**stating, "sku": rejected("invalid")}) == "partial"
    assert outcome({**stating, "sku": rejected("not_owned")}) == "no_match"  # another entity's value (§8.2 rule 3)
    assert outcome(stating) == "extracted"


# Record confidence


# Listings (§4.10: one record per row, keyed by the row's URL)

LISTING_URL = "https://shop.example.test/c/widgets?page=2"


def _listing_schema() -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="l",
        page_kind="listing",
        fields={
            "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
            "url": FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url"),
            "heading": FieldSpec(type=FieldType.TEXT, description="d", scope="page"),
        },
    )


def _row(n: int | None, *, title: bool = True) -> dict[str, FieldOutcome]:
    return {
        "title": _published(f"Widget {n}") if title else _unpublished(),
        "url": _published(f"https://shop.example.test/p/{n}") if n is not None else _unpublished(),
    }


PAGE_FIELDS = {"heading": _published("All widgets")}


def _assemble_listing(*rows: dict[str, FieldOutcome], caller_supplied: bool = True) -> tuple[str, tuple[Any, ...]]:
    return assemble_listing(
        _listing_schema(), PAGE_FIELDS, rows, site_id=SITE, page_url=LISTING_URL, caller_supplied=caller_supplied
    )


def test_a_row_stating_no_row_value_keeps_no_record_though_the_page_fields_publish() -> None:
    schema = _listing_schema()
    heading = schema.fields["heading"].model_copy(update={"required": True})
    schema = schema.model_copy(update={"fields": {**schema.fields, "heading": heading}})
    rows = (_row(1), _row(None, title=False))

    outcome, records = assemble_listing(
        schema, PAGE_FIELDS, rows, site_id=SITE, page_url=LISTING_URL, caller_supplied=True
    )

    assert outcome == "partial"
    assert [r.data["title"] for r in records] == ["Widget 1"]


def test_each_row_is_a_record_keyed_by_its_url_with_the_page_fields() -> None:
    outcome, records = _assemble_listing(_row(1), _row(2))
    assert outcome == "extracted"
    assert [(r.entity_key, r.data, r.complete) for r in records] == [
        (
            entity_key(SITE, "https://shop.example.test/p/1"),
            {"title": "Widget 1", "url": "https://shop.example.test/p/1", "heading": "All widgets"},
            True,
        ),
        (
            entity_key(SITE, "https://shop.example.test/p/2"),
            {"title": "Widget 2", "url": "https://shop.example.test/p/2", "heading": "All widgets"},
            True,
        ),
    ]
    assert set(records[0].field_meta) == {"title", "url", "heading"}


def test_a_url_publishes_as_the_page_states_it_and_keys_its_record_canonically() -> None:
    row = {
        "title": _published("Widget 3"),
        "url": _published("https://shop.example.test/p/3").model_copy(update={"stated": "/p/3"}),
    }

    _, records = _assemble_listing(row)

    assert records[0].entity_key == entity_key(SITE, "https://shop.example.test/p/3")
    assert records[0].data["url"] == "/p/3"
