"""Data calls (acquisition spec, "Data calls"): a platform's documented product JSON joins the page only when it states
the requested product, and is then read as structured evidence with its documented minor unit; another product's
answer is refused, as a detail API recipe's is. The fetch path is grounded at runtime; this covers the identity check,
the unit and the platform's declared currency on any product key and amount, and the variant rows."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.identity import NOT_THE_PRODUCT, identified, joined
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.collect.base import Entity
from crawlerai.collect.currencies import with_page_declarations
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.platform_json import PlatformJsonCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.resolve.intent import primary_types, select_target
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, network_file
from crawlerai.storage.capture_bundle import sha256_hex as sha

HOST = "https://shop.example.test"
KEYS = st.from_regex(r"[a-z][a-z0-9]{2,8}-[a-z0-9]{2,8}", fullmatch=True)
CENTS = st.integers(min_value=1, max_value=10**9)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
SCHEMA = next(
    SchemaDef(id=SchemaId(uuid7()), origin="preset", status="active", **d.model_dump())
    for d in load_presets()
    if d.name == "commerce_detail"
)


def _capture(url: str, method: CaptureMethod, body: bytes, calls: tuple[tuple[str, bytes], ...] = ()) -> FetchResult:
    entries = tuple(
        NetworkBody(
            url=u, status=200, content_type="application/json", sha256=sha(b), file=network_file(i), method="GET"
        )
        for i, (u, b) in enumerate(calls)
    )
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
        fetched_at=datetime.now(UTC),
        method=method,
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("content-type", "application/json"),)),
        timings_ms={"total": 1},
        html_sha256=sha(body),
        network_bodies=entries,
        fetch_policy=FetchPolicy().model_dump(mode="json"),
        engine_version="test",
    )
    bundle = CaptureBundle(manifest=manifest, body=body, network=tuple(b for _, b in calls))
    attempt = AttemptRecord(method=method, status=200, block_class="ok", duration_ms=1)
    return FetchResult(bundle=bundle, duration_ms=1, attempts=(attempt,))


def _product(key: str, cents: int = 2900) -> bytes:
    # Shopify Ajax API product (its documentation, "Product"): one variant, its price in cents for every currency.
    variant = {"id": 1, "title": "Default", "sku": f"{key}-1", "barcode": "4006381333931", "price": cents}
    product = {"handle": key, "title": "Item", "url": f"/products/{key}", "variants": [{**variant, "available": False}]}
    images = [f"//cdn.example.test/files/{key}-{n}.jpg" for n in (1, 2)]
    return json.dumps({**product, "description": "<p>A <b>mug</b>.</p>", "images": images}).encode()


# An Online Store page: the platform's features script and its presentment currency (`content_for_header`).
_PAGE = b'<html><script id="shopify-features"></script><script>Shopify.currency = {"active":"CAD"};</script></html>'


@given(KEYS, KEYS, CENTS)
def test_a_documented_answer_joins_only_for_its_product_and_reads_in_major_units(
    key: str, other: str, cents: int
) -> None:
    page = f"{HOST}/products/{key}"
    http = _capture(page, "http", _PAGE)

    served, attempt = joined(http, _capture(f"{page}.js", "api", _product(key, cents)), key, "shopify")

    assert served is not None
    assert attempt.attempts[-1].error is None
    assert served.bundle.manifest.network_bodies[-1].data_call == "shopify"
    parsed = ParsedPage.of(served.bundle)
    ctx = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC), html_lang="en-US", page_url=page, base_url=page)
    read = PlatformJsonCollector(VOCABULARY).collect(parsed, SCHEMA, with_page_declarations(ctx, parsed))
    prices = [c.normalized for c in read.candidates if c.field == "price"]
    assert len(prices) == 1
    assert isinstance(prices[0], Ok)
    # The amount in major units, in the currency the page's `Shopify.currency.active` declares.
    assert prices[0].value == {"amount": format(Decimal(cents).scaleb(-2), "f"), "currency": "CAD"}
    # The variant's own identifiers fill a `variants` row.
    row = {c.field: c.normalized for c in read.candidates if c.field.startswith("variants.")}
    assert row["variants.sku"] == Ok(f"{key}-1")
    assert row["variants.gtin"] == Ok("4006381333931")
    # `available: false` is OutOfStock; `true` names no one ItemAvailability (pre-order and back order can be bought).
    assert row["variants.availability"] == Ok("OutOfStock")
    # The product's every image, the featured one first, and its HTML body read as text.
    files: list[JsonValue] = [f"https://cdn.example.test/files/{key}-{n}.jpg" for n in (1, 2)]
    # Each publishes as the answer writes it, scheme-relative.
    written: list[JsonValue] = [f"//cdn.example.test/files/{key}-{n}.jpg" for n in (1, 2)]
    assert [c.normalized for c in read.candidates if c.field == "additional_images"] == [Ok(files, stated=written)]
    assert [c.normalized for c in read.candidates if c.field == "description"] == [Ok("A mug.")]
    if other != key:
        # Another product's answer (an endpoint that ignores its key) never joins, and says why.
        refused, attempt = joined(http, _capture(f"{page}.js", "api", _product(other)), key, "shopify")
        assert refused is None
        assert (attempt.block_class, attempt.attempts[-1].error) == ("error", NOT_THE_PRODUCT)
        # A detail API recipe's answer is checked the same way.
        recipe = identified(_capture(f"{HOST}/api/p", "api", _product(other)), page, (key,))
        assert recipe.attempts[-1].error == NOT_THE_PRODUCT


def test_a_documented_answer_is_the_page_products_own_entity() -> None:
    # The answer's Product names its sku and barcode on its variants only, and no IRI: it passed the identity check,
    # so it is the page's one JSON-LD Product, and the page has one target holding both sources' values.
    page = f"{HOST}/products/blue-mug"
    markup = {"@context": "https://schema.org", "@type": "Product", "name": "Blue Mug", "description": "A blue mug."}
    html = f'<html><script type="application/ld+json">{json.dumps(markup)}</script></html>'.encode()
    served, _ = joined(
        _capture(page, "http", html), _capture(f"{page}.js", "api", _product("blue-mug")), "blue-mug", "shopify"
    )
    assert served is not None
    parsed = ParsedPage.of(served.bundle)
    ctx = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC), html_lang="en-US", page_url=page, base_url=page)
    reads = [c.collect(parsed, SCHEMA, ctx) for c in (JsonLdCollector(VOCABULARY), PlatformJsonCollector(VOCABULARY))]
    graph = EntityGraph.of((e for r in reads for e in r.entities), VOCABULARY, (page,))

    target = select_target(page, page, None, graph, primary_types(SCHEMA, VOCABULARY))

    assert isinstance(target, Entity)
    owned = {c.field for c in graph.adopt(c for r in reads for c in r.candidates) if graph.owned_by(c, target)}
    assert {"description", "price", "variants.sku"} <= owned
    # A sole root Product whose URL is another page's is another item: the answer stays apart from it.
    elsewhere = Entity(id="jsonld:0:$", types=("Product",), urls=(), parent=None, item_urls=(f"{HOST}/products/other",))
    assert not EntityGraph.of((elsewhere, *reads[1].entities), VOCABULARY, (page,)).aliases
    # A comparison table's microdata Products (one shape, repeated) are other items, not more roots of the page's own.
    table = (
        Entity(id=f"microdata:/html[1]/body[1]/table[1]/tr[1]/th[{n}]", types=("Product",), urls=(), parent=None)
        for n in (1, 2, 3)
    )
    beside = EntityGraph.of((*reads[0].entities, *table, *reads[1].entities), VOCABULARY, (page,))
    assert set(beside.aliases.values()) == {reads[0].entities[0].id}
