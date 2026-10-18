"""Derived values (SPEC-05 §4.8, ARCHITECTURE §9, C7, INV-07): only a missing field is filled, only by a named
derivation, and the value says which."""

from datetime import UTC, datetime
from pathlib import Path

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId, SourceKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.resolve.derive import Derived, fill, is_page_url_field
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import PRECEDENCE_TYPES, Chosen, PageFacts, Preference, Resolver
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
FINAL_URL = "https://shop.example.test/p/1?colour=red"
CANONICAL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=FINAL_URL, page_url=FINAL_URL)

PRODUCT = Entity(id="jsonld:0:$", types=("Product",), urls=(), parent=None)
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", types=("Product",), urls=(), parent=PRODUCT.id, via="isRelatedTo")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
RESOLVER = Resolver(
    graph=EntityGraph.of((PRODUCT, RELATED), VOCABULARY),
    target=PRODUCT,
    page=PageFacts.of(FINAL_URL, lambda _: False),
    orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER),
)

URL = FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url")
IMAGE = FieldSpec(type=FieldType.IMAGE_URL, description="d", schema_org="Product.image")
TITLE = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")


def _schema(page_kind: PageKind = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields=fields,
    )


def _fill(
    spec: FieldSpec,
    preference: Preference,
    *candidates: Candidate,
    canonical_url: str | None = CANONICAL,
    page_url_field: bool = True,
    ctx: Context = CTX,
) -> Preference | Derived:
    return fill(
        spec,
        preference,
        candidates,
        RESOLVER,
        ctx,
        canonical_url=canonical_url,
        page_url_field=page_url_field,
    )


def test_the_page_url_field_is_a_detail_schemas_url_of_its_primary_type() -> None:
    schema = _schema(url=URL, title=TITLE, image=IMAGE, seller_url=URL.model_copy(update={"schema_org": "Offer.url"}))
    primary = frozenset({"Product"})

    assert [name for name, spec in schema.fields.items() if is_page_url_field(schema, spec, primary)] == ["url"]


def test_a_published_field_is_not_filled() -> None:
    chosen = Candidate(
        field="url",
        entity_id=PRODUCT.id,
        source_kind="jsonld",
        raw=CANONICAL,
        normalized=Ok(CANONICAL),
        locator="jsonld:0:$['url']",
        independent=True,
    )
    preference = Chosen(chosen, (), (), (chosen,))

    assert _fill(URL, preference) == preference
