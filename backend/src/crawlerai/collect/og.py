"""The OpenGraph collector (extraction spec): `og:*` and `product:*` meta properties.

OpenGraph names no entity types, so every value describes the page's one object: the entity is `page`, and its URL is
`og:url`. A property maps to a field through the fixed table below, keyed by the OGP property and the field's role:
its type and the one schema.org property its `schema_org` path names on the root type (`Product.name` has the role
`name`; `Product.brand.name` names the brand's name, not the object's, so it has none). The table is justified by the
OGP specification (C2), not by any page.

OGP's basic metadata (`og:title`, `og:image`, `og:url`) describes one object. Client-rendered pages often keep the
site's own defaults there: an `og:title` that names the site (`site_names`) says the object is the site, so its
`og:title`, `og:image` and `og:description` are not the entity's. A title that ends in separator segments naming the
site is read without them.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace

from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate, CollectResult, Entity
from crawlerai.collect.schema_org_map import parse_paths
from crawlerai.collect.site_names import SiteNames
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
_TITLE = "og:title"
_IMAGES = ("og:image", "og:image:url")
_DESCRIPTION = "og:description"
# Open Graph protocol, "Basic Metadata": `og:title` is the object's title, `og:image` its image, `og:url` its
# canonical URL; "Structured Properties": `og:image:url` is identical to `og:image`; "Optional Metadata":
# `og:description` is "a one to two sentence description" of the object, prose for a long_text description. The OGP
# `product` namespace: `product:availability` is the item's availability. `product:price:*` is the money row, read by
# `_price`. Only properties OGP defines are read (owner, Appendix A #48); others are left to learned configs.
_TABLE = (
    _Row((_TITLE,), FieldType.TEXT, "name"),
    _Row(_IMAGES, FieldType.IMAGE_URL, "image"),
    _Row((_OG_URL,), FieldType.URL, "url"),
    _Row((_DESCRIPTION,), FieldType.LONG_TEXT, "description"),
    _Row(("product:availability",), FieldType.ENUM, "availability"),
)
# OGP `product` namespace: `product:price:amount` is the price and `product:price:currency` its ISO 4217 code.
_AMOUNT, _CURRENCY = "product:price:amount", "product:price:currency"
# OGP "Optional Metadata": `og:site_name` is "the name of the overall site" the object is part of.
_SITE_NAME = "og:site_name"
_READ = frozenset(p for row in _TABLE for p in row.properties) | {_AMOUNT, _CURRENCY, _SITE_NAME}
_SITE_TITLE = "og: og:title names the site, so og:title, og:image and og:description are not read"
# The values a site-default block holds about the site rather than the object.
_SITE_DEFAULTS = (_TITLE, *_IMAGES, _DESCRIPTION)


@dataclass(frozen=True, slots=True)
class _Meta:
    """One OGP property; `reading` is the content as a field reads it (a title without its site segments)."""

    property: str
    content: str
    reading: str


@dataclass(frozen=True, slots=True)
class _Value:
    raw: JsonValue
    locator: str
    reading: JsonValue  # what is normalized: `raw`, or a title without its site segments


class OpenGraphCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        metas = _metas(page)
        if not metas:
            return CollectResult(entities=(), candidates=())
        metas, diagnostics = _without_site_values(metas, ctx)
        candidates = tuple(_candidates(metas, schema, ctx))
        entity = Entity(id=PAGE, types=(PAGE,), urls=_urls(metas, ctx), parent=None)
        return CollectResult(entities=(entity,), candidates=candidates, diagnostics=diagnostics)


def price_currencies(page: ParsedPage) -> list[str]:
    """The `product:price:currency` values the page writes, in document order, read as `_metas` reads every OGP
    property."""
    return [meta.content for meta in _metas(page) if meta.property == _CURRENCY]


def _metas(page: ParsedPage) -> list[_Meta]:
    """The OGP properties this collector reads, in document order. OGP writes properties in RDFa's `property`
    attribute; the HTML Standard's `name` attribute is read the same way (the `meta:` locator, extraction spec)."""
    metas: list[_Meta] = []
    for node in page.tree.css("meta"):
        attributes = node.attributes
        key = attributes.get("property") or attributes.get("name")
        content = attributes.get("content")
        if key in _READ and content is not None:
            metas.append(_Meta(key, content, content))
    return metas


def _without_site_values(metas: list[_Meta], ctx: Context) -> tuple[list[_Meta], tuple[str, ...]]:
    """The metas the fields read: without `og:title`, `og:image` and `og:description` when the (first) title names the
    site, else with each title read without its trailing site segments."""
    title = next((m.content for m in metas if m.property == _TITLE), None)
    if title is None:
        return metas, ()
    site = SiteNames.of([m.content for m in metas if m.property == _SITE_NAME], ctx.page_url)
    if site.names(title):
        return [m for m in metas if m.property not in _SITE_DEFAULTS], (_SITE_TITLE,)
    return [replace(m, reading=site.without_site(m.content)) if m.property == _TITLE else m for m in metas], ()


def _candidates(metas: Sequence[_Meta], schema: SchemaDef, ctx: Context) -> Iterator[Candidate]:
    for name, spec in schema.fields.items():
        if (found := _value(metas, spec)) is not None:
            yield Candidate(
                field=name,
                entity_id=PAGE,
                source_kind="og",
                raw=found.raw,
                normalized=normalize(found.reading, spec, ctx),
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
    """The one property a `schema_org` path names on its root type (`Offer.price+priceCurrency` gives `price`), the
    same in every alternative, or `None` when an alternative goes through another object or the alternatives name
    different properties (variants spec). A row-mapped field's path names rows, so it has no role."""
    if spec.schema_org is None or spec.row_mapped:
        return None
    roles = {path.steps[0] if len(path.steps) == 1 else None for path in parse_paths(spec.schema_org)}
    return roles.pop() if len(roles) == 1 else None


def _first_or_all(found: Sequence[_Meta], *, as_list: bool) -> _Value | None:
    """Open Graph protocol, "Arrays": a property may repeat, and the first tag, top to bottom, is preferred in a
    conflict. A scalar field takes that first value; a list field takes them all, in document order. The locator names
    the first."""
    if not found:
        return None
    raw: JsonValue = [m.content for m in found] if as_list else found[0].content
    reading: JsonValue = [m.reading for m in found] if as_list else found[0].reading
    return _Value(raw, f"meta:{found[0].property}", reading)


def _price(metas: Sequence[_Meta]) -> _Value | None:
    """The first price amount with the first currency, in the money normalizer's structured form. A missing currency
    is left out, never filled in (C7), so the candidate declines."""
    amounts = [m.content for m in metas if m.property == _AMOUNT]
    if not amounts:
        return None
    raw: dict[str, JsonValue] = {"amount": amounts[0]}
    if currencies := [m.content for m in metas if m.property == _CURRENCY]:
        raw["currency"] = currencies[0]
    return _Value(raw, f"meta:{_AMOUNT}", raw)


def _urls(metas: Sequence[_Meta], ctx: Context) -> tuple[str, ...]:
    """The page entity's URL: the first `og:url` (Open Graph protocol: the object's canonical URL)."""
    first = next((m.content for m in metas if m.property == _OG_URL), None)
    result = None if first is None else normalize(first, _URL, ctx)
    return (result.value,) if isinstance(result, Ok) and isinstance(result.value, str) else ()
