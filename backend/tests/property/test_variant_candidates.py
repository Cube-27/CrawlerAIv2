"""Sub-field candidates of a row-mapped field (SPEC-13 §4.2, §6): a generated variant set, written as JSON-LD and as
microdata, gives the same sub-field candidates from both collectors, and the row path itself gives none."""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.microdata import MicrodataCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url="https://shop.example.test/p/1")
_SCHEMA_ORG = "https://schema.org/"
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "variants": FieldSpec(
            type=FieldType.LIST,
            description="d",
            schema_org="ProductGroup.hasVariant|Product.offers",
            key=["sku", "url"],
            item=FieldSpec(
                type=FieldType.OBJECT,
                fields={
                    "sku": FieldSpec(
                        type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku|Offer.sku"
                    ),
                    "url": FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url"),
                    "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
                    "name": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"),
                },
            ),
        ),
    },
)


@dataclass(frozen=True)
class Variant:
    """One variant Product with one Offer; each property is given or not."""

    name: str | None
    sku: str | None
    offer_sku: str | None
    url: str | None
    price: str | None
    currency: str | None

    def jsonld(self) -> dict[str, JsonValue]:
        offer: dict[str, JsonValue] = {
            "@type": "Offer",
            **_given(sku=self.offer_sku, price=self.price, priceCurrency=self.currency),
        }
        return {"@type": "Product", "offers": offer, **_given(name=self.name, sku=self.sku, url=self.url)}

    def microdata(self) -> str:
        offer = _metas(sku=self.offer_sku, price=self.price, priceCurrency=self.currency)
        url = "" if self.url is None else f'<link itemprop="url" href="{escape(self.url)}">'
        return (
            f'<div itemprop="hasVariant" itemscope itemtype="{_SCHEMA_ORG}Product">'
            f"{_metas(name=self.name, sku=self.sku)}{url}"
            f'<div itemprop="offers" itemscope itemtype="{_SCHEMA_ORG}Offer">{offer}</div></div>'
        )


def _given(**values: str | None) -> dict[str, str]:
    return {k: v for k, v in values.items() if v is not None}


def _metas(**values: str | None) -> str:
    return "".join(f'<meta itemprop="{k}" content="{escape(v)}">' for k, v in _given(**values).items())


_codes = st.text(alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ0123456789-", min_size=1, max_size=8)


def _maybe(values: st.SearchStrategy[str]) -> st.SearchStrategy[str | None]:
    return st.none() | values


VARIANTS = st.lists(
    st.builds(
        Variant,
        name=_maybe(st.text(alphabet="abcdefghij XYZ", min_size=1, max_size=10).map(str.strip).filter(bool)),
        sku=_maybe(_codes),
        offer_sku=_maybe(_codes),
        url=_maybe(st.integers(1, 99).map(lambda i: f"https://shop.example.test/p/1?variant={i}")),
        price=_maybe(st.decimals(min_value=0, max_value=10_000, places=2).map(str)),
        currency=_maybe(st.sampled_from(["EUR", "USD", "JPY"])),
    ),
    max_size=6,
)


def _jsonld_page(group_name: str, variants: list[Variant]) -> ParsedPage:
    document = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": group_name,
        "hasVariant": [v.jsonld() for v in variants],
    }
    return ParsedPage(f'<html><head><script type="application/ld+json">{json.dumps(document)}</script></head></html>')


def _microdata_page(group_name: str, variants: list[Variant]) -> ParsedPage:
    inner = "".join(v.microdata() for v in variants)
    return ParsedPage(
        f'<html><body><div itemscope itemtype="{_SCHEMA_ORG}ProductGroup">{_metas(name=group_name)}{inner}</div>'
        "</body></html>"
    )


def _values(candidates: tuple[Candidate, ...]) -> Counter[tuple[str, str]]:
    """Each candidate's field and normalized value (or its status), as a multiset: entity ids and locators differ by
    source, values do not."""
    return Counter(
        (
            c.field,
            json.dumps(c.normalized.value, sort_keys=True)
            if isinstance(c.normalized, Ok)
            else type(c.normalized).__name__,
        )
        for c in candidates
    )


@given(st.text(alphabet="abc ", min_size=1, max_size=6).map(str.strip).filter(bool), VARIANTS)
def test_the_row_path_gives_no_candidates_and_json_ld_and_microdata_give_equal_sub_field_candidates(
    group_name: str, variants: list[Variant]
) -> None:
    jsonld = JsonLdCollector(VOCABULARY).collect(_jsonld_page(group_name, variants), SCHEMA, CTX).candidates
    microdata = MicrodataCollector(VOCABULARY).collect(_microdata_page(group_name, variants), SCHEMA, CTX).candidates
    fields = Counter(c.field for c in jsonld)

    assert "variants" not in fields
    assert fields["variants.sku"] == sum((v.sku is not None) + (v.offer_sku is not None) for v in variants)
    assert fields["variants.price"] == sum(v.price is not None for v in variants)
    assert fields["variants.url"] == sum(v.url is not None for v in variants)
    assert _values(jsonld) == _values(microdata)
