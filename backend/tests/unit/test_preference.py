"""Preference (SPEC-05 §4.7, §4.8, ARCHITECTURE §8.2 rule 4, §10): which of a field's valid, owned candidates
publishes, and why every other one does not."""

import json
import time
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
    PRECEDENCE_TYPES,
    Chosen,
    Orders,
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
ORDERS = dict.fromkeys(PRECEDENCE_TYPES, ORDER)

PRODUCT = Entity(id="jsonld:0:$", types=("Product",), urls=(), parent=None)
OFFER_A = Entity(id="jsonld:0:$['offers'][0]", types=("Offer",), urls=(), parent=PRODUCT.id, via="offers")
OFFER_B = Entity(id="jsonld:0:$['offers'][1]", types=("Offer",), urls=(), parent=PRODUCT.id, via="offers")
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", types=("Product",), urls=(), parent=PRODUCT.id, via="isRelatedTo")
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
        page_kind="detail",
        fields=fields,
    )


def _locator(entity_id: str, kind: SourceKind, n: int) -> str:
    if kind == "og":
        return f"meta:og:x{n}"
    if kind == "js_state":
        return f"js_state:/html[1]/body[1]/script[1]:$['x{n}']"
    if kind == "dom":
        return f"dom:/html[1]/body[1]/img[{n + 1}]"
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
    orders: Orders = ORDERS,
) -> Resolver:
    return Resolver(
        graph=EntityGraph.of(entities, VOCABULARY),
        target=target,
        page=PageFacts.of(request_url, lambda value: value in shown),
        orders=orders,
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

    assert result == {"sku": Chosen(own, (), ((invalid, "invalid"), (related, "not_owned")), (own,))}


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

    assert _prefer(_schema(sku=SKU), jsonld, og)["sku"] == Chosen(jsonld, (og,), (), (jsonld, og))


def test_disagreeing_exact_candidates_are_a_conflict() -> None:
    jsonld = _candidate("sku", "A-1")
    og = _candidate("sku", "A-2", PAGE, "og")

    result = _prefer(_schema(sku=SKU), jsonld, og)

    assert result["sku"] == Unpublished("conflict", "disagree", ((jsonld, "disagree"), (og, "disagree")), (jsonld, og))


def test_exact_values_agree_by_the_types_equality() -> None:
    # GTIN-13 and GTIN-14 of one item are the same value (SPEC-04 §4.5, GS1).
    spec = FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin", description="d", schema_org="Product.gtin")
    short = _candidate("gtin", "4006381333931")
    padded = _candidate("gtin", "04006381333931", PAGE, "og")

    assert _prefer(_schema(gtin=spec), short, padded)["gtin"] == Chosen(short, (padded,), (), (short, padded))


# Text, url and image_url: source precedence


def test_the_first_ranked_source_kind_wins_and_lower_ones_that_disagree_are_rejected() -> None:
    og = _candidate("title", "Lamp, the shop", PAGE, "og")
    jsonld = _candidate("title", "Lamp")
    og_same = _candidate("title", "Lamp", PAGE, "og", n=1)

    result = _prefer(_schema(title=TITLE), og, jsonld, og_same)

    assert result["title"] == Chosen(jsonld, (og_same,), ((og, "precedence"),), (og, jsonld, og_same))


DOM_ORDER: tuple[SourceKind, ...] = ("jsonld", "og", "dom")
BODY = FieldSpec(type=FieldType.LONG_TEXT, description="d", schema_org="Product.description")
FULL_BODY = "The lamp has a steel base and a linen shade. It ships flat, assembles in a minute and takes any bulb."


def test_a_truncated_value_and_a_short_summary_yield_to_the_full_text_of_a_lower_kind() -> None:
    cut = _candidate("body", FULL_BODY[:45] + "\u2026")
    summary = _candidate("body", "Buy lamps at Example Shop.", PAGE, "og")
    full = _candidate("body", FULL_BODY, PAGE, "dom")

    result = _prefer(_schema(body=BODY), cut, summary, full, orders=dict.fromkeys(PRECEDENCE_TYPES, DOM_ORDER))

    assert result["body"] == Chosen(full, (), ((cut, "precedence"), (summary, "precedence")), (cut, summary, full))


def test_a_decorated_title_yields_to_another_kinds_clean_one_and_both_stay_kept() -> None:
    decorated = _candidate("title", "Desk Lamp | Example Shop")
    clean = _candidate("title", "Desk Lamp", PAGE, "dom")

    result = _prefer(_schema(title=TITLE), decorated, clean, orders=dict.fromkeys(PRECEDENCE_TYPES, DOM_ORDER))

    assert result["title"] == Chosen(clean, (), ((decorated, "precedence"),), (decorated, clean))


def test_the_order_is_the_types_own() -> None:
    resolver = _resolver(orders={**ORDERS, FieldType.TEXT: ("og", "jsonld")})
    og = _candidate("title", "Lamp, the shop", PAGE, "og")
    jsonld = _candidate("title", "Lamp")

    assert resolver.prefer(_schema(title=TITLE), [jsonld, og])["title"] == Chosen(
        og, (), ((jsonld, "precedence"),), (jsonld, og)
    )


def test_candidates_of_the_winning_kind_that_disagree_are_a_conflict() -> None:
    first = _candidate("title", "Lamp")
    second = _candidate("title", "Desk lamp", n=1)

    result = _prefer(_schema(title=TITLE), first, second)

    assert result["title"] == Unpublished(
        "conflict", "disagree", ((first, "disagree"), (second, "disagree")), (first, second)
    )


IMAGE = FieldSpec(type=FieldType.IMAGE_URL, description="d", schema_org="Product.image")
_GALLERY = ("https://shop.example.test/a.jpg", "https://shop.example.test/b.jpg", "https://shop.example.test/c.jpg")


def test_an_independent_lower_kind_selects_one_value_of_an_entity_s_several() -> None:
    # Product.image with three values gives a scalar image field three candidates of one entity; og:image names the
    # second, so that one publishes, agreed by the og value.
    gallery = [_candidate("image", url, n=i) for i, url in enumerate(_GALLERY)]
    og = _candidate("image", _GALLERY[1], PAGE, "og")

    result = _prefer(_schema(image=IMAGE), *gallery, og)

    assert result["image"] == Chosen(
        gallery[1], (og,), ((gallery[0], "precedence"), (gallery[2], "precedence")), (*gallery, og)
    )


@pytest.mark.parametrize(
    ("members", "og", "published"),
    [
        pytest.param(("a.jpg?w=1000", "b.jpg?w=1000"), "a.jpg?w=1200&h=630", "a.jpg?w=1000", id="another-rendition"),
        pytest.param(("a.jpg?w=1", "a.jpg?w=2", "b.jpg"), "a.jpg?w=2", "a.jpg?w=2", id="equal-before-rendition"),
        pytest.param(("a.jpg?w=1", "a.jpg?w=2", "b.jpg"), "a.jpg?w=3", "a.jpg?w=1", id="two-renditions-named"),
    ],
)
def test_a_value_naming_the_same_resource_selects_it_when_none_is_equal(
    members: tuple[str, ...], og: str, published: str | None
) -> None:
    # `og:image` is often another rendition (size, crop) of one of the JSON-LD images: same path, another query.
    base = "https://cdn.example.test/i/"
    gallery = [_candidate("image", base + m, n=i) for i, m in enumerate(members)]

    result = _prefer(_schema(image=IMAGE), *gallery, _candidate("image", base + og, PAGE, "og"))["image"]

    if published is None:
        assert isinstance(result, Unpublished)
    else:
        assert isinstance(result, Chosen)
        assert result.candidate.normalized == Ok(base + published)


@pytest.mark.parametrize(
    "others",
    [
        pytest.param([_candidate("image", "https://shop.example.test/z.jpg", PAGE, "og")], id="names-none"),
        pytest.param(
            [_candidate("image", _GALLERY[0], PAGE, "og"), _candidate("image", _GALLERY[1], PAGE, "og", n=1)],
            id="names-two",
        ),
        pytest.param(
            [_candidate("image", _GALLERY[0], PAGE, "js_state").model_copy(update={"independent": False})],
            id="not-independent",
        ),
        pytest.param(
            [_candidate("image", _GALLERY[2], OFFER_A, n=9), _candidate("image", _GALLERY[0], PAGE, "og")],
            id="two-entities",
        ),
    ],
)
def test_several_values_stay_a_conflict_unless_one_independent_value_names_one(others: list[Candidate]) -> None:
    gallery = [_candidate("image", url, n=i) for i, url in enumerate(_GALLERY[:2])]

    result = _prefer(_schema(image=IMAGE), *gallery, *others)

    assert isinstance(result["image"], Unpublished)
    assert (result["image"].status, result["image"].reason) == ("conflict", "disagree")


def test_a_value_over_another_scheme_names_the_same_file() -> None:
    # RFC 3986 §3.2-§3.3: `og:image` over http names the file the JSON-LD gallery states over https.
    gallery = [_candidate("image", url, n=i) for i, url in enumerate(_GALLERY[:2])]
    og = _candidate("image", _GALLERY[1].replace("https:", "http:"), PAGE, "og")

    result = _prefer(_schema(image=IMAGE), *gallery, og)["image"]

    assert isinstance(result, Chosen)
    assert result.candidate is gallery[1]


def test_the_first_kind_in_the_order_that_names_a_value_selects_it() -> None:
    # og:image names the second gallery image in another rendition, and a DOM image the first one exactly: Open Graph
    # ranks before the DOM, so its naming decides.
    gallery = [_candidate("image", url, n=i) for i, url in enumerate(_GALLERY[:2])]
    og = _candidate("image", f"{_GALLERY[1]}?w=1200", PAGE, "og")
    dom = _candidate("image", _GALLERY[0], PAGE, "dom")
    resolver = _resolver(orders={**ORDERS, FieldType.IMAGE_URL: ("jsonld", "og", "dom")})

    result = resolver.prefer(_schema(image=IMAGE), [*gallery, og, dom])["image"]

    assert isinstance(result, Chosen)
    assert result.candidate is gallery[1]


def test_renditions_of_one_image_agree() -> None:
    # The same file in two sizes, as two merged JSON-LD blocks state it: one image, so the first publishes.
    renditions = [_candidate("image", f"{_GALLERY[0]}?width={w}", n=w) for w in (2000, 480)]

    result = _prefer(_schema(image=IMAGE), *renditions)["image"]

    assert isinstance(result, Chosen)
    assert result.candidate is renditions[0]


@pytest.mark.parametrize(
    ("second", "published"),
    [
        pytest.param(["b.jpg?w=2", "a.jpg?w=2"], 0, id="same-files"),
        pytest.param(["a.jpg?w=2", "c.jpg?w=2"], None, id="other-files"),
    ],
)
def test_lists_naming_the_same_files_agree(second: list[str], published: int | None) -> None:
    base = "https://cdn.example.test/i/"
    lists = [
        _candidate("images", [base + "a.jpg?w=1", base + "b.jpg?w=1"]),
        _candidate("images", [base + name for name in second], n=1),
    ]

    result = _prefer(_schema(images=IMAGES), *lists)["images"]

    if published is None:
        assert isinstance(result, Unpublished)
    else:
        assert isinstance(result, Chosen)
        assert result.candidate is lists[published]


def test_a_list_names_the_list_of_the_same_files() -> None:
    base = "https://cdn.example.test/i/"
    lists = [_candidate("images", [base + "a.jpg?w=1"]), _candidate("images", [base + "a_450x450.jpg"], n=1)]
    og = _candidate("images", ["http://cdn.example.test/i/a.jpg"], PAGE, "og")

    result = _prefer(_schema(images=IMAGES), *lists, og)["images"]

    assert isinstance(result, Chosen)
    assert result.candidate is lists[0]


def test_a_list_stating_one_file_in_two_renditions_names_that_file_once() -> None:
    # Two merged blocks: one lists the image once, the other in two sizes. Both name one file, so they agree and the
    # first publishes.
    base = "https://cdn.example.test/i/a.jpg"
    lists = [_candidate("images", [f"{base}?w=1"]), _candidate("images", [f"{base}?w=800", f"{base}?w=400"], n=1)]

    result = _prefer(_schema(images=IMAGES), *lists)["images"]

    assert isinstance(result, Chosen)
    assert result.candidate is lists[0]


@pytest.mark.parametrize("field", ["image", "images"])
def test_the_https_rendition_of_one_file_publishes_over_its_http_twin(field: str) -> None:
    secure = _GALLERY[0]
    plain = secure.replace("https:", "http:")
    renditions = [_candidate(field, [v] if field == "images" else v, n=i) for i, v in enumerate((plain, secure))]

    result = _prefer(_schema(image=IMAGE, images=IMAGES), *renditions)[field]

    assert isinstance(result, Chosen)
    assert result.candidate is renditions[1]


def test_a_rendition_another_kind_states_agrees_with_the_published_image() -> None:
    # og:image over http names the JSON-LD image's file: the two kinds agree on one image (evidence `agreed`).
    jsonld = _candidate("image", _GALLERY[0])
    og = _candidate("image", _GALLERY[0].replace("https:", "http:") + "?w=1200", PAGE, "og")

    result = _prefer(_schema(image=IMAGE), jsonld, og)["image"]

    assert isinstance(result, Chosen)
    assert (result.candidate, result.agreeing) == (jsonld, (og,))


def test_a_source_kind_outside_the_order_never_wins() -> None:
    state = _candidate("title", "Lamp", PAGE, "js_state")

    result = _prefer(_schema(title=TITLE), state)

    assert result["title"] == Unpublished("missing", "unranked", ((state, "unranked"),), (state,))


def test_an_unranked_kind_that_agrees_with_the_winner_is_agreeing() -> None:
    jsonld = _candidate("title", "Lamp")
    state = _candidate("title", "Lamp", PAGE, "js_state")

    assert _prefer(_schema(title=TITLE), state, jsonld)["title"] == Chosen(jsonld, (state,), (), (state, jsonld))


def test_a_list_field_follows_its_item_types_rule() -> None:
    # A list of image URLs takes the image_url order; disagreeing og images are rejected, not a conflict.
    jsonld = _candidate("images", ["https://shop.example.test/a.jpg"])
    og = _candidate("images", ["https://shop.example.test/b.jpg"], PAGE, "og")

    assert _prefer(_schema(images=IMAGES), og, jsonld)["images"] == Chosen(
        jsonld, (), ((og, "precedence"),), (og, jsonld)
    )


# Atomic offers (INV-15)


def test_offer_fields_come_from_one_offer() -> None:
    price_a = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    price_b = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_B)
    stock_b = _candidate("availability", "InStock", OFFER_B)

    result = _prefer(_schema(price=PRICE, availability=AVAILABILITY), price_a, price_b, stock_b)

    # Offer B states both fields, so both come from it; A's equal price agrees.
    assert result == {
        "price": Chosen(price_b, (price_a,), (), (price_a, price_b)),
        "availability": Chosen(stock_b, (), (), (stock_b,)),
    }


