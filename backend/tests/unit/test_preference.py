"""Preference (SPEC-05 §4.7, §4.8, ARCHITECTURE §8.2 rule 4, §10): which of a field's valid, owned candidates
publishes, and why every other one does not."""

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


# Exact-match types (INV-14)


def test_disagreeing_exact_candidates_are_a_conflict() -> None:
    jsonld = _candidate("sku", "A-1")
    og = _candidate("sku", "A-2", PAGE, "og")

    result = _prefer(_schema(sku=SKU), jsonld, og)

    assert result["sku"] == Unpublished("conflict", "disagree", ((jsonld, "disagree"), (og, "disagree")), (jsonld, og))


# Text, url and image_url: source precedence


def test_the_first_ranked_source_kind_wins_and_lower_ones_that_disagree_are_rejected() -> None:
    og = _candidate("title", "Lamp, the shop", PAGE, "og")
    jsonld = _candidate("title", "Lamp")
    og_same = _candidate("title", "Lamp", PAGE, "og", n=1)

    result = _prefer(_schema(title=TITLE), og, jsonld, og_same)

    assert result["title"] == Chosen(jsonld, (og_same,), ((og, "precedence"),), (og, jsonld, og_same))


DOM_ORDER: tuple[SourceKind, ...] = ("jsonld", "og", "dom")


# Atomic offers (INV-15)


# URL parameters (INV-13)


# source_precedence.yaml
