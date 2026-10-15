"""Derived values (SPEC-05 §4.8, ARCHITECTURE §9, C7, INV-07): only a missing field is filled, only by a named
derivation, and the value says which."""

from datetime import UTC, datetime
from pathlib import Path

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId, SourceKind
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.resolve.derive import Derived, fill, is_page_url_field
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import PRECEDENCE_TYPES, Chosen, PageFacts, Preference, Resolver, Unpublished
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
FINAL_URL = "https://shop.example.test/p/1?colour=red"
CANONICAL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=FINAL_URL, page_url=FINAL_URL)

PRODUCT = Entity(id="jsonld:0:$", kind="Product", urls=(), parent=None)
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", kind="Product", urls=(), parent=PRODUCT.id, via="isRelatedTo")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
RESOLVER = Resolver(
    graph=EntityGraph.of((PRODUCT, RELATED), VOCABULARY),
    target=PRODUCT,
    page=PageFacts.of(FINAL_URL, lambda _: False),
    orders={t: ORDER for t in PRECEDENCE_TYPES},
)

URL = FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url")
IMAGE = FieldSpec(type=FieldType.IMAGE_URL, description="d", schema_org="Product.image")
TITLE = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
MISSING = Unpublished("missing", "no_candidates", ())


def _schema(page_kind: PageKind = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        version=1,
        page_kind=page_kind,
        fields=fields,
    )


def _relative(field: str, raw: str, entity: Entity = PRODUCT) -> Candidate:
    # A collector without a base URL leaves a relative reference unresolved (SPEC-04 §4.4).
    return Candidate(
        field=field,
        entity_id=entity.id,
        source_kind="jsonld",
        raw=raw,
        normalized=Invalid("relative_without_base"),
        locator=f"{entity.id}['{field}']",
        independent=True,
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


def test_a_listing_has_no_page_url_field() -> None:
    schema = _schema("listing", url=URL)
    assert is_page_url_field(schema, URL, frozenset({"Product"})) is False


def test_a_missing_page_url_is_the_canonical_link() -> None:
    assert _fill(URL, MISSING) == Derived(CANONICAL, "canonical_link", None)


def test_without_a_canonical_link_the_page_url_is_the_final_url() -> None:
    assert _fill(URL, MISSING, canonical_url=None) == Derived(FINAL_URL, "final_url", None)


def test_a_canonical_link_that_is_not_an_http_url_is_skipped() -> None:
    assert _fill(URL, MISSING, canonical_url="ftp://shop.example.test/p/1") == Derived(FINAL_URL, "final_url", None)


def test_only_the_page_url_field_takes_the_page_url() -> None:
    assert _fill(URL, MISSING, page_url_field=False) == MISSING


def test_a_conflict_is_not_filled() -> None:
    # A conflict is a field with values that disagree, not an empty one (INV-07, INV-14).
    preference = Unpublished("conflict", "disagree", ())
    assert _fill(URL, preference) == preference


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


def test_a_relative_image_of_the_target_is_absolutized_against_the_base_url() -> None:
    image = _relative("image", "../img/a.jpg")

    result = _fill(IMAGE, MISSING, image, page_url_field=False)

    assert result == Derived("https://shop.example.test/img/a.jpg", "absolutize", image)


def test_an_absolutized_value_comes_before_the_page_url() -> None:
    url = _relative("url", "/p/1-lamp")

    assert _fill(URL, MISSING, url) == Derived("https://shop.example.test/p/1-lamp", "absolutize", url)


def test_a_relative_value_of_another_entity_is_not_absolutized() -> None:
    image = _relative("image", "/img/b.jpg", RELATED)

    assert _fill(IMAGE, MISSING, image, page_url_field=False) == MISSING


def test_without_a_base_url_nothing_is_absolutized() -> None:
    image = _relative("image", "/img/a.jpg")
    ctx = Context(captured_at=CTX.captured_at)

    assert _fill(IMAGE, MISSING, image, page_url_field=False, ctx=ctx) == MISSING