def test_offers_that_disagree_are_a_conflict() -> None:
    price_a = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    price_b = _candidate("price", {"amount": "12.00", "currency": "USD"}, OFFER_B)

    result = _prefer(_schema(price=PRICE), price_a, price_b)

    assert result["price"] == Unpublished(
        "conflict", "offers_disagree", ((price_a, "offers_disagree"), (price_b, "offers_disagree")), (price_a, price_b)
    )


def test_an_offer_field_the_chosen_offer_lacks_is_a_conflict() -> None:
    price_a = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    stock_b = _candidate("availability", "InStock", OFFER_B)

    result = _prefer(_schema(price=PRICE, availability=AVAILABILITY), price_a, stock_b)

    # Each Offer states one field; taking one from each would mix two offers.
    assert result == {
        "price": Chosen(price_a, (), (), (price_a,)),
        "availability": Unpublished("conflict", "offer_split", ((stock_b, "offer_split"),), (stock_b,)),
    }


def test_a_page_level_price_beside_a_structured_offer_agrees_with_it() -> None:
    offer = _candidate("price", {"amount": "10.00", "currency": "USD"}, OFFER_A)
    og = _candidate("price", {"amount": "10.00", "currency": "USD"}, PAGE, "og")

    assert _prefer(_schema(price=PRICE), og, offer)["price"] == Chosen(offer, (og,), (), (og, offer))


