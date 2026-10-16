"""Row matching properties (SPEC-13 §6, INV-33): rows are matched by key and never by position, so the order of rows
and of sources does not change the published rows; rows with different keys never merge; a sub-field that disagrees
inside one variant is a conflict, never a value; and JSON-LD and microdata give equal `variants` values."""

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
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.dispatch import equal
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
    return result.entity["variants"]


def _rows(outcome: FieldOutcome) -> list[str]:
    """The published rows, each as canonical JSON, sorted: row order follows the page, and is compared apart."""
    value: JsonValue = outcome.value if outcome.status == "published" else []
    assert isinstance(value, list)
    return sorted(json.dumps(row, sort_keys=True) for row in value)


# Each example runs the whole extraction pipeline; its time depends on the machine, not on the property.
_RUNS_THE_PIPELINE = settings(deadline=None)


@_RUNS_THE_PIPELINE
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
def test_a_sub_field_that_disagrees_inside_a_variant_is_a_conflict(variant: Variant, other_price: str) -> None:
    twin = Variant(variant.sku, other_price, variant.color)
    other = Variant("W-99", "10.00", None)  # a second variant, so that the list publishes

    outcome = _outcome(head=_jsonld([variant, twin, other]))

    assert outcome.items is not None
    assert len(outcome.items) == 2
    price = outcome.items[0].fields["price"]
    if other_price == variant.price:
        assert price.value == {"amount": variant.price, "currency": "EUR"}
    else:
        assert (price.status, price.value) == ("conflict", None)


_KEY_SUBS = {
    "sku": FieldSpec(type=FieldType.TEXT),
    "url": FieldSpec(type=FieldType.URL),
    "place": FieldSpec(type=FieldType.LOCATION),
}
_KEY_VALUES: dict[str, list[JsonValue]] = {
    "sku": ["W-1", " W-1", "W-2", "W-3"],
    "url": ["https://example.test/v/1", "HTTPS://example.test/v/1#a", "https://example.test/v/2"],
    # Location equality is not transitive: a place without a region equals both places with one.
    "place": [
        {"text": None, "locality": "Springfield", "region": None, "country": "DE", "remote_flag": False},
        {"text": None, "locality": "Springfield", "region": "BY", "country": "DE", "remote_flag": False},
        {"text": None, "locality": "Springfield", "region": "BE", "country": "DE", "remote_flag": False},
    ],
}
ROW_KEYS = st.lists(
    st.fixed_dictionaries(
        {},
        optional={
            sub: st.lists(st.sampled_from(values), min_size=1, max_size=2) for sub, values in _KEY_VALUES.items()
        },
    ),
    max_size=8,
)


@given(ROW_KEYS)
def test_rows_link_as_comparing_every_pair_would(row_keys: list[dict[str, list[JsonValue]]]) -> None:
    rows = [Entity(id=f"row:{i}", types=("Product",), urls=(), parent=None) for i in range(len(row_keys))]
    keys = {row.id: k for row, k in zip(rows, row_keys, strict=True)}

    assert [[row.id for row in group] for group in linked(_KEY_SUBS, rows, keys)] == _pairwise(rows, keys)


def _pairwise(rows: list[Entity], keys: dict[str, dict[str, list[JsonValue]]]) -> list[list[str]]:
    """The components found by comparing every pair of rows (SPEC-13 §4.4, INV-33), in collector order by first row:
    two rows link when they share a value of a key sub-field and state no different value of an earlier one."""
    groups: list[set[str]] = []
    for row in rows:
        joined = [g for g in groups if any(_share(keys[row.id], keys[other]) for other in g)]
        groups = [g for g in groups if g not in joined] + [set().union({row.id}, *joined)]
    order = [row.id for row in rows]
    return sorted(([r for r in order if r in g] for g in groups), key=lambda g: order.index(g[0]))


def _share(a: dict[str, list[JsonValue]], b: dict[str, list[JsonValue]]) -> bool:
    subs = list(_KEY_SUBS)
    return any(
        any(equal(x, y, _KEY_SUBS[sub]) for x in a.get(sub, ()) for y in b.get(sub, ()))
        and not any(_differ(a, b, earlier) for earlier in subs[: subs.index(sub)])
        for sub in subs
    )


def _differ(a: dict[str, list[JsonValue]], b: dict[str, list[JsonValue]], sub: str) -> bool:
    return any(not equal(x, y, _KEY_SUBS[sub]) for x in a.get(sub, ()) for y in b.get(sub, ()))


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
