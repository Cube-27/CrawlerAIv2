"""Row-mapped fields on a detail page (variants spec, INV-33 to INV-35): rows are matched by key and never by
position, so the order of rows and of sources does not change the published rows; rows with different keys never merge;
a sub-field that disagrees inside one variant leaves the price a conflict; JSON-LD and microdata give equal `variants`
values; and each structured-data shape of a variant set publishes one row per variant with per-sub-field outcomes.
Pages are synthetic (`example.test`) and the schema is preset `commerce_detail` (C3, C9)."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.base import Entity
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve import pipeline
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.rows import linked
from crawlerai.resolve.types import FieldOutcome
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")
_SCHEMA_ORG = "https://schema.org/"


@dataclass(frozen=True)
class Variant:
    sku: str
    price: str
    color: str | None

    def jsonld(self) -> dict[str, Any]:
        offer = {"@type": "Offer", "price": self.price, "priceCurrency": "EUR"}
        node: dict[str, Any] = {"@type": "Product", "sku": self.sku, "offers": offer}
        return node | ({"color": self.color} if self.color else {})

    def microdata(self) -> str:
        color = f'<meta itemprop="color" content="{escape(self.color)}">' if self.color else ""
        return (
            f'<div itemprop="hasVariant" itemscope itemtype="{_SCHEMA_ORG}Product">'
            f'<meta itemprop="sku" content="{escape(self.sku)}">{color}'
            f'<div itemprop="offers" itemscope itemtype="{_SCHEMA_ORG}Offer">'
            f'<meta itemprop="price" content="{self.price}"><meta itemprop="priceCurrency" content="EUR"></div></div>'
        )


SKUS = st.sampled_from(["W-11", "W-12", "W-13", "W-14"])
VARIANTS = st.builds(Variant, SKUS, st.sampled_from(["10.00", "12.00"]), st.none() | st.sampled_from(["Red", "Blue"]))
# Variants with distinct skus: one per variant. A list of variants has two or more (owner, Appendix A #48).
DISTINCT = st.lists(VARIANTS, min_size=2, max_size=4, unique_by=lambda v: v.sku)


def _jsonld(variants: list[Variant]) -> str:
    group: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Synthetic Widget",
        "url": PAGE_URL,
    }
    group["hasVariant"] = [v.jsonld() for v in variants]
    return f'<script type="application/ld+json">{json.dumps(group)}</script>'


def _microdata(variants: list[Variant]) -> str:
    inner = "".join(v.microdata() for v in variants)
    return (
        f'<div itemscope itemtype="{_SCHEMA_ORG}ProductGroup"><meta itemprop="name" content="Synthetic Widget">'
        f'<link itemprop="url" href="{PAGE_URL}">{inner}</div>'
    )


def _outcome(head: str = "", body: str = "") -> FieldOutcome:
    return _entity(head, body)["variants"]


def _entity(head: str = "", body: str = "") -> dict[str, FieldOutcome]:
    raw = f"<html><head>{head}</head><body>{body}</body></html>".encode()
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
    bundle = CaptureBundle(manifest=manifest, body=raw, network=())
    result = asyncio.run(extract_page(bundle, SCHEMA, None, None, data=DATA))
    assert result.entity is not None
    return dict(result.entity)


def _rows(outcome: FieldOutcome) -> list[str]:
    """The published rows, each as canonical JSON, sorted: row order follows the page, and is compared apart."""
    value: JsonValue = outcome.value if outcome.status == "published" else []
    assert isinstance(value, list)
    return sorted(json.dumps(row, sort_keys=True) for row in value)


# Each example runs the whole extraction pipeline; its time depends on the machine, not on the property.
_RUNS_THE_PIPELINE = settings(deadline=None)


@settings(_RUNS_THE_PIPELINE, max_examples=50)
@given(DISTINCT, st.randoms(use_true_random=False))
def test_rows_never_merge_and_neither_their_order_nor_their_source_changes_them(
    variants: list[Variant], random: Any
) -> None:
    shuffled = random.sample(variants, len(variants))

    in_order = _rows(_outcome(head=_jsonld(variants), body=_microdata(variants)))
    reordered = _rows(_outcome(head=_jsonld(shuffled), body=_microdata(list(reversed(variants)))))
    from_jsonld = _rows(_outcome(head=_jsonld(variants)))

    # Rows with different keys never merge, and JSON-LD and microdata give equal rows.
    assert len(from_jsonld) == len(variants)
    assert from_jsonld == _rows(_outcome(body=_microdata(variants)))
    assert in_order == reordered


@_RUNS_THE_PIPELINE
@given(VARIANTS, st.sampled_from(["10.00", "12.00"]))
def test_a_price_that_disagrees_inside_a_variant_is_a_conflict(variant: Variant, other_price: str) -> None:
    twin = Variant(variant.sku, other_price, variant.color)
    other = Variant("W-99", "10.00", None)  # a second variant, so that the list publishes

    outcome = _outcome(head=_jsonld([variant, twin, other]))

    assert outcome.items is not None
    assert len(outcome.items) == 2
    price = outcome.items[0].fields["price"]
    # Two Offers of one variant state other amounts and nothing says which is its price: accuracy before coverage.
    if other_price == variant.price:
        assert price.value == {"amount": variant.price, "currency": "EUR"}
    else:
        assert (price.status, price.reason) == ("conflict", "offers_disagree")


def test_a_key_never_joins_rows_an_earlier_key_tells_apart() -> None:
    # Two sizes of one sku with their own GTINs: the gtin, listed first, is the more specific key.
    rows = [Entity(id=f"row:{i}", types=("Product",), urls=(), parent=None) for i in range(3)]
    keys: dict[str, dict[str, list[JsonValue]]] = {
        "row:0": {"gtin": ["4006381333931"], "sku": ["W-1"]},
        "row:1": {"gtin": ["4006381333948"], "sku": ["W-1"]},
        "row:2": {"sku": ["W-1"]},
    }
    subs = {"gtin": FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin"), "sku": FieldSpec(type=FieldType.TEXT)}

    groups = [[row.id for row in group] for group in linked(subs, rows, keys)]

    # The row without a gtin joins both by its sku, which is then a conflict cluster (INV-33), never a guess.
    assert groups == [["row:0", "row:1", "row:2"]]
    assert [[row.id for row in group] for group in linked(subs, rows[:2], keys)] == [["row:0"], ["row:1"]]


def _offer(price: str, **values: Any) -> dict[str, Any]:
    return {"@type": "Offer", "price": price, "priceCurrency": "EUR", "availability": "https://schema.org/InStock"} | (
        values
    )


def _variant(sku: str, price: str, **values: Any) -> dict[str, Any]:
    return {"@type": "Product", "sku": sku, "offers": _offer(price)} | values


def _group(*variants: dict[str, Any], **values: Any) -> dict[str, Any]:
    return {"@type": "ProductGroup", "name": "Synthetic Widget", "url": PAGE_URL, "hasVariant": list(variants)} | values


def _blocks(*nodes: dict[str, Any]) -> str:
    return "".join(
        f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **n})}</script>'
        for n in nodes
    )


def _variants(*nodes: dict[str, Any], body: str = "") -> FieldOutcome:
    return _entity(_blocks(*nodes), body)["variants"]


def _published(outcome: FieldOutcome) -> list[dict[str, JsonValue]]:
    assert outcome.status == "published", (outcome.status, outcome.reason)
    assert isinstance(outcome.value, list)
    rows = [row for row in outcome.value if isinstance(row, dict)]
    assert len(rows) == len(outcome.value), outcome.value  # every row is an object
    return rows


def test_a_group_s_variants_with_offers_are_one_row_each() -> None:
    outcome = _variants(_group(_variant("W-11", "10.00", size="S"), _variant("W-12", "12.00", size="M")))

    assert _published(outcome) == [
        {
            "sku": "W-11",
            "price": {"amount": "10.00", "currency": "EUR"},
            "availability": "InStock",
            "size": "S",
        },
        {
            "sku": "W-12",
            "price": {"amount": "12.00", "currency": "EUR"},
            "availability": "InStock",
            "size": "M",
        },
    ]
    # INV-34: every sub-field outcome of a published row carries status and reason; published ones carry provenance.
    assert outcome.items is not None
    assert len(outcome.items) == 2
    gtin = outcome.items[0].fields["gtin"]
    assert (gtin.status, gtin.reason) == ("missing", "no_candidates")
    price = outcome.items[0].fields["price"]
    assert (price.evidence, price.source_kind) == ("structured", "jsonld")
    assert outcome.locator == "jsonld:0:$['hasVariant'][0]"


def test_entries_of_one_list_with_other_skus_are_two_variants_whatever_barcode_they_repeat() -> None:
    # INV-33: one list names each of its items once, so two entries saying W-11 and W-12 are two variants (a sold-out
    # one as well), though both repeat the product's GTIN.
    first = _variant("W-11", "10.00", gtin="4006381333931")
    second = _variant("W-12", "10.00", gtin="4006381333931", offers=_offer("10.00", availability="OutOfStock"))

    assert [(row["sku"], row["availability"]) for row in _published(_variants(_group(first, second)))] == [
        ("W-11", "InStock"),
        ("W-12", "OutOfStock"),
    ]


def test_one_offer_each_source_states_by_another_key_is_the_item_s_one_offer() -> None:
    # Two blocks of one Product (one `@id`) each state its one Offer, one by its URL and one by its SKU: one variant,
    # so no variant list publishes (Appendix A #48), not two half-rows.
    product = {"@type": "Product", "@id": PAGE_URL + "#product", "name": "Synthetic Widget"}
    by_url = product | {"offers": {"@type": "Offer", "url": PAGE_URL + "?variant=1", "availability": "InStock"}}
    by_sku = product | {"offers": _offer("10.00", sku="W-11")}

    outcome = _variants(by_url, by_sku)

    assert (outcome.status, outcome.reason) == ("missing", "single_row")


def test_each_variant_row_publishes_its_stated_price_and_only_a_one_offer_page_publishes_the_visible_one() -> None:
    # Variants spec: a row publishes the amount its variant states, whatever amount the page shows at the top; the
    # visible price is the page offer's, and a page is one offer only when it states one variant.
    shown = "<main><h1>Synthetic Widget</h1><p><span>€12.10</span></p></main>"

    for prices in (("10.00", "10.00"), ("10.00", "11.00")):
        rows = _published(_variants(_group(*(_variant(f"W-1{i}", p) for i, p in enumerate(prices))), body=shown))
        assert [row["price"] for row in rows] == [{"amount": p, "currency": "EUR"} for p in prices]

    one = _entity(_blocks(_group(_variant("W-10", "10.00"))), shown)
    assert (one["variants"].status, one["variants"].reason) == ("missing", "single_row")
    assert one["price"].value == {"amount": "12.10", "currency": "EUR"}


def test_role_c_is_never_asked_for_a_row_mapped_field() -> None:
    # variants spec: a claim is one verbatim span, which cannot hold a row of typed sub-fields.
    fields = {name: _missing() for name in SCHEMA.fields}

    assert "variants" not in pipeline._gaps(SCHEMA, fields, frozenset())
    assert "title" in pipeline._gaps(SCHEMA, fields, frozenset())


def _missing() -> FieldOutcome:
    return FieldOutcome(
        status="missing",
        reason="no_candidates",
        value=None,
        evidence=None,
        confidence=None,
        calibrated=False,
        source_kind=None,
        locator=None,
        derived_by=None,
        chosen=None,
        rejected=(),
    )