def test_a_page_level_offer_value_does_not_join_a_structured_offer() -> None:
    og_price = _candidate("price", {"amount": "10.00", "currency": "USD"}, PAGE, "og")
    stock = _candidate("availability", "InStock", OFFER_A)

    result = _prefer(_schema(price=PRICE, availability=AVAILABILITY), og_price, stock)

    assert result["price"] == Unpublished("conflict", "offer_split", ((og_price, "offer_split"),), (og_price,))
    assert result["availability"] == Chosen(stock, (), (), (stock,))


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
    product = next(e for e in collected.entities if e.types == ("Product",))
    resolver = Resolver(graph=graph, target=product, page=PageFacts.of(PAGE_URL, lambda _: False), orders=ORDERS)

    result = resolver.prefer(schema, collected.candidates)

    title = result["title"]
    assert isinstance(title, Chosen)
    assert title.candidate.normalized == Ok("Lamp")
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
    assert shown["sku"] == Chosen(sku, (), (), (sku,))


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

    assert _prefer(_schema(sku=SKU), sku, request_url=f"{PAGE_URL}?ref=A-78&q=")["sku"] == Chosen(sku, (), (), (sku,))


# source_precedence.yaml


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "source_precedence.yaml"
    path.write_text(text, encoding="utf-8")
    return path


