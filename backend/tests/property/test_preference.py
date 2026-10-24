"""Preference and derivation: which of a field's valid, owned candidates
publishes, and why every other one does not; for any candidate set, an exact-match value publishes when its score is
the best alone and a shared best is a conflict, a query-parameter value publishes only when shown, a page's
offer fields but money come from one Offer and a price publishes only when no other amount contests it, and only a
missing field is derived."""

from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from snowcrawl.collect.base import PAGE, Candidate, Entity
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import SchemaId, SourceKind
from snowcrawl.normalize.base import Ambiguous, Basis, Context, Invalid, NormalizeResult, Ok
from snowcrawl.resolve.derive import Derived, fill
from snowcrawl.resolve.ownership import EntityGraph
from snowcrawl.resolve.preference import (
    PRECEDENCE_TYPES,
    Chosen,
    Orders,
    PageFacts,
    Preference,
    Resolver,
    Unpublished,
)
from snowcrawl.resolve.score import value_of
from snowcrawl.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
ORDERS = dict.fromkeys(PRECEDENCE_TYPES, ORDER)

PRODUCT = Entity(id="jsonld:0:$", types=("Product",), urls=(), parent=None)
OFFER_A = Entity(id="jsonld:0:$['offers'][0]", types=("Offer",), urls=(), parent=PRODUCT.id, via="offers")
OFFER_B = Entity(id="jsonld:0:$['offers'][1]", types=("Offer",), urls=(), parent=PRODUCT.id, via="offers")
OFFER_C = Entity(id="jsonld:0:$['offers'][2]", types=("Offer",), urls=(), parent=PRODUCT.id, via="offers")
OFFERS = (OFFER_A, OFFER_B, OFFER_C)
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", types=("Product",), urls=(), parent=PRODUCT.id, via="isRelatedTo")
ENTITIES = (PRODUCT, *OFFERS, RELATED)

TITLE = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name")
SKU = FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku")
PRICE = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")
AVAILABILITY = FieldSpec(
    type=FieldType.ENUM, vocab="schema:ItemAvailability", description="d", schema_org="Offer.availability"
)
URL = FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url")


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
    jsonld = _candidate("price", {"amount": "19.90", "currency": "EUR"})
    dom = _candidate("price", {"amount": "19.9", "currency": "USD"}, PAGE, "dom")

    chosen = _prefer(_schema(price=PRICE), jsonld, dom)["price"]

    assert isinstance(chosen, Chosen)
    assert chosen.candidate.normalized == Ok({"amount": "19.90", "currency": None}, basis="unknown")


def test_amounts_that_differ_are_a_conflict_unless_a_role_explains_them() -> None:
    jsonld = _candidate("price", {"amount": "19.90", "currency": "EUR"})
    og = _candidate("price", {"amount": "21.00", "currency": "EUR"}, PAGE, "og", n=1)
    dom = _candidate("price", {"amount": "21.00", "currency": "EUR"}, PAGE, "dom", n=2)
    schema = _schema(price=PRICE)

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


BRAND = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name")
_BRANDS = st.sampled_from(["Lumen", "Fall Edit", "Lumen Co"])


@given(_BRANDS, _BRANDS, st.sampled_from(["jsonld", "microdata", "og"]))
def test_a_fallback_fills_a_field_only_where_the_page_states_no_value(
    record: str, stated: str, kind: SourceKind
) -> None:
    fallback = _candidate("brand", record, kind="adapter").model_copy(update={"fallback": True})
    page = _candidate("brand", stated, PRODUCT if kind != "og" else PAGE, kind, n=1)
    decorated = _candidate("brand", f"{record} | Shop", PRODUCT, "jsonld", n=2)

    alone = _prefer(_schema(brand=BRAND), fallback)
    beside = _prefer(_schema(brand=BRAND), fallback, page)
    referenced = _prefer(_schema(brand=BRAND), fallback, decorated)

    # A platform's record weighs 0 beside a value the page states: it neither wins, agrees nor flags the field.
    assert alone["brand"] == Chosen(fallback, (), (), (fallback,))
    assert isinstance(chosen := beside["brand"], Chosen)
    assert (chosen.candidate, chosen.flag) == (page, None)
    # Nor is it the reference that makes a stated value a fragment.
    assert isinstance(fragment := referenced["brand"], Chosen)
    assert fragment.candidate == decorated


IMAGE = FieldSpec(type=FieldType.IMAGE_URL, description="d", schema_org="Product.image")


