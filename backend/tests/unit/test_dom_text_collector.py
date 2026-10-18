"""The DOM description collector (extraction spec, requirement "DOM description block"): the prose block of a detail
page that states a long_text field in full, found as the block that extends what another collector stated or as the
section a heading or an ARIA label names with the field's words, and, where only a summary is stated, the main text.
Pages are synthetic (`example.test`, C3, C9)."""

from datetime import UTC, datetime

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.dom_text import DescriptionCollector
from crawlerai.collect.locator import format_locator, parse_locator
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


def test_block_beginning_with_a_cut_value_extends_it() -> None:
    body = f"<main><div><p>{FIRST}</p><p>{SECOND}</p></div></main>"
    assert _read(body, _stated("jsonld", "A sturdy kettle for everyday use. It boils a…")) == {
        "description": f"{FIRST}\n{SECOND}"
    }


def test_block_equal_to_structured_value_is_that_value_and_no_more() -> None:
    body = f"<main><div><p>{FIRST}</p><p>{SECOND}</p><img src='/a.jpg' alt='a'></div></main>"
    assert _read(body, _stated("jsonld", FIRST)) == {"description": FIRST}


def test_outermost_block_of_an_og_summary_that_equals_a_paragraph() -> None:
    body = f"<main><div><p>{FIRST}</p><p>{SECOND}</p></div></main>"
    assert _read(body, _stated("og", FIRST)) == {"description": f"{FIRST}\n{SECOND}"}


def test_white_space_is_not_compared() -> None:
    body = f"<main><div><p>{FIRST}</p><p>{SECOND}</p></div></main>"
    joined = FIRST.replace(". ", ".") + SECOND
    assert _read(body, _stated("og", joined)) == {"description": f"{FIRST}\n{SECOND}"}


def test_candidate_locator_names_the_block() -> None:
    page = ParsedPage(f"<html><body><main><p>{FIRST}</p></main></body></html>")
    result = DescriptionCollector().collect(page, _schema(), CTX, [_stated("og", SUMMARY)])
    assert parse_locator(result.candidates[0].locator).scheme == "dom"


def test_review_and_tangential_blocks_are_not_the_description() -> None:
    body = (
        "<main><h1>Kettle</h1>"
        f"<aside><p>{FIRST} Sold out.</p></aside>"
        f'<div itemprop="review"><p>{FIRST} Loved it.</p></div>'
        f"<dialog open><p>{FIRST} Close.</p></dialog>"
        f"<div><p>{FIRST}</p></div></main>"
    )
    assert _read(body, _stated("jsonld", SUMMARY)) == {"description": FIRST}


def test_blocks_that_differ_are_ambiguous() -> None:
    body = f"<main><div><p>{SUMMARY} Version one.</p></div><div><p>{SUMMARY} Version two.</p></div></main>"
    assert _read(body, _stated("jsonld", SUMMARY)) == {}


def test_heading_names_a_section_by_the_fields_words() -> None:
    body = f"<main><h2>Description</h2><p>{FIRST}</p><p>{SECOND}</p><h2>Reviews</h2><p>Great.</p></main>"
    assert _read(body, _stated("jsonld", "x")) == {"description": f"{FIRST}\n{SECOND}"}


def test_heading_in_a_wrapper_names_the_wrappers_next_block() -> None:
    body = f"<main><div><h2>Description</h2></div><div><p>{FIRST}</p></div></main>"
    assert _read(body, _stated("jsonld", "x")) == {"description": FIRST}


def test_heading_naming_a_field_without_a_property_uses_the_field_name() -> None:
    body = f"<main><h3>Care</h3><p>{SECOND}</p></main>"
    assert _read(body, _stated("jsonld", "x")) == {"care": SECOND}


def test_heading_with_other_words_names_nothing() -> None:
    body = f"<main><h2>About this item</h2><p>{FIRST}</p></main>"
    assert _read(body, _stated("jsonld", "x")) == {}


def test_aria_label_names_a_section() -> None:
    body = f'<main><section aria-label="Description"><p>{FIRST}</p></section></main>'
    assert _read(body, _stated("jsonld", "x")) == {"description": FIRST}