_FILE = """\
source_split: dev
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


def test_thousands_of_agreeing_candidates_resolve_without_comparing_every_pair() -> None:
    # 6,000 equal prices over 80 Offers: about 18 million pairs if each were compared with each.
    offers = [
        Entity(id=f"jsonld:0:$['offers'][{i}]", types=("Offer",), urls=(), parent="jsonld:0:$", via="offers")
        for i in range(80)
    ]
    product = Entity(id="jsonld:0:$", types=("Product",), urls=(), parent=None)
    price: JsonValue = {"amount": "10.00", "currency": "USD"}
    candidates = [
        Candidate(
            field="price",
            entity_id=offers[n % len(offers)].id,
            source_kind="jsonld",
            raw=price,
            normalized=Ok(price),
            locator=f"{offers[n % len(offers)].id}['price'][{n}]",
            independent=True,
        )
        for n in range(6000)
    ]
    resolver = Resolver(EntityGraph.of((product, *offers), VOCABULARY), product, PageFacts.of(PAGE_URL, bool), ORDERS)
    spec = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")

    started = time.perf_counter()
    result = resolver.prefer_fields({"price": spec}, candidates)["price"]
    elapsed = time.perf_counter() - started

    assert isinstance(result, Chosen)
    assert result.candidate.normalized == Ok(price)
    assert elapsed < 5.0
