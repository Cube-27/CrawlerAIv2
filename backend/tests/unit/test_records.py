"""Records (SPEC-05 §4.10, ARCHITECTURE §6 `record`, §10 "Incomplete pages", INV-22): published values only in `data`,
`field_meta` for every field, `complete`, the entity key, `partial` for caller-supplied URLs and `no_match` with no
record for crawl-discovered ones."""

import hashlib
import uuid
from typing import Any

import pytest

from crawlerai.collect.base import Candidate
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SiteId
from crawlerai.normalize.base import Ok
from crawlerai.resolve.records import (
    FieldMeta,
    assemble,
    assemble_listing,
    entity_key,
    is_complete,
    record_confidence,
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
        version=1,
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


def test_field_meta_says_how_every_field_resolved() -> None:
    fields = {"sku": _published(), "gtin": _unpublished("conflict", "disagree"), "mpn": _unpublished()}

    _, record = assemble(_schema(), fields, site_id=SITE, canonical_url=URL, caller_supplied=True)

    assert record is not None
    assert record.field_meta == {
        "sku": FieldMeta(
            status="published",
            reason=None,
            evidence="structured",
            confidence=0.99,
            calibrated=True,
            source_kind="jsonld",
            locator=LOCATOR,
            derived_by=None,
        ),
        "gtin": FieldMeta(
            status="conflict",
            reason="disagree",
            evidence=None,
            confidence=None,
            calibrated=False,
            source_kind=None,
            locator=None,
            derived_by=None,
        ),
        "mpn": FieldMeta(
            status="missing",
            reason="no_candidates",
            evidence=None,
            confidence=None,
            calibrated=False,
            source_kind=None,
            locator=None,
            derived_by=None,
        ),
    }


def test_an_incomplete_caller_supplied_page_is_partial_with_its_record() -> None:
    fields = {"sku": _unpublished(), "gtin": _published(), "mpn": _unpublished()}

    outcome, record = assemble(_schema(), fields, site_id=SITE, canonical_url=URL, caller_supplied=True)

    assert outcome == "partial"
    assert record is not None
    assert (record.complete, record.data) == (False, {"gtin": "A-1"})


def test_an_incomplete_crawl_discovered_page_is_no_match_without_a_record() -> None:
    fields = {"sku": _unpublished(), "gtin": _published(), "mpn": _unpublished()}

    assert assemble(_schema(), fields, site_id=SITE, canonical_url=URL, caller_supplied=False) == ("no_match", None)


@pytest.mark.parametrize(
    ("gtin", "mpn", "complete"),
    [(True, False, True), (False, False, False)],
)
def test_a_required_group_needs_one_published_member(gtin: bool, mpn: bool, complete: bool) -> None:
    fields = {
        "sku": _published(),
        "gtin": _published() if gtin else _unpublished(),
        "mpn": _published() if mpn else _unpublished(),
    }
    assert is_complete(_schema([["gtin", "mpn"]]), fields) is complete


def test_an_abstained_required_field_makes_the_page_incomplete() -> None:
    fields = {"sku": _unpublished("abstained", "below_tau"), "gtin": _published(), "mpn": _published()}
    assert is_complete(_schema(), fields) is False


def test_outcomes_must_cover_exactly_the_schemas_fields() -> None:
    schema, fields = _schema(), {"sku": _published()}
    with pytest.raises(ValueError, match="do not match"):
        assemble(schema, fields, site_id=SITE, canonical_url=URL, caller_supplied=True)


def test_the_entity_key_hashes_the_site_and_the_canonical_url() -> None:
    expected = hashlib.sha256(f"{SITE}{URL}".encode()).hexdigest()
    assert entity_key(SITE, URL) == expected
    other_site = SiteId(uuid.UUID("01900000-0000-7000-8000-0000000000bb"))
    assert entity_key(other_site, URL) != expected
    assert entity_key(SITE, URL + "?v=2") != expected


# Record confidence (§10)


def test_record_confidence_is_the_minimum_over_required_published_fields() -> None:
    fields = {"sku": _published(confidence=0.99), "gtin": _published(confidence=0.975), "mpn": _unpublished()}
    # gtin and mpn are a required group; an optional field's confidence would not count.
    assert record_confidence(_schema([["gtin", "mpn"]]), fields) == 0.975


def test_an_optional_fields_confidence_does_not_count() -> None:
    fields = {"sku": _published(confidence=0.99), "gtin": _published(confidence=0.5), "mpn": _unpublished()}
    assert record_confidence(_schema(), fields) == 0.99


def test_record_confidence_is_empty_when_a_required_field_is_uncalibrated() -> None:
    fields = {
        "sku": _published(confidence=0.99),
        "gtin": _published(confidence=None, calibrated=False),
        "mpn": _unpublished(),
    }
    assert record_confidence(_schema([["gtin", "mpn"]]), fields) is None


def test_record_confidence_is_empty_when_no_required_field_published() -> None:
    fields = {"sku": _unpublished(), "gtin": _published(), "mpn": _unpublished()}
    assert record_confidence(_schema(), fields) is None


# Listings (§4.10: one record per row, keyed by the row's URL)

LISTING_URL = "https://shop.example.test/c/widgets?page=2"


def _listing_schema() -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="l",
        version=1,
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


def test_a_caller_supplied_listing_keeps_its_incomplete_rows() -> None:
    outcome, records = _assemble_listing(_row(1), _row(2, title=False))
    assert outcome == "partial"
    assert [r.complete for r in records] == [True, False]


def test_a_crawled_listing_drops_its_incomplete_rows() -> None:
    outcome, records = _assemble_listing(_row(1), _row(2, title=False), caller_supplied=False)
    assert outcome == "partial"
    assert [r.data["title"] for r in records] == ["Widget 1"]
    assert _assemble_listing(_row(2, title=False), caller_supplied=False) == ("no_match", ())


@pytest.mark.parametrize("caller_supplied", [True, False])
def test_a_listing_without_rows_is_no_match(caller_supplied: bool) -> None:
    assert _assemble_listing(caller_supplied=caller_supplied) == ("no_match", ())


def test_a_url_listed_twice_is_one_record() -> None:
    _, records = _assemble_listing(_row(1), _row(1))
    assert [r.entity_key for r in records] == [entity_key(SITE, "https://shop.example.test/p/1")]


def test_a_row_without_a_published_url_is_keyed_by_its_position_on_the_page() -> None:
    _, records = _assemble_listing(_row(1), _row(None), _row(None))
    assert [r.entity_key for r in records] == [
        entity_key(SITE, "https://shop.example.test/p/1"),
        entity_key(SITE, f"{LISTING_URL}#2"),
        entity_key(SITE, f"{LISTING_URL}#3"),
    ]
