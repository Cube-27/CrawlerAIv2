"""Preference (SPEC-05 §4.7, §4.8, ARCHITECTURE §8.2 rule 4, §10): which of a field's valid, owned candidates
publishes, and why every other one does not."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import (
    Chosen,
    PageFacts,
    Resolver,
    Unpublished,
    intent_ambiguous,
    load_precedence,
)
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
ORDERS = {t: ORDER for t in (FieldType.TEXT, FieldType.LONG_TEXT, FieldType.URL, FieldType.IMAGE_URL)}

PRODUCT = Entity(id="jsonld:0:$", kind="Product", urls=(), parent=None)
OFFER_A = Entity(id="jsonld:0:$['offers'][0]", kind="Offer", urls=(), parent=PRODUCT.id, via="offers")
OFFER_B = Entity(id="jsonld:0:$['offers'][1]", kind="Offer", urls=(), parent=PRODUCT.id, via="offers")
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", kind="Product", urls=(), parent=PRODUCT.id, via="isRelatedTo")
ENTITIES = (PRODUCT, OFFER_A, OFFER_B, RELATED)

TITLE = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name")
SKU = FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku")
PRICE = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")
AVAILABILITY = FieldSpec(
    type=FieldType.ENUM, vocab="schema:ItemAvailability", description="d", schema_org="Offer.availability"
)
IMAGES = FieldSpec(
    type=FieldType.LIST, description="d", schema_org="Product.image", item=FieldSpec(type=FieldType.IMAGE_URL)
)


def _schema(**fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        version=1,
        page_kind="detail",
        fields=fields,
    )


def _locator(entity_id: str, kind: SourceKind, n: int) -> str:
    if kind == "og":
        return f"meta:og:x{n}"
    if kind == "js_state":
        return f"js_state:/html[1]/body[1]/script[1]:$['x{n}']"
    return f"{entity_id}['x{n}']"


def _candidate(
    field: str,
    value: JsonValue,
    entity: Entity | str = PRODUCT,
    kind: SourceKind = "jsonld",
    *,
    raw: JsonValue = None,
    normalized: NormalizeResult | None = None,
    n: int = 0,
) -> Candidate:
    entity_id = entity if isinstance(entity, str) else entity.id
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind=kind,
        raw=value if raw is None else raw,
        normalized=normalized or Ok(value),
        locator=_locator(entity_id, kind, n),
        independent=True,
    )


def _resolver(
    *,
    target: Entity = PRODUCT,
    request_url: str = PAGE_URL,
    shown: tuple[str, ...] = (),
    entities: tuple[Entity, ...] = ENTITIES,
) -> Resolver:
    return Resolver(
        graph=EntityGraph.of(entities, VOCABULARY),
        target=target,
        page=PageFacts.of(request_url, lambda value: value in shown),
        orders=ORDERS,
    )


def _prefer(schema: SchemaDef, *candidates: Candidate, **kwargs: object) -> dict[str, Chosen | Unpublished]:
    return _resolver(**kwargs).prefer(schema, candidates)  # type: ignore[arg-type]


# Validity and ownership


def test_a_field_without_candidates_is_missing() -> None:
    assert _prefer(_schema(sku=SKU)) == {"sku": Unpublished("missing", "no_candidates", ())}


def test_candidates_that_decline_or_are_not_owned_never_publish() -> None:
    invalid = _candidate("sku", None, raw="", normalized=Invalid("empty"))
    ambiguous = _candidate("sku", None, raw="x", normalized=Ambiguous("two", ()), n=1)
    related = _candidate("sku", "R-1", RELATED)

    result = _prefer(_schema(sku=SKU), invalid, ambiguous, related)

    # The reason is the furthest stage a candidate reached: it was valid, but not the target's.
    assert result == {
        "sku": Unpublished(
            "missing", "not_owned", ((invalid, "invalid"), (ambiguous, "ambiguous"), (related, "not_owned"))
        )
    }


def test_only_the_valid_owned_candidate_publishes() -> None:
    invalid = _candidate("sku", None, raw="", normalized=Invalid("empty"))
    related = _candidate("sku", "R-1", RELATED)
    own = _candidate("sku", "A-1")

    result = _prefer(_schema(sku=SKU), invalid, related, own)

    assert result == {"sku": Chosen(own, (), ((invalid, "invalid"), (related, "not_owned")))}


def test_an_ambiguous_target_makes_every_field_a_conflict() -> None:
    title = _candidate("title", "Lamp")

    result = intent_ambiguous(_schema(title=TITLE, sku=SKU), [title])

    assert result == {
        "title": Unpublished("conflict", "intent_ambiguous", ((title, "intent_ambiguous"),)),
        "sku": Unpublished("conflict", "intent_ambiguous", ()),
    }


# Exact-match types (INV-14)


def test_agreeing_exact_candidates_publish_the_first_and_the_rest_agree() -> None:
    jsonld = _candidate("sku", "A-1")
    og = _candidate("sku", "A-1", PAGE, "og")

    assert _prefer(_schema(sku=SKU), jsonld, og)["sku"] == Chosen(jsonld, (og,), ())


def test_disagreeing_exact_candidates_are_a_conflict() -> None:
    jsonld = _candidate("sku", "A-1")
    og = _candidate("sku", "A-2", PAGE, "og")

    result = _prefer(_schema(sku=SKU), jsonld, og)

    assert result["sku"] == Unpublished("conflict", "disagree", ((jsonld, "disagree"), (og, "disagree")))


def test_exact_values_agree_by_the_types_equality() -> None:
    # GTIN-13 and GTIN-14 of one item are the same value (SPEC-04 §4.5, GS1).
    spec = FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin", description="d", schema_org="Product.gtin")
    short = _candidate("gtin", {"scheme": "gtin", "value": "4006381333931"})
    padded = _candidate("gtin", {"scheme": "gtin", "value": "04006381333931"}, PAGE, "og")

    assert _prefer(_schema(gtin=spec), short, padded)["gtin"] == Chosen(short, (padded,), ())


# Text, url and image_url: source precedence


def test_the_first_ranked_source_kind_wins_and_lower_ones_that_disagree_are_rejected() -> None:
    og = _candidate("title", "Lamp, the shop", PAGE, "og")
    jsonld = _candidate("title", "Lamp")
    og_same = _candidate("title", "Lamp", PAGE, "og", n=1)

    result = _prefer(_schema(title=TITLE), og, jsonld, og_same)

    assert result["title"] == Chosen(jsonld, (og_same,), ((og, "precedence"),))


def test_the_order_is_the_types_own() -> None:
    resolver = Resolver(
        graph=EntityGraph.of(ENTITIES, VOCABULARY),
        target=PRODUCT,
        page=PageFacts.of(PAGE_URL, lambda _: False),
        orders={**ORDERS, FieldType.TEXT: ("og", "jsonld")},
    )
    og = _candidate("title", "Lamp, the shop", PAGE, "og")
    jsonld = _candidate("title", "Lamp")

    assert resolver.prefer(_schema(title=TITLE), [jsonld, og])["title"] == Chosen(og, (), ((jsonld, "precedence"),))


def test_candidates_of_the_winning_kind_that_disagree_are_a_conflict() -> None:
    first = _candidate("title", "Lamp")
    second = _candidate("title", "Desk lamp", n=1)

    result = _prefer(_schema(title=TITLE), first, second)

    assert result["title"] == Unpublished("conflict", "disagree", ((first, "disagree"), (second, "disagree")))


def test_a_source_kind_outside_the_order_never_wins() -> None:
    state = _candidate("title", "Lamp", PAGE, "js_state")

    result = _prefer(_schema(title=TITLE), state)

    assert result["title"] == Unpublished("missing", "unranked", ((state, "unranked"),))


def test_an_unranked_kind_that_agrees_with_the_winner_is_agreeing() -> None:
    jsonld = _candidate("title", "Lamp")
    state = _candidate("title", "Lamp", PAGE, "js_state")

    assert _prefer(_schema(title=TITLE), state, jsonld)["title"] == Chosen(jsonld, (state,), ())


def test_a_list_field_follows_its_item_types_rule() -> None:
    # A list of image URLs takes the image_url order; disagreeing og images are rejected, not a conflict.
    jsonld = _candidate("images", ["https://shop.example.test/a.jpg"])
    og = _candidate("images", ["https://shop.example.test/b.jpg"], PAGE, "og")

    assert _prefer(_schema(images=IMAGES), og, jsonld)["images"] == Chosen(jsonld, (), ((og, "precedence"),))


# Atomic offers (INV-15)


def test_offer_fields_come_from_one_offer() -> None:
    price_a = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    price_b = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_B)
    stock_b = _candidate("availability", "InStock", OFFER_B)

    result = _prefer(_schema(price=PRICE, availability=AVAILABILITY), price_a, price_b, stock_b)

    # Offer B states both fields, so both come from it; A's equal price agrees.
    assert result == {
        "price": Chosen(price_b, (price_a,), ()),
        "availability": Chosen(stock_b, (), ()),
    }


def test_offers_that_disagree_are_a_conflict() -> None:
    price_a = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    price_b = _candidate("price", {"amount": "12.00", "currency": "USD"}, OFFER_B)

    result = _prefer(_schema(price=PRICE), price_a, price_b)

    assert result["price"] == Unpublished(
        "conflict", "offers_disagree", ((price_a, "offers_disagree"), (price_b, "offers_disagree"))
    )


def test_an_offer_field_the_chosen_offer_lacks_is_a_conflict() -> None:
    price_a = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    stock_b = _candidate("availability", "InStock", OFFER_B)

    result = _prefer(_schema(price=PRICE, availability=AVAILABILITY), price_a, stock_b)

    # Each Offer states one field; taking one from each would mix two offers.
    assert result == {
        "price": Chosen(price_a, (), ()),
        "availability": Unpublished("conflict", "offer_split", ((stock_b, "offer_split"),)),
    }


def test_a_page_level_price_beside_a_structured_offer_agrees_with_it() -> None:
    offer = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    og = _candidate("price", {"amount": "10.00", "currency": "USD"}, PAGE, "og")

    assert _prefer(_schema(price=PRICE), og, offer)["price"] == Chosen(offer, (og,), ())


def test_a_page_level_offer_value_does_not_join_a_structured_offer() -> None:
    og_price = _candidate("price", {"amount": "10.00", "currency": "USD"}, PAGE, "og")
    stock = _candidate("availability", "InStock", OFFER_A)

    result = _prefer(_schema(price=PRICE, availability=AVAILABILITY), og_price, stock)

    assert result["price"] == Unpublished("conflict", "offer_split", ((og_price, "offer_split"),))
    assert result["availability"] == Chosen(stock, (), ())


def test_an_aggregate_low_price_is_never_the_price() -> None:
    html = _jsonld_page(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Lamp",
            "offers": {"@type": "AggregateOffer", "lowPrice": "10.00", "highPrice": "20.00", "priceCurrency": "USD"},
        }
    )
    schema = _schema(title=TITLE, price=PRICE)
    collected = JsonLdCollector(VOCABULARY).collect(ParsedPage(html), schema, _CTX)
    graph = EntityGraph.of(collected.entities, VOCABULARY)
    product = next(e for e in collected.entities if e.kind == "Product")
    resolver = Resolver(graph=graph, target=product, page=PageFacts.of(PAGE_URL, lambda _: False), orders=ORDERS)

    result = resolver.prefer(schema, collected.candidates)

    assert isinstance(result["title"], Chosen)
    assert result["price"] == Unpublished("missing", "no_candidates", ())


_CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)


def _jsonld_page(document: object) -> str:
    return f'<html><head><script type="application/ld+json">{json.dumps(document)}</script></head></html>'


# URL parameters (INV-13)


def test_a_value_from_a_query_parameter_is_rejected_unless_shown() -> None:
    sku = _candidate("sku", "A-77")
    request_url = f"{PAGE_URL}?ref=A-77"

    hidden = _prefer(_schema(sku=SKU), sku, request_url=request_url)
    shown = _prefer(_schema(sku=SKU), sku, request_url=request_url, shown=("A-77",))

    assert hidden["sku"] == Unpublished("missing", "url_param", ((sku, "url_param"),))
    assert shown["sku"] == Chosen(sku, (), ())


def test_a_query_parameter_inside_an_object_value_is_rejected() -> None:
    # `Offer.price+priceCurrency` joins two values; a currency taken from the URL makes the price one too (C7).
    price = _candidate(
        "price", {"amount": "10.00", "currency": "EUR"}, OFFER_A, raw={"price": 10, "priceCurrency": "EUR"}
    )

    result = _prefer(_schema(price=PRICE), price, request_url=f"{PAGE_URL}?currency=EUR&qty=10")

    assert result["price"] == Unpublished("missing", "url_param", ((price, "url_param"),))


def test_query_values_are_form_decoded() -> None:
    # WHATWG URL Standard, application/x-www-form-urlencoded: `+` is a space and triplets decode.
    title = _candidate("title", "Desk Lamp")

    result = _prefer(_schema(title=TITLE), title, request_url=f"{PAGE_URL}?q=Desk+Lamp")

    assert result["title"] == Unpublished("missing", "url_param", ((title, "url_param"),))


def test_a_value_that_is_not_a_query_parameter_is_kept() -> None:
    sku = _candidate("sku", "A-77")

    assert _prefer(_schema(sku=SKU), sku, request_url=f"{PAGE_URL}?ref=A-78&q=")["sku"] == Chosen(sku, (), ())


# source_precedence.yaml


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "source_precedence.yaml"
    path.write_text(text, encoding="utf-8")
    return path


_FILE = """\
source_split: dev
eval_run_id: 0192f3c4-0000-7000-8000-000000000000
git_sha: 0123456789abcdef0123456789abcdef01234567
text: [adapter, jsonld, og]
long_text: [jsonld]
url: [jsonld, og]
image_url: [og, jsonld]
"""


def test_the_precedence_file_gives_one_order_per_type(tmp_path: Path) -> None:
    assert load_precedence(_write(tmp_path, _FILE)) == {
        FieldType.TEXT: ("adapter", "jsonld", "og"),
        FieldType.LONG_TEXT: ("jsonld",),
        FieldType.URL: ("jsonld", "og"),
        FieldType.IMAGE_URL: ("og", "jsonld"),
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (_FILE.replace("source_split: dev", "source_split: hidden"), "dev only"),
        (_FILE.replace("source_split: dev\n", ""), "dev only"),
        (_FILE.replace("long_text: [jsonld]\n", ""), "no order for long_text"),
        (_FILE.replace("[og, jsonld]", "[og, html]"), "unknown source kind"),
        (_FILE + "money: [jsonld]\n", "money"),
        (_FILE.replace("[jsonld, og]", "jsonld"), "not a list"),
        ("- text\n", "not a mapping"),
    ],
)
def test_a_precedence_file_that_is_wrong_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = _write(tmp_path, text)

    with pytest.raises(ValueError, match=message):
        load_precedence(path)
