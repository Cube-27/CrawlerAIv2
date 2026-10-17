"""Failure classes of extraction replayed through `extract_page` on synthetic captures (SPEC-05 §4.5 to §4.8): each
test builds the class's page shape on `example.test` names (C3, C9) and checks what the commerce preset publishes."""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


def _extract(head: str, body: str = "", schema: SchemaDef = SCHEMA, lang: str = "") -> ExtractionResult:
    lang_attribute = f' lang="{lang}"' if lang else ""
    raw = f"<html{lang_attribute}><head>{head}</head><body>{body}</body></html>".encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=PAGE_URL,
        final_url=PAGE_URL,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return asyncio.run(
        extract_page(CaptureBundle(manifest=manifest, body=raw, network=()), schema, None, None, data=DATA)
    )


def _jsonld(*nodes: Mapping[str, Any]) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(node)}</script>' for node in nodes)


def _outcomes(result: ExtractionResult, *names: str) -> dict[str, tuple[str, str | None, JsonValue]]:
    assert result.entity is not None
    return {name: (result.entity[name].status, result.entity[name].reason, result.entity[name].value) for name in names}


def test_state_admission_stays_linear_in_values_and_anchors() -> None:
    # 2,000 gallery images give the image field 2,000 anchors, and 10,000 distinct state strings are tried against
    # them: 20 million url equalities pairwise, one key lookup per value with an equality-key index.
    images = [f"https://cdn.example.test/img/{i}.jpg" for i in range(2_000)]
    product = {"@context": "https://schema.org", "@type": "Product", "name": "Synthetic Widget", "image": images}
    state = [f"https://cdn.example.test/img/{i % 4_000}.jpg?w={i}" for i in range(10_000)]
    head = _jsonld(product) + f"<script>window.__STATE__ = {json.dumps(state)};</script>"

    started = time.perf_counter()
    result = _extract(head)
    elapsed = time.perf_counter() - started

    assert _outcomes(result, "title") == {"title": ("published", None, "Synthetic Widget")}
    assert elapsed < 20


def _og(*metas: tuple[str, str]) -> str:
    return "".join(f'<meta property="{p}" content="{c}">' for p, c in metas)


def test_site_wide_og_values_on_a_client_rendered_page_do_not_publish() -> None:
    # The page names its product only in rendered text; its og block is the site's default.
    head = _og(
        ("og:site_name", "Synthetic Tools - Workshop"),
        ("og:title", "Synthetic Tools"),
        ("og:image", "https://shop.example.test/banner.png"),
        ("og:url", PAGE_URL),
    )

    result = _extract(head, "<h1>Widget One</h1>")

    assert _outcomes(result, "title", "image_url", "url") == {
        "title": ("missing", "no_candidates", None),
        "image_url": ("missing", "no_candidates", None),
        "url": ("published", None, PAGE_URL),
    }


def test_an_og_title_publishes_without_its_site_segment() -> None:
    result = _extract(_og(("og:title", "Widget One | green | Example Store")))

    assert _outcomes(result, "title") == {"title": ("published", None, "Widget One | green")}


def _product(**properties: Any) -> dict[str, Any]:
    return {"@context": "https://schema.org", "@type": "Product", **properties}


def _offer(price: str, availability: str, **properties: Any) -> dict[str, Any]:
    return {"@type": "Offer", "price": price, "priceCurrency": "EUR", "availability": availability, **properties}


def test_two_blocks_of_one_node_id_publish_as_one_product() -> None:
    # One block writes the page's URL relative; both name one @id, so they are one product and its values agree.
    head = _jsonld(
        _product(
            **{"@id": "/p/1#product"},
            url=PAGE_URL,
            name="Widget One",
            sku="W-1",
            offers=_offer("14.00", "https://schema.org/InStock"),
        ),
        _product(**{"@id": "/p/1#product"}, url="/p/1", name="Widget One", offers=_offer("14.0", "InStock")),
    )

    assert _outcomes(_extract(head), "title", "price", "availability", "sku") == {
        "title": ("published", None, "Widget One"),
        "price": ("published", None, {"amount": "14.00", "currency": "EUR"}),
        "availability": ("published", None, "InStock"),
        "sku": ("published", None, "W-1"),
    }


