"""Which fields induction leaves to synthesis or to a mapping (learning-configs spec)."""

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


def test_values_of_one_adapter_come_from_its_mapping() -> None:
    induced = _induce(*["adapter:board:$['title']"] * 5)
    assert (induced.fields, induced.mapped, induced.to_synthesize) == ({}, {"title": "adapter:board"}, {})


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
