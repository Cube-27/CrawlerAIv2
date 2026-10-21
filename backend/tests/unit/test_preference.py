"""Preference (resolution spec, "Candidate score"): which of a field's valid, owned candidates publishes, and why every
other one does not."""

from pathlib import Path

from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Ambiguous, Invalid, NormalizeResult, Ok
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import (
    PRECEDENCE_TYPES,
    Chosen,
    Orders,
    PageFacts,
    Resolver,
    Unpublished,
)
from crawlerai.resolve.score import value_of
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


# Exact-match types


def test_exact_candidates_that_share_the_best_score_are_a_conflict() -> None:
    jsonld = _candidate("sku", "A-1")
    og = _candidate("sku", "A-2", PAGE, "og")

    result = _prefer(_schema(sku=SKU), jsonld, og)

    assert result["sku"] == Unpublished("conflict", "disagree", ((jsonld, "disagree"), (og, "disagree")), (jsonld, og))


def _place(text: str, locality: str | None = None, region: str | None = None) -> dict[str, JsonValue]:
    return {"text": text, "locality": locality, "region": region, "country": None, "remote_flag": None}


def test_a_list_of_places_publishes_every_member_its_sources_state() -> None:
    # Two places that both belong to the item are members, not rivals; a text naming a structured place's locality
    # states that place, and stands for it.
    places = FieldSpec(type=FieldType.LIST, item=FieldSpec(type=FieldType.LOCATION), description="d")
    brooklyn, austin = _place("Brooklyn, NY", "Brooklyn", "NY"), _place("Austin, TX", "Austin", "TX")
    jsonld = _candidate("places", [brooklyn, austin])
    dom = _candidate("places", [_place("New York City"), _place("Austin; Denver")], PAGE, "dom")

    chosen = _prefer(_schema(places=places), jsonld, dom)["places"]

    assert isinstance(chosen, Chosen)
    assert value_of(chosen.candidate) == [brooklyn, _place("Austin; Denver"), _place("New York City")]
    assert (chosen.rejected, chosen.flag) == ((), None)


def test_one_amount_in_two_currencies_publishes_with_its_currency_unknown() -> None:
    price = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")
    jsonld = _candidate("price", {"amount": "19.90", "currency": "EUR"})
    dom = _candidate("price", {"amount": "19.9", "currency": "USD"}, PAGE, "dom")

    chosen = _prefer(_schema(price=price), jsonld, dom)["price"]

    assert isinstance(chosen, Chosen)
    assert chosen.candidate.normalized == Ok({"amount": "19.90", "currency": None}, basis="unknown")


def test_amounts_that_differ_are_a_conflict_unless_a_role_explains_them() -> None:
    price = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")
    jsonld = _candidate("price", {"amount": "19.90", "currency": "EUR"})
    og = _candidate("price", {"amount": "21.00", "currency": "EUR"}, PAGE, "og", n=1)
    dom = _candidate("price", {"amount": "21.00", "currency": "EUR"}, PAGE, "dom", n=2)
    schema = _schema(price=price)

    # Two structured sources state other amounts: the same role, nothing says which is the product's.
    assert _prefer(schema, jsonld, og)["price"] == Unpublished(
        "conflict", "disagree", ((jsonld, "disagree"), (og, "disagree")), (jsonld, og)
    )
    # The rendered price beats stale structured data, which is recorded as the disagreement.
    chosen = _prefer(schema, jsonld, dom)["price"]
    assert isinstance(chosen, Chosen)
    assert (chosen.candidate, chosen.flag) == (dom, "disagree")


# Text, url and image_url: the source weight is the fitted order


def test_the_best_scored_value_wins_and_a_fragment_weighs_nothing() -> None:
    og = _candidate("title", "Lamp, the shop", PAGE, "og")
    jsonld = _candidate("title", "Lamp")
    og_same = _candidate("title", "Lamp", PAGE, "og", n=1)
    decorated = _candidate("title", "Lamp | The Shop", PAGE, "og", n=2)

    result = _prefer(_schema(title=TITLE), og, jsonld, og_same)
    fragment = _prefer(_schema(title=TITLE), decorated, jsonld)

    # The other value is outscored and flags the field; a decorated title is a fragment (`supersede`): it weighs 0,
    # so it neither wins nor flags it.
    assert result["title"] == Chosen(jsonld, (og_same,), ((og, "outscored"),), (og, jsonld, og_same), "disagree")
    assert fragment["title"] == Chosen(jsonld, (), ((decorated, "outscored"),), (decorated, jsonld))


IMAGE = FieldSpec(type=FieldType.IMAGE_URL, description="d", schema_org="Product.image")


def test_an_image_publishes_at_the_largest_rendition_any_source_states() -> None:
    file = "https://cdn.example.test/i/7/a.jpg?sw="
    microdata = _candidate("image", file + "71", kind="microdata")
    og = _candidate("image", file + "406", PAGE, "og", n=1)

    chosen = _prefer(_schema(image=IMAGE), microdata, og)["image"]

    assert isinstance(chosen, Chosen)
    assert (chosen.candidate, chosen.agreeing) == (og, (microdata,))


def test_images_that_tie_as_items_of_one_list_publish_its_first() -> None:
    first, second = (
        _candidate("image", f"https://cdn.example.test/i/{n}.jpg", n=n).model_copy(
            update={"locator": f"{PRODUCT.id}['image'][{n}]"}
        )
        for n in (0, 1)
    )

    chosen = _prefer(_schema(image=IMAGE), second, first)["image"]

    assert isinstance(chosen, Chosen)
    assert (chosen.candidate, chosen.rejected) == (first, ((second, "outscored"),))


DOM_ORDER: tuple[SourceKind, ...] = ("jsonld", "og", "dom")


# Atomic offers (INV-15)


def test_a_price_no_offer_states_publishes_from_the_targets_own_values_and_another_offer_s_is_flagged() -> None:
    price = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")
    availability = FieldSpec(
        type=FieldType.ENUM, vocab="schema:ItemAvailability", description="d", schema_org="Offer.availability"
    )
    stock = _candidate("availability", "InStock", OFFER_A)
    og = _candidate("price", {"amount": "6.75", "currency": "USD"}, PAGE, "og")
    other_offer = _candidate("price", {"amount": "6.75", "currency": "USD"}, OFFER_B)
    schema = _schema(price=price, availability=availability)

    result = _prefer(schema, stock, og)
    # Availability first in schema order: Offer A is the anchor, and only Offer B states the price.
    split = _prefer(_schema(availability=availability, price=price), stock, other_offer)

    assert result["price"] == Chosen(og, (), (), (og,))
    assert result["availability"] == Chosen(stock, (), (), (stock,))
    # A price only another Offer than the anchor states is not shown to be the target's: a conflict.
    assert split["price"] == Unpublished("conflict", "offer_split", ((other_offer, "offer_split"),), (other_offer,))


# URL parameters (INV-13)


# source_precedence.yaml
