"""Which fields induction leaves to synthesis or to a mapping (SPEC-08 §4.5)."""

from datetime import UTC, datetime
from pathlib import Path

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.induction import Induction, Published, SamplePage, induce
from crawlerai.config_ir.model import JsonLdStep, JsonPathStep, XPathStep
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


ANCHORED = ParsedPage(
    "<html><head><meta property='og:title' content='A title'></head><body><p>Shop</p>"
    "<h1 id='t'>A title</h1><script id='state' type='application/json'>{\"item\": {\"title\": \"A title\"}}</script>"
    "</body></html>"
)
SPAN = ANCHORED.cleaned_text.text.index("A title")
TEXT_LOCATOR = f"text:{SPAN}-{SPAN + len('A title')}"


def _induce_on(page: ParsedPage, *locators: str) -> Induction:
    sample = [SamplePage(page, CTX, {"title": Published("A title", locator)}) for locator in locators]
    return induce(_schema(), sample, VOCABULARY)


def test_a_role_c_span_is_induced_through_the_element_that_holds_it() -> None:
    induced = _induce_on(ANCHORED, *[TEXT_LOCATOR] * 3)
    assert induced.fields["title"].steps == [XPathStep(xpath="normalize-space(//h1[@id='t'])")]


def test_a_role_c_span_on_one_page_and_a_dom_value_on_another_share_a_selector() -> None:
    induced = _induce_on(ANCHORED, TEXT_LOCATOR, "dom:/html/body/h1", TEXT_LOCATOR)
    assert induced.fields["title"].steps == [XPathStep(xpath="normalize-space(//h1[@id='t'])")]


def test_a_span_no_element_holds_alone_has_no_verified_selector() -> None:
    whole = f"text:0-{len(ANCHORED.cleaned_text.text)}"
    assert _induce_on(ANCHORED, *[whole] * 3).to_synthesize == {"title": "no_verified_selector"}


def test_a_meta_value_is_read_from_its_content() -> None:
    induced = _induce_on(ANCHORED, *["meta:og:title"] * 3)
    assert induced.fields["title"].steps == [XPathStep(xpath="//meta[@property='og:title']/@content")]


def test_a_field_missing_on_one_sample_page_goes_to_synthesis() -> None:
    locators = ["microdata:/html[1]/body[1]/h1[1]"] * 4
    assert _induce(*locators, None).to_synthesize == {"title": "not_published_on_every_page"}


def test_locators_proposing_no_common_step_have_no_verified_selector() -> None:
    induced = _induce(*["microdata:/html[1]/body[1]/h1[1]"] * 4, "jsonld:0:$['name']")
    assert induced.to_synthesize == {"title": "no_verified_selector"}


def test_values_of_one_adapter_come_from_its_mapping() -> None:
    induced = _induce(*["adapter:board:$['title']"] * 5)
    assert (induced.fields, induced.mapped, induced.to_synthesize) == ({}, {"title": "adapter:board"}, {})


def test_values_of_two_adapters_have_no_common_pattern() -> None:
    induced = _induce(*["adapter:board:$['title']"] * 4, "adapter:other:$['title']")
    assert induced.to_synthesize == {"title": "no_common_pattern"}


def test_a_listings_row_fields_are_left_to_listing_induction() -> None:
    assert _induce(*["microdata:/html[1]/body[1]/h1[1]"] * 5, page_kind="listing") == Induction()


def test_an_unanchored_element_has_no_verified_selector() -> None:
    induced = _induce(*["microdata:/html[1]/body[1]/h1[1]"] * 5)
    assert (induced.fields, induced.to_synthesize) == ({}, {"title": "no_verified_selector"})


def test_an_expression_of_an_earlier_config_is_kept_as_it_is() -> None:
    induced = _induce(*["config:title:0:normalize-space(//h1)"] * 5)
    assert induced.fields["title"].steps == [XPathStep(xpath="normalize-space(//h1)")]


def test_a_structural_dom_value_is_induced_like_a_microdata_element() -> None:
    induced = _induce(*["dom:/html[1]/body[1]/h1[1]"] * 5)
    assert (induced.fields, induced.to_synthesize) == ({}, {"title": "no_verified_selector"})


def test_an_embedded_state_value_is_read_by_its_path_over_the_pages_state_documents() -> None:
    induced = _induce_on(ANCHORED, *["js_state:/html[1]/body[1]/script[1]:$['item']['title']"] * 3)
    assert induced.fields["title"].steps == [JsonPathStep(jsonpath="$['item']['title']", source="js_state")]


SCHEMA_ORG = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
MONEY = SchemaDef.model_validate(
    {
        "id": SchemaId(uuid7()),
        "origin": "user",
        "status": "active",
        "name": "synthetic_money",
        "page_kind": "detail",
        "fields": {"price": {"type": "money", "description": "d", "schema_org": "Offer.price+priceCurrency"}},
    }
)


def _offer_page(n: int) -> SamplePage:
    node = (
        '{"@context": "https://schema.org", "@type": "Product", "name": "K",'
        f' "offers": [{{"price": "{n}.50", "priceCurrency": "EUR"}}]}}'
    )
    page = ParsedPage(f'<html><head><script type="application/ld+json">{node}</script></head><body></body></html>')
    published = Published({"amount": f"{n}.50", "currency": "EUR"}, "jsonld:0:$['offers'][0]['price']")
    return SamplePage(page, CTX, {"price": published})


def test_a_composite_value_located_at_one_member_is_read_from_the_object_holding_it() -> None:
    # `Offer.price+priceCurrency`: the price alone has no currency, the offer holding it has both.
    induced = induce(MONEY, [_offer_page(n) for n in range(1, 4)], SCHEMA_ORG)
    assert induced.fields["price"].steps == [JsonLdStep(jsonld="$['offers'][*]", when_type="Product")]
