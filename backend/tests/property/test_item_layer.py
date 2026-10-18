"""The item layer's align step on synthetic repeated structures (listings spec, "Rows from blocks"): whatever tags,
class tokens and nesting one template uses, every shown block is one row with its own link, name and price; hidden
blocks are no rows; a struck-through former price is not the price; each block's currency is its own. Hosts are RFC
2606 names."""

from dataclasses import dataclass
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from crawlerai.collect.items.align import align
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/list/kettles"
CTX = Context(html_lang="en", captured_at=datetime(2026, 10, 18, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    name="t_listing",
    origin="user",
    status="active",
    page_kind="listing",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "url": FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    },
)
# ISO 4217 codes, written after the amount: a syntax the money normalizer checks whatever the page's language.
_CURRENCIES = ("EUR", "USD", "GBP", "CHF", "JPY")


@dataclass(frozen=True)
class _Item:
    title: str
    cents: int
    currency: str
    hidden: bool
    former: int | None  # a struck-through former price, in cents


_ITEM = st.builds(
    _Item,
    title=st.from_regex(r"[A-Z][a-z]{2,8}( [a-z]{2,8}){0,3}", fullmatch=True),
    cents=st.integers(100, 999_999),
    currency=st.sampled_from(_CURRENCIES),
    hidden=st.booleans(),
    former=st.none() | st.integers(100, 999_999),
)


@dataclass(frozen=True)
class _Template:
    block: str  # the block's tag
    container: str
    shared: tuple[str, ...]  # the class tokens every block carries
    depth: int  # wrappers around the block's content
    heading: bool  # the name link inside a heading, else bare


_TEMPLATE = st.builds(
    _Template,
    block=st.sampled_from(("div", "li", "article", "section")),
    container=st.sampled_from(("div", "section", "main")),
    shared=st.lists(st.from_regex(r"[a-z]{2,6}", fullmatch=True), min_size=1, max_size=3, unique=True).map(tuple),
    depth=st.integers(0, 3),
    heading=st.booleans(),
)


def _amount(cents: int, currency: str) -> str:
    return f"{cents // 100}.{cents % 100:02d} {currency}"


def _title(item: _Item, n: int) -> str:
    # Items' names differ (a name every block repeats is the template's: `test_item_align`).
    return f"{item.title} {n}"


def _block(template: _Template, item: _Item, n: int) -> str:
    link = f'<a href="/p/{n}">{_title(item, n)}</a>'
    name = f"<h3>{link}</h3>" if template.heading else link
    former = "" if item.former is None else f"<s>{_amount(item.former, item.currency)}</s> "
    price = f"<p>{former}<span>{_amount(item.cents, item.currency)}</span></p>"
    content = f'<a href="/p/{n}"><img src="/i/{n}.jpg" alt=""></a>{name}{price}'
    for _ in range(template.depth):
        content = f"<div>{content}</div>"
    classes = " ".join((*template.shared, f"pos-{n}"))
    hidden = " hidden" if item.hidden else ""
    return f'<{template.block} class="{classes}"{hidden}>{content}</{template.block}>'


def _page(template: _Template, items: list[_Item]) -> ParsedPage:
    blocks = "".join(_block(template, item, n) for n, item in enumerate(items))
    inner = f"<ul>{blocks}</ul>" if template.block == "li" else blocks
    return ParsedPage(f"<html><body><h1>Kettles</h1><{template.container}>{inner}</{template.container}></body></html>")


@settings(max_examples=60, deadline=None)
@given(template=_TEMPLATE, items=st.lists(_ITEM, min_size=3, max_size=12))
def test_every_shown_block_is_a_row_with_its_own_link_name_and_price(template: _Template, items: list[_Item]) -> None:
    shown = [(n, item) for n, item in enumerate(items) if not item.hidden]
    groups = align(_page(template, items), SCHEMA, CTX)
    if len(shown) < 3:  # fewer shown blocks than a listing's are no group
        assert all(len(group.blocks) < 3 for group in groups)
        return
    rows = groups[0]
    values = {
        block.link: {
            c.field: c.normalized.value
            for c in rows.candidates
            if c.entity_id == block.entity.id and isinstance(c.normalized, Ok)
        }
        for block in rows.blocks
    }
    expected = {
        f"https://shop.example.test/p/{n}": {
            "url": f"https://shop.example.test/p/{n}",
            "title": _title(item, n),
            "price": {"amount": _amount(item.cents, item.currency).split()[0], "currency": item.currency},
        }
        for n, item in shown
    }
    assert values == expected


@settings(max_examples=40, deadline=None)
@given(template=_TEMPLATE, items=st.lists(_ITEM, min_size=3, max_size=8))
def test_every_value_is_located_at_its_element(template: _Template, items: list[_Item]) -> None:
    page = _page(template, items)
    for group in align(page, SCHEMA, CTX):
        for c in group.candidates:
            assert isinstance(c.normalized, Ok)
            assert c.source_kind == "dom"
            assert c.locator.startswith("dom:/html[1]/")
            (element,) = page.lxml_tree.xpath(c.locator.removeprefix("dom:"))
            assert c.raw in (element.get("href"), " ".join(element.text_content().split()))