def test_an_image_publishes_at_the_largest_rendition_any_source_states() -> None:
    file = "https://cdn.example.test/i/7/a.jpg?sw="
    microdata = _candidate("image", file + "71", kind="microdata")
    og = _candidate("image", file + "406", PAGE, "og", n=1)

    chosen = _prefer(_schema(image=IMAGE), microdata, og)["image"]

    assert isinstance(chosen, Chosen)
    assert (chosen.candidate, chosen.agreeing) == (og, (microdata,))


def test_images_that_tie_as_items_of_one_list_publish_the_first_its_collector_reads() -> None:
    # A platform answer read as the shown variant's page shows it: its image first, wherever the array places it.
    first, second = (
        _candidate("image", f"https://cdn.example.test/i/{n}.jpg", n=n).model_copy(
            update={"locator": f"{PRODUCT.id}['image'][{n}]"}
        )
        for n in (3, 0)
    )

    chosen = _prefer(_schema(image=IMAGE), first, second)["image"]

    assert isinstance(chosen, Chosen)
    assert (chosen.candidate, chosen.rejected) == (first, ((second, "outscored"),))


# Atomic offers


def test_a_price_no_offer_states_publishes_from_the_targets_own_values_and_another_offer_s_is_flagged() -> None:
    stock = _candidate("availability", "InStock", OFFER_A)
    og = _candidate("price", {"amount": "6.75", "currency": "USD"}, PAGE, "og")
    other_offer = _candidate("price", {"amount": "6.75", "currency": "USD"}, OFFER_B)
    schema = _schema(price=PRICE, availability=AVAILABILITY)

    result = _prefer(schema, stock, og)
    # Availability first in schema order: Offer A is the anchor, and only Offer B states the price.
    split = _prefer(_schema(availability=AVAILABILITY, price=PRICE), stock, other_offer)

    assert result["price"] == Chosen(og, (), (), (og,))
    assert result["availability"] == Chosen(stock, (), (), (stock,))
    # A price only another Offer than the anchor states is not shown to be the target's: a conflict.
    assert split["price"] == Unpublished("conflict", "offer_split", ((other_offer, "offer_split"),), (other_offer,))


# Properties


_SKUS = st.sampled_from(["A-1", "A-2", "B-7"])
_SOURCES = st.sampled_from([(PRODUCT.id, "jsonld"), (PAGE, "og"), (PRODUCT.id, "adapter")])


@given(st.lists(st.tuples(_SKUS, _SOURCES), max_size=6))
def test_an_exact_value_publishes_when_the_most_source_kinds_state_it(
    drawn: list[tuple[str, tuple[str, SourceKind]]],
) -> None:
    # Every kind weighs 1 and every candidate is the target's, so the score is the share of kinds stating the value.
    candidates = [_candidate("sku", value, owner, kind, n=n) for n, (value, (owner, kind)) in enumerate(drawn)]

    result = _prefer(_schema(sku=SKU), *candidates)["sku"]

    kinds: dict[str, set[str]] = {}
    for value, (_, kind) in drawn:
        kinds.setdefault(value, set()).add(kind)
    most = max((len(k) for k in kinds.values()), default=0)
    best = [value for value, k in kinds.items() if len(k) == most]
    if not drawn:
        assert result == Unpublished("missing", "no_candidates", ())
    elif len(best) > 1:
        assert isinstance(result, Unpublished)
        assert (result.status, result.reason) == ("conflict", "disagree")
    else:
        assert isinstance(result, Chosen)
        assert result.candidate.normalized == Ok(best[0])
        assert result.flag == (None if len(kinds) == 1 else "disagree")


_PARAM = st.text(st.characters(categories=("L", "N")), min_size=1, max_size=8)


@given(_PARAM, st.booleans(), st.booleans())
def test_a_query_parameter_value_publishes_only_when_shown(value: str, in_query: bool, shown: bool) -> None:
    query = f"?p={value}" if in_query else "?p=other-value"
    resolver = _resolver(request_url=f"{PAGE_URL}{query}", shown=(value,) if shown else ())
    candidate = _candidate("sku", value)

    result = resolver.prefer(_schema(sku=SKU), [candidate])["sku"]

    if in_query and not shown:
        assert result == Unpublished("missing", "url_param", ((candidate, "url_param"),))
    else:
        assert result == Chosen(candidate, (), (), (candidate,))


