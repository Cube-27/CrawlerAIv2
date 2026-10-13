"""Held-out facts from stored rows (SPEC-08 §4.7, §8.3 step 4): a detail page's published values are its record's,
and its references are the valid structured or adapter values of the entities that published; a listing's rows are
its records in stored order, with the page's fields split off and no references."""

from crawlerai.config_ir.held_out import StoredCandidate, StoredRecord, facts_of, published_of
from crawlerai.config_ir.induction import Published
from crawlerai.config_ir.validation import Facts
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

TEXT = FieldSpec(type=FieldType.TEXT, description="d")
PAGE_TEXT = FieldSpec(type=FieldType.TEXT, description="d", scope="page")


def _schema(page_kind: str, **fields: FieldSpec) -> SchemaDef:
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic", "version": 1}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields})


def test_a_detail_page_compares_with_the_structured_values_of_the_entities_that_published() -> None:
    schema = _schema("detail", title=TEXT, brand=TEXT)
    candidates = [
        StoredCandidate("p", "title", "Kettle", "jsonld", chosen=True),
        StoredCandidate("p", "title", "Kettle!", "microdata", chosen=False),
        StoredCandidate("page", "brand", "Acme", "og", chosen=True),
        # Not references: another entity's value, the config's own, the model's.
        StoredCandidate("related", "title", "Toaster", "jsonld", chosen=False),
        StoredCandidate("p", "title", "Kettle", "config", chosen=False),
        StoredCandidate("p", "brand", "Acme", "llm", chosen=False),
    ]

    facts, rows = facts_of(schema, [{"title": "Kettle", "brand": "Acme"}], candidates)

    assert facts == Facts(
        published={"title": "Kettle", "brand": "Acme"}, references={"title": ["Kettle", "Kettle!"], "brand": ["Acme"]}
    )
    assert rows == ()


def test_a_listing_splits_page_fields_from_rows_in_stored_order() -> None:
    schema = _schema("listing", name=TEXT, heading=PAGE_TEXT)
    records = [{"name": "A", "heading": "All"}, {"name": "B", "heading": "All"}]
    candidates = [StoredCandidate("row-0", "name", "A", "jsonld", chosen=True)]

    facts, rows = facts_of(schema, records, candidates)

    assert facts == Facts(published={"heading": "All"})
    assert rows == (Facts(published={"name": "A"}), Facts(published={"name": "B"}))


def test_a_page_without_records_has_no_facts() -> None:
    assert facts_of(_schema("detail", title=TEXT), [], []) == (Facts(), ())


def test_a_sample_page_reads_published_values_with_their_locators() -> None:
    schema = _schema("detail", title=TEXT, brand=TEXT, sku=TEXT)
    record = StoredRecord({"title": "Kettle", "brand": "Acme"}, {"title": "jsonld:0:$['name']", "sku": "x"})

    # A value stored without a locator is left out: induction and synthesis read where a value came from.
    assert published_of(schema, [record]) == ({"title": Published("Kettle", "jsonld:0:$['name']")}, ())


def test_a_listing_samples_its_page_fields_from_the_first_record_and_rows_from_each() -> None:
    schema = _schema("listing", name=TEXT, heading=PAGE_TEXT)
    records = [
        StoredRecord({"name": "A", "heading": "All"}, {"name": "text:0-1", "heading": "text:9-12"}),
        StoredRecord({"name": "B", "heading": "All"}, {"name": "text:4-5", "heading": "text:9-12"}),
    ]

    page, rows = published_of(schema, records)

    assert page == {"heading": Published("All", "text:9-12")}
    assert rows == ({"name": Published("A", "text:0-1")}, {"name": Published("B", "text:4-5")})
