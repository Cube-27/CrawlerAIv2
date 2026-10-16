"""Preference and derivation properties (SPEC-05 §4.7, §4.8): for any candidate set, exact-match values publish only
when all agree (INV-14), a query-parameter value publishes only when shown (INV-13), a page's offer fields come
from one Offer (INV-15), and only a missing field is derived (INV-07)."""

from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.resolve.derive import Derived, fill
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import PRECEDENCE_TYPES, Chosen, PageFacts, Preference, Resolver, Unpublished
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
ORDERS = dict.fromkeys(PRECEDENCE_TYPES, ORDER)
PRODUCT = Entity(id="jsonld:0:$", types=("Product",), urls=(), parent=None)
OFFERS = tuple(
    Entity(id=f"jsonld:0:$['offers'][{i}]", types=("Offer",), urls=(), parent=PRODUCT.id, via="offers")
    for i in range(3)
)

SKU = FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku")
PRICE = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")
AVAILABILITY = FieldSpec(
    type=FieldType.ENUM, vocab="schema:ItemAvailability", description="d", schema_org="Offer.availability"
)
URL = FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url")


def _schema(**fields: FieldSpec) -> SchemaDef:
    return SchemaDef(id=SchemaId(uuid7()), origin="user", status="active", name="s", page_kind="detail", fields=fields)


def _candidate(field: str, value: object, entity_id: str, kind: SourceKind, n: int) -> Candidate:
    locator = f"meta:og:x{n}" if kind == "og" else f"{entity_id}['x{n}']"
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind=kind,
        raw=value,  # type: ignore[arg-type]
        normalized=Ok(value),  # type: ignore[arg-type]
        locator=locator,
        independent=True,
    )


def _resolver(request_url: str = PAGE_URL, shown: frozenset[str] = frozenset()) -> Resolver:
    return Resolver(
        graph=EntityGraph.of((PRODUCT, *OFFERS), VOCABULARY),
        target=PRODUCT,
        page=PageFacts.of(request_url, shown.__contains__),
        orders=ORDERS,
    )


_SKUS = st.sampled_from(["A-1", "A-2", "B-7"])
_SOURCES = st.sampled_from([(PRODUCT.id, "jsonld"), (PAGE, "og"), (PRODUCT.id, "adapter")])


@given(st.lists(st.tuples(_SKUS, _SOURCES), max_size=6))
def test_exact_values_publish_only_when_all_agree(drawn: list[tuple[str, tuple[str, SourceKind]]]) -> None:
    candidates = [_candidate("sku", value, owner, kind, n) for n, (value, (owner, kind)) in enumerate(drawn)]

    result = _resolver().prefer(_schema(sku=SKU), candidates)["sku"]

    values = {value for value, _ in drawn}
    if not values:
        assert result == Unpublished("missing", "no_candidates", ())
    elif len(values) == 1:
        assert isinstance(result, Chosen)
        assert result.candidate.normalized == Ok(values.pop())
        assert len(result.agreeing) == len(drawn) - 1
    else:
        assert isinstance(result, Unpublished)
        assert (result.status, result.reason) == ("conflict", "disagree")


_PARAM = st.text(st.characters(categories=("L", "N")), min_size=1, max_size=8)


@given(_PARAM, st.booleans(), st.booleans())
def test_a_query_parameter_value_publishes_only_when_shown(value: str, in_query: bool, shown: bool) -> None:
    query = f"?p={value}" if in_query else "?p=other-value"
    resolver = _resolver(f"{PAGE_URL}{query}", frozenset({value}) if shown else frozenset())
    candidate = _candidate("sku", value, PRODUCT.id, "jsonld", 0)

    result = resolver.prefer(_schema(sku=SKU), [candidate])["sku"]

    if in_query and not shown:
        assert result == Unpublished("missing", "url_param", ((candidate, "url_param"),))
    else:
        assert result == Chosen(candidate, (), (), (candidate,))


_PRICES = st.sampled_from([{"amount": "10.00", "currency": "USD"}, {"amount": "12.00", "currency": "USD"}])
_STOCK = st.sampled_from(["InStock", "OutOfStock"])
_OFFER = st.tuples(st.none() | _PRICES, st.none() | _STOCK)


@given(st.lists(_OFFER, min_size=1, max_size=len(OFFERS)))
def test_offer_fields_publish_from_one_offer_that_all_offers_agree_with(
    offers: list[tuple[dict[str, str] | None, str | None]],
) -> None:
    candidates = _offer_candidates(offers)

    result = _resolver().prefer(_schema(price=PRICE, availability=AVAILABILITY), candidates)

    published = {name: p for name, p in result.items() if isinstance(p, Chosen)}
    if len(offers) == 1:
        assert published.keys() == {c.field for c in candidates}
    # One source object (INV-15).
    assert len({p.candidate.entity_id for p in published.values()}) <= 1
    # Every Offer that states the field states the published value.
    for name, preference in published.items():
        stated = [c.normalized for c in candidates if c.field == name]
        assert all(value == preference.candidate.normalized for value in stated)


def _offer_candidates(offers: list[tuple[dict[str, str] | None, str | None]]) -> list[Candidate]:
    candidates = []
    for n, (offer, (price, stock)) in enumerate(zip(OFFERS, offers, strict=False)):
        if price is not None:
            candidates.append(_candidate("price", price, offer.id, "jsonld", 2 * n))
        if stock is not None:
            candidates.append(_candidate("availability", stock, offer.id, "jsonld", 2 * n + 1))
    return candidates


_PREFERENCES = st.one_of(
    st.builds(
        Unpublished,
        st.sampled_from(["missing", "conflict"]),
        st.sampled_from(["no_candidates", "disagree"]),
        st.just(()),
    ),
    st.just(_candidate("url", PAGE_URL, PRODUCT.id, "jsonld", 0)).map(lambda c: Chosen(c, (), (), (c,))),
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


@given(st.lists(st.tuples(st.sampled_from(range(len(OFFERS))), _PRICES), min_size=1, max_size=8))
def test_offers_split_exactly_when_two_offers_state_different_values(stated: list[tuple[int, dict[str, str]]]) -> None:
    candidates = [_candidate("price", price, OFFERS[i].id, "jsonld", n) for n, (i, price) in enumerate(stated)]

    result = _resolver().prefer(_schema(price=PRICE), candidates)["price"]

    # §4.8 and INV-14, compared pair by pair: the rule the grouped comparison must give.
    pairs = [(a, b) for a in stated for b in stated]
    if any(a[0] != b[0] and a[1] != b[1] for a, b in pairs):
        assert isinstance(result, Unpublished)
        assert (result.status, result.reason) == ("conflict", "offers_disagree")
    elif len({tuple(price.items()) for _, price in stated}) > 1:
        assert isinstance(result, Unpublished)
        assert (result.status, result.reason) == ("conflict", "disagree")
    else:
        assert isinstance(result, Chosen)
        assert result.candidate.normalized == Ok(dict(stated[0][1]))