_PRICES = st.sampled_from([{"amount": "10.00", "currency": "USD"}, {"amount": "12.00", "currency": "USD"}])
_STOCK = st.sampled_from(["InStock", "OutOfStock"])
_OFFER = st.tuples(st.none() | _PRICES, st.none() | _STOCK)


@given(st.lists(_OFFER, min_size=1, max_size=len(OFFERS)))
def test_offer_fields_but_money_publish_from_one_offer_and_a_price_only_when_its_amount_is_uncontested(
    offers: list[tuple[JsonValue, str | None]],
) -> None:
    candidates = _offer_candidates(offers)

    result = _prefer(_schema(price=PRICE, availability=AVAILABILITY), *candidates)

    published = {name: p for name, p in result.items() if isinstance(p, Chosen)}
    if len(offers) == 1:
        assert published.keys() == {c.field for c in candidates}
    # Offers that state other amounts, none of them the shown variant's, leave the price a conflict.
    amounts = {c.normalized.value["amount"] for c in candidates if c.field == "price"}  # type: ignore[union-attr,call-overload,index]
    if len(offers) == 1:
        assert ("price" in published) == bool(amounts)
    if len(amounts) > 1:
        assert "price" not in published
    # Availability is a variant's: it publishes only when every Offer that states it states the published value.
    if "availability" in published:
        stated = [c.normalized for c in candidates if c.field == "availability"]
        assert all(value == published["availability"].candidate.normalized for value in stated)


def _offer_candidates(offers: list[tuple[JsonValue, str | None]]) -> list[Candidate]:
    candidates = []
    for n, (offer, (price, stock)) in enumerate(zip(OFFERS, offers, strict=False)):
        if price is not None:
            candidates.append(_candidate("price", price, offer, n=2 * n))
        if stock is not None:
            candidates.append(_candidate("availability", stock, offer, n=2 * n + 1))
    return candidates


_PREFERENCES = st.one_of(
    st.builds(
        Unpublished,
        st.sampled_from(["missing", "conflict"]),
        st.sampled_from(["no_candidates", "disagree"]),
        st.just(()),
    ),
    st.just(_candidate("url", PAGE_URL)).map(lambda c: Chosen(c, (), (), (c,))),
)
_CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)


@given(_PREFERENCES, st.none() | st.just(f"{PAGE_URL}?v=2"), st.booleans())
def test_only_a_missing_field_is_derived(preference: Preference, canonical: str | None, page_url_field: bool) -> None:
    result = fill(URL, preference, (), _resolver(), _CTX, canonical_url=canonical, page_url_field=page_url_field)

    missing = isinstance(preference, Unpublished) and preference.status == "missing"
    if missing and page_url_field:
        assert isinstance(result, Derived)
        assert result.derived_by == ("final_url" if canonical is None else "canonical_link")
    else:
        assert result == preference


_SETTLED = st.sampled_from([None, "page", "locale", "url", "unknown"])


@given(st.lists(st.tuples(st.just("10.00"), _SETTLED), min_size=1, max_size=4))
def test_a_price_publishes_on_its_best_currency_evidence(drawn: list[tuple[str, Basis | None]]) -> None:
    # Normalization spec, money: the currency's evidence is the source weight; of equal weights, the first stated.
    candidates = []
    for n, (amount, basis) in enumerate(drawn):
        value: JsonValue = {"amount": amount, "currency": None if basis == "unknown" else "USD"}
        candidate = _candidate("price", value, PAGE, "og", n=n)
        candidates.append(candidate.model_copy(update={"normalized": Ok(value, basis=basis)}))

    result = _prefer(_schema(price=PRICE), *candidates)["price"]

    rank = [None, "page", "locale", "url", "unknown"]
    best = min(rank.index(b) for _, b in drawn)
    # Groups rank by their first member: the first candidate stating a best-evidence value, whatever its own evidence.
    amounts = {amount for amount, b in drawn if rank.index(b) == best}
    first = next(a for a, b in drawn if a in amounts and (b == "unknown") == (rank[best] == "unknown"))
    assert isinstance(result, Chosen)
    assert isinstance(result.candidate.normalized, Ok)
    assert rank.index(result.candidate.normalized.basis) == best
    assert result.candidate.normalized.value["amount"] == first  # type: ignore[call-overload,index]
    # Another amount, or the same amount without a currency, is another value: the field is flagged.
    assert result.flag == (None if len({(a, b == "unknown") for a, b in drawn}) == 1 else "disagree")