def test_aria_labelledby_names_a_section_without_its_label() -> None:
    body = f'<main><section aria-labelledby="t"><span id="t">Description</span><p>{FIRST}</p></section></main>'
    assert _read(body, _stated("jsonld", "x")) == {"description": FIRST}


def test_section_with_a_table_or_form_is_not_prose() -> None:
    body = f"<main><h2>Description</h2><table><tr><td>{FIRST}</td></tr></table></main>"
    assert _read(body, _stated("jsonld", "x")) == {}


def test_main_text_stands_for_a_description_only_an_og_summary_states() -> None:
    body = (
        f"<main><h1>Kettle</h1><button>Buy</button><div><h2>Overview</h2><p>{FIRST}</p><p>{SECOND}</p></div>"
        "<p>Short note.</p></main>"
    )
    found = _read(body, _stated("og", "Shop kettles at our store."))
    assert found["description"] == f"{FIRST}\n{SECOND}"


def test_main_text_skips_a_run_of_links() -> None:
    links = "".join(f'<a href="/p/{i}">Another kettle model number {i} with a long name</a> ' for i in range(8))
    body = f"<main><button>Buy</button><div>{links}</div><div><p>{FIRST}</p></div></main>"
    assert _read(body, _stated("og", "Shop kettles.")) == {"description": FIRST}


def test_main_text_of_equal_blocks_is_ambiguous() -> None:
    body = f"<main><button>Buy</button><div><p>{FIRST}</p></div><div><p>{FIRST.upper()}</p></div></main>"
    assert _read(body, _stated("og", "Shop kettles.")) == {}


def test_main_text_is_not_read_beside_a_structured_description() -> None:
    body = f"<main><button>Buy</button><div><p>{FIRST}</p></div></main>"
    assert _read(body, _stated("jsonld", "Unrelated words entirely.")) == {}


def test_listing_and_json_pages_read_nothing() -> None:
    body = f"<main><p>{FIRST}</p></main>"
    assert _read(body, _stated("og", SUMMARY), schema=_schema("listing")) == {}
    page = ParsedPage(f"<html><body>{body}</body></html>", json_body=True)
    assert not DescriptionCollector().collect(page, _schema(), CTX, [_stated("og", SUMMARY)]).candidates


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


def test_a_title_is_not_the_main_text() -> None:
    body = "<main><h1>Synthetic Kettle</h1><button>Buy</button></main>"
    assert _read(body, _stated("og", "Shop kettles.")) == {}


def test_a_section_whose_content_is_not_prose_does_not_climb_to_the_next_block() -> None:
    body = (
        f'<main><section><h2>Description</h2><div><p>{FIRST}</p><img src="/a.jpg" alt="a"></div></section>'
        f"<p>{SECOND}</p></main>"
    )
    assert _read(body, _stated("jsonld", "x")) == {}


def test_a_value_ending_inside_a_word_does_not_begin_a_block() -> None:
    body = "<main><div><p>Newsletter signup and other notes for visitors.</p></div></main>"
    assert _read(body, _stated("jsonld", "New")) == {}


def test_a_heading_role_with_a_fallback_token_names_a_section() -> None:
    body = f'<main><div role="heading presentation">Description</div><p>{FIRST}</p></main>'
    assert _read(body, _stated("jsonld", "x")) == {"description": FIRST}


def test_aria_labelledby_may_name_several_elements() -> None:
    body = f'<main><section aria-labelledby="a missing"><span id="a">Description</span><p>{FIRST}</p></section></main>'
    assert _read(body, _stated("jsonld", "x")) == {"description": FIRST}


def test_review_marked_with_the_schema_iri_is_not_the_description() -> None:
    review = f'<div itemprop="https://schema.org/review"><p>{FIRST} Loved it.</p></div>'
    body = f"<main>{review}<div><p>{FIRST}</p></div></main>"
    assert _read(body, _stated("jsonld", SUMMARY)) == {"description": FIRST}


def test_a_value_cut_inside_a_word_by_an_ellipsis_begins_the_block() -> None:
    body = f"<main><div><p>{FIRST}</p><p>{SECOND}</p></div></main>"
    assert _read(body, _stated("jsonld", "A sturdy kettle for everyday us...")) == {"description": f"{FIRST}\n{SECOND}"}