def test_two_blocks_of_one_sku_that_disagree_on_the_offer_are_a_conflict() -> None:
    # The second block has no @id or url, only the sku that identifies the product: its Offer is the product's too,
    # so the two Offers disagree and neither publishes.
    head = _jsonld(
        _product(url=PAGE_URL, name="Widget One", sku="W-1", offers=_offer("199.95", "https://schema.org/OutOfStock")),
        _product(
            name="Widget One",
            sku="W-1",
            offers=_offer("179.95", "https://schema.org/InStock", sku="W-1", url=f"{PAGE_URL}?variant=2"),
        ),
    )

    assert _outcomes(_extract(head), "title", "price", "availability") == {
        "title": ("published", None, "Widget One"),
        "price": ("conflict", "offers_disagree", None),
        "availability": ("conflict", "offers_disagree", None),
    }


def test_og_image_selects_one_image_of_a_json_ld_gallery() -> None:
    gallery = [f"https://cdn.example.test/w1-{side}.jpg" for side in ("front", "back", "side")]
    product = _product(url=PAGE_URL, name="Widget One", image=gallery)

    named = _extract(_jsonld(product) + _og(("og:image", gallery[1])))
    rendition = _extract(_jsonld(product) + _og(("og:image", f"{gallery[1]}?w=1200&amp;h=630")))
    unnamed = _extract(_jsonld(product) + _og(("og:image", "https://cdn.example.test/w1-crop.jpg")))

    assert _outcomes(named, "image_url") == {"image_url": ("published", None, gallery[1])}
    assert _outcomes(rendition, "image_url") == {"image_url": ("published", None, gallery[1])}
    assert _outcomes(unnamed, "image_url") == {"image_url": ("conflict", "disagree", None)}


def test_a_page_without_canonical_or_og_url_publishes_its_final_url_as_derived() -> None:
    # Round-1 class 9, fixed by D-0355's derivation: a static page with no structured data and no canonical link.
    result = _extract("<title>Widget One</title>", "<h1>Widget One</h1>")

    assert result.entity is not None
    url = result.entity["url"]
    assert (url.status, url.value, url.evidence, url.derived_by) == ("published", PAGE_URL, "derived", "final_url")


def test_a_variant_page_beside_its_group_publishes_its_canonical_url_as_derived() -> None:
    # Eval class 16: the page's Product states no url of its own and the group beside it names the group's page, so
    # the url is the canonical link's (D-0355), not the group's and not missing.
    group_url = "https://shop.example.test/p/group"
    product = _product(name="Widget One", sku="W-1", offers=_offer("10.00", "https://schema.org/InStock", url=PAGE_URL))
    group = _product(**{"@type": "ProductGroup"}, name="Widget", url=group_url, hasVariant=[{"@type": "Product"}])
    result = _extract(_jsonld(product, group) + f'<link rel="canonical" href="{PAGE_URL}">')

    assert result.entity is not None
    url = result.entity["url"]
    assert (url.status, url.value, url.evidence, url.derived_by) == ("published", PAGE_URL, "derived", "canonical_link")


_LISTING_PRESET = next(p for p in load_presets() if p.name == "commerce_listing")
LISTING = SchemaDef(**_LISTING_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


def test_microdata_rows_with_prices_written_with_their_sign_publish_them() -> None:
    # A listing's microdata Offers write `price` as display text beside `priceCurrency` (schema.org asks for digits
    # only); each row publishes its price in the stated currency (D-1240).
    card = (
        '<div itemscope itemtype="https://schema.org/Product"><a itemprop="url" href="/item/{n}">p</a>'
        '<h4 itemprop="name">Widget {n}</h4><div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        '<span itemprop="price">${n},299.50</span><meta itemprop="priceCurrency" content="USD"></div></div>'
    )
    body = "".join(card.format(n=n) for n in (1, 2, 3))

    result = _extract('<meta charset="utf-8">', body, LISTING, lang="en")

    assert [(row["title"].value, row["price"].value) for row in result.rows] == [
        (f"Widget {n}", {"amount": f"{n}299.50", "currency": "USD"}) for n in (1, 2, 3)
    ]
