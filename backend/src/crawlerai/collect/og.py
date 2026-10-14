"""The OpenGraph collector (SPEC-05 §4.5, ARCHITECTURE §8.1): `og:*` and `product:*` meta properties.

OpenGraph names no entity types, so every value describes the page's one object: the entity is `page`, and its URL is
`og:url`. A property maps to a field through the fixed table below, keyed by the OGP property and the field's role:
its type and the one schema.org property its `schema_org` path names on the root type (`Product.name` has the role
`name`; `Product.brand.name` names the brand's name, not the object's, so it has none). The table is justified by the
OGP specification (C2), not by any page.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate, CollectResult, Entity
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

_URL = FieldSpec(type=FieldType.URL)


@dataclass(frozen=True, slots=True)
class _Row:
    """OGP properties (read as one, in document order) whose values fill fields of type `type` with the role `role`."""

    properties: tuple[str, ...]
    type: FieldType
    role: str


_OG_URL = "og:url"
# Open Graph protocol, "Basic Metadata": `og:title` is the object's title, `og:image` its image, `og:url` its
# canonical URL; "Structured Properties": `og:image:url` is identical to `og:image`. The OGP `product` namespace:
# `product:availability` is the item's availability. `product:price:*` is the money row, read by `_price`.
_TABLE = (
    _Row(("og:title",), FieldType.TEXT, "name"),
    _Row(("og:image", "og:image:url"), FieldType.IMAGE_URL, "image"),
    _Row((_OG_URL,), FieldType.URL, "url"),
    _Row(("product:availability",), FieldType.ENUM, "availability"),
)
# OGP `product` namespace: `product:price:amount` is the price and `product:price:currency` its ISO 4217 code.
_AMOUNT, _CURRENCY = "product:price:amount", "product:price:currency"
_READ = frozenset(p for row in _TABLE for p in row.properties) | {_AMOUNT, _CURRENCY}


@dataclass(frozen=True, slots=True)
class _Meta:
    property: str
    content: str


@dataclass(frozen=True, slots=True)
class _Value:
    raw: JsonValue
    locator: str


class OpenGraphCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        metas = _metas(page)
        if not metas:
            return CollectResult(entities=(), candidates=())
        candidates = tuple(_candidates(metas, schema, ctx))
        entity = Entity(id=PAGE, kind=PAGE, urls=_urls(metas, ctx), parent=None)
        return CollectResult(entities=(entity,), candidates=candidates)


def price_currencies(page: ParsedPage) -> list[str]:
    """The `product:price:currency` values the page writes, in document order, read as `_metas` reads every OGP
    property."""
    return [meta.content for meta in _metas(page) if meta.property == _CURRENCY]


def _metas(page: ParsedPage) -> list[_Meta]:
    """The OGP properties this collector reads, in document order. OGP writes properties in RDFa's `property`
    attribute; the HTML Standard's `name` attribute is read the same way (the `meta:` locator, SPEC-05 §4.3)."""
    metas: list[_Meta] = []
    for node in page.tree.css("meta"):
        attributes = node.attributes
        key = attributes.get("property") or attributes.get("name")
        content = attributes.get("content")
        if key in _READ and content is not None:
            metas.append(_Meta(key, content))
    return metas


def _candidates(metas: Sequence[_Meta], schema: SchemaDef, ctx: Context) -> Iterator[Candidate]:
    for name, spec in schema.fields.items():
        if (found := _value(metas, spec)) is not None:
            yield Candidate(
                field=name,
                entity_id=PAGE,
                source_kind="og",
                raw=found.raw,
                normalized=normalize(found.raw, spec, ctx),
                locator=found.locator,
                independent=True,
            )


def _value(metas: Sequence[_Meta], spec: FieldSpec) -> _Value | None:
    """The value of the table row that fits `spec`'s role and type; a list field is matched by its item's type."""
    role = _role(spec)
    item = spec.item if spec.type is FieldType.LIST else None
    value_type = (item or spec).type
    if role == "price" and value_type is FieldType.MONEY:
        return _price(metas)
    for row in _TABLE:
        if row.role == role and value_type is row.type:
            return _first_or_all([m for m in metas if m.property in row.properties], as_list=item is not None)
    return None


def _role(spec: FieldSpec) -> str | None:
    """The one property a `schema_org` path names on its root type (`Offer.price+priceCurrency` gives `price`), or
    `None` when the path goes through another object."""
    if spec.schema_org is None:
        return None
    steps = spec.schema_org.split("+", 1)[0].split(".")
    return steps[1] if len(steps) == 2 else None


def _first_or_all(found: Sequence[_Meta], *, as_list: bool) -> _Value | None:
    """Open Graph protocol, "Arrays": a property may repeat, and the first tag, top to bottom, is preferred in a
    conflict. A scalar field takes that first value; a list field takes them all, in document order. The locator names
    the first."""
    if not found:
        return None
    raw: JsonValue = [m.content for m in found] if as_list else found[0].content
    return _Value(raw, f"meta:{found[0].property}")


def _price(metas: Sequence[_Meta]) -> _Value | None:
    """The first price amount with the first currency, in the money normalizer's structured form. A missing currency
    is left out, never filled in (C7), so the candidate declines."""
    amounts = [m.content for m in metas if m.property == _AMOUNT]
    if not amounts:
        return None
    raw: dict[str, JsonValue] = {"amount": amounts[0]}
    if currencies := [m.content for m in metas if m.property == _CURRENCY]:
        raw["currency"] = currencies[0]
    return _Value(raw, f"meta:{_AMOUNT}")


def _urls(metas: Sequence[_Meta], ctx: Context) -> tuple[str, ...]:
    """The page entity's URL: the first `og:url` (Open Graph protocol: the object's canonical URL)."""
    first = next((m.content for m in metas if m.property == _OG_URL), None)
    result = None if first is None else normalize(first, _URL, ctx)
    return (result.value,) if isinstance(result, Ok) and isinstance(result.value, str) else ()
