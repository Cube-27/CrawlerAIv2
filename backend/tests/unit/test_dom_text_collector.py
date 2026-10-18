"""The DOM description collector (extraction spec, requirement "DOM description block"): the prose block of a detail
page that states a long_text field in full, found as the block that extends what another collector stated or as the
section a heading or an ARIA label names with the field's words, and, where only a summary is stated, the main text.
Pages are synthetic (`example.test`, C3, C9)."""

from datetime import UTC, datetime

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.dom_text import DescriptionCollector
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId, SourceKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL, html_lang="en")


def _field(type_: FieldType, path: str | None) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, "description": "d", "schema_org": path})


def _schema(page_kind: PageKind = "detail") -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields={
            "title": _field(FieldType.TEXT, "Product.name"),
            "description": _field(FieldType.LONG_TEXT, "Product.description"),
            "care": _field(FieldType.LONG_TEXT, None),
        },
    )


def _stated(kind: SourceKind, value: str, field: str = "description") -> Candidate:
    made = candidate(field, _schema().fields[field], PAGE, kind, value, format_locator("dom", "/html"), CTX, [])
    assert made is not None
    return made


def _read(body: str, *stated: Candidate, schema: SchemaDef | None = None) -> dict[str, str]:
    page = ParsedPage(f"<html><body>{body}</body></html>")
    result = DescriptionCollector().collect(page, schema or _schema(), CTX, stated)
    found = {}
    for c in result.candidates:
        assert (c.entity_id, c.source_kind, c.independent) == (PAGE, "dom", True)
        assert isinstance(c.normalized, Ok)
        assert isinstance(c.normalized.value, str)
        found[c.field] = c.normalized.value
    return found


SUMMARY = "A sturdy kettle for everyday use."
FIRST = "A sturdy kettle for everyday use. It boils a litre in two minutes."
SECOND = "The lid locks and the handle stays cool."


def test_block_extending_a_summary_is_the_description() -> None:
    body = f"<main><h1>Kettle</h1><div><p>{FIRST}</p><p>{SECOND}</p></div><button>Buy</button></main>"
    found = _read(body, _stated("og", SUMMARY))
    assert found == {"description": f"{FIRST}\n{SECOND}"}


def test_review_and_tangential_blocks_are_not_the_description() -> None:
    body = (
        "<main><h1>Kettle</h1>"
        f"<aside><p>{FIRST} Sold out.</p></aside>"
        f'<div itemprop="review"><p>{FIRST} Loved it.</p></div>'
        f"<dialog open><p>{FIRST} Close.</p></dialog>"
        f"<div><p>{FIRST}</p></div></main>"
    )
    assert _read(body, _stated("jsonld", SUMMARY)) == {"description": FIRST}


def test_main_text_stands_for_a_description_only_an_og_summary_states() -> None:
    body = (
        f"<main><h1>Kettle</h1><button>Buy</button><div><h2>Overview</h2><p>{FIRST}</p><p>{SECOND}</p></div>"
        "<p>Short note.</p></main>"
    )
    found = _read(body, _stated("og", "Shop kettles at our store."))
    assert found["description"] == f"{FIRST}\n{SECOND}"


def test_schema_without_long_text_reads_nothing() -> None:
    schema = SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind="detail",
        fields={"title": _field(FieldType.TEXT, "Product.name")},
    )
    assert _read(f"<main><p>{FIRST}</p></main>", schema=schema) == {}


def test_a_heading_naming_a_list_field_gives_the_items_of_its_section_lists() -> None:
    schema = _schema().model_copy(
        update={"fields": {"requirements": FieldSpec.model_validate({"type": "list", "item": {"type": "text"}})}}
    )
    body = "<main><h2>Requirements</h2><ul><li>Kettles</li><li>Tea <b>leaves</b></li></ul><h2>Other</h2><p>x</p></main>"
    page = ParsedPage(f"<html><body>{body}</body></html>")

    found = DescriptionCollector().collect(page, schema, CTX, ()).candidates

    assert [(c.field, c.normalized) for c in found] == [("requirements", Ok(["Kettles", "Tea leaves"]))]
    # Two sections that list different items under the field's heading leave it unread.
    twice = body.replace("</main>", "<h3>Requirements</h3><ol><li>Cups</li></ol></main>")
    assert DescriptionCollector().collect(ParsedPage(twice), schema, CTX, ()).candidates == ()
