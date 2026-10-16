"""Which fields induction leaves to synthesis or to a mapping (SPEC-08 §4.5)."""

from datetime import UTC, datetime

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.induction import Induction, Published, SamplePage, induce
from crawlerai.config_ir.model import XPathStep
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
VOCABULARY = Vocabulary({})
PAGE = ParsedPage("<html><body><h1>A title</h1></body></html>")


def _schema(page_kind: str = "detail") -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": SchemaId(uuid7()),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "page_kind": page_kind,
            "fields": {"title": {"type": "text", "description": "d"}},
        }
    )


def _induce(*locators: str | None, page_kind: str = "detail") -> Induction:
    sample = [
        SamplePage(PAGE, CTX, {} if locator is None else {"title": Published("A title", locator)})
        for locator in locators
    ]
    return induce(_schema(page_kind), sample, VOCABULARY)


def test_role_c_values_go_to_synthesis() -> None:
    assert _induce(*["text:0-7"] * 5).to_synthesize == {"title": "not_induced:text"}


def test_a_field_missing_on_one_sample_page_goes_to_synthesis() -> None:
    locators = ["microdata:/html[1]/body[1]/h1[1]"] * 4
    assert _induce(*locators, None).to_synthesize == {"title": "not_published_on_every_page"}


def test_locators_of_different_schemes_have_no_common_pattern() -> None:
    induced = _induce(*["microdata:/html[1]/body[1]/h1[1]"] * 4, "jsonld:0:$['name']")
    assert induced.to_synthesize == {"title": "no_common_pattern"}


def test_values_of_one_adapter_come_from_its_mapping() -> None:
    induced = _induce(*["adapter:board:$['title']"] * 5)
    assert (induced.fields, induced.mapped, induced.to_synthesize) == ({}, {"title": "adapter:board"}, {})


def test_values_of_two_adapters_have_no_common_pattern() -> None:
    induced = _induce(*["adapter:board:$['title']"] * 4, "adapter:other:$['title']")
    assert induced.to_synthesize == {"title": "no_common_pattern"}


def test_a_listing_is_left_to_synthesis() -> None:
    induced = _induce(*["microdata:/html[1]/body[1]/h1[1]"] * 5, page_kind="listing")
    assert induced.to_synthesize == {"title": "listing"}


def test_an_unanchored_element_has_no_verified_selector() -> None:
    induced = _induce(*["microdata:/html[1]/body[1]/h1[1]"] * 5)
    assert (induced.fields, induced.to_synthesize) == ({}, {"title": "no_verified_selector"})


def test_an_expression_of_an_earlier_config_is_kept_as_it_is() -> None:
    induced = _induce(*["config:title:0:normalize-space(//h1)"] * 5)
    assert induced.fields["title"].steps == [XPathStep(xpath="normalize-space(//h1)")]


def test_a_structural_dom_value_is_induced_like_a_microdata_element() -> None:
    induced = _induce(*["dom:/html[1]/body[1]/h1[1]"] * 5)
    assert (induced.fields, induced.to_synthesize) == ({}, {"title": "no_verified_selector"})
