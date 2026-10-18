"""Records (extraction spec, INV-22): published values only in `data`,
`field_meta` for every field, `complete`, the entity key, `partial` for caller-supplied URLs and `no_match` with no
record for crawl-discovered ones."""

import hashlib
import uuid
from typing import Any

from crawlerai.collect.base import Candidate
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SiteId
from crawlerai.normalize.base import Ok
from crawlerai.resolve.records import (
    assemble,
    assemble_listing,
    entity_key,
)
from crawlerai.resolve.types import FieldOutcome
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

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

    outcome, record = assemble(_schema(), fields, site_id=SITE, canonical_url=URL, caller_supplied=False)

    assert outcome == "extracted"
    assert record is not None
    assert record.complete is True
    assert record.data == {"sku": "A-1", "gtin": "4006381333931"}  # published fields only
    assert record.entity_key == hashlib.sha256(f"{SITE}{URL}".encode()).hexdigest()


# Record confidence (§10)


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
