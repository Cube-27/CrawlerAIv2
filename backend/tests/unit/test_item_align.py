"""The item layer's align step (listings spec, "Rows from blocks"): which document a block leads to, what names it, and
which values it gives, from structure, types and standards only. Pages are synthetic (RFC 2606 names)."""

from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.collect.items.align import AMBIGUOUS_IN_BLOCK, Items, align
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Ambiguous, Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://jobs.example.test/search"
CTX = Context(html_lang="en", captured_at=datetime(2026, 10, 18, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
_TITLE = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
_URL = FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url")
_PRICE = FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency")


def _schema(page_kind: str = "listing", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        name="t_listing",
        origin="user",
        status="active",
        page_kind=page_kind,  # type: ignore[arg-type]
        fields=fields or {"title": _TITLE, "url": _URL, "price": _PRICE},
    )


LISTING = _schema()


def _groups(body: str, schema: SchemaDef = LISTING) -> tuple[Items, ...]:
    return align(ParsedPage(f"<html><body><h1>Results</h1>{body}</body></html>"), schema, CTX)


def _rows(body: str, schema: SchemaDef = LISTING) -> list[dict[str, JsonValue]]:
    groups = _groups(body, schema)
    if not groups:
        return []
    first = groups[0]
    return [
        {
            c.field: c.normalized.value
            for c in first.candidates
            if c.entity_id == block.entity.id and isinstance(c.normalized, Ok)
        }
        for block in first.blocks
    ]


def _repeat(block: str, n: int = 4) -> str:
    return "<ul>" + "".join(block.format(i=i) for i in range(n)) + "</ul>"


def _url(path: str) -> str:
    return f"https://jobs.example.test{path}"


def test_a_block_linking_to_its_item_and_its_seller_takes_the_link_its_heading_holds() -> None:
    # HTML Standard §4.3.6: a heading labels the content it heads.
    body = _repeat('<li class="r"><h2><a href="/job/{i}">Job {i}</a></h2><a href="/employer/{i}">Employer {i}</a></li>')

    assert [row["url"] for row in _rows(body)] == [_url(f"/job/{i}") for i in range(4)]


def test_without_a_heading_the_link_labelled_by_the_blocks_text_is_the_items() -> None:
    # HTML Standard §4.5.1: an `a` element's content labels its link; the seller's link labels a logo only.
    block = (
        '<li class="r"><a href="/co/{i}"><img src="/logo/{i}.png" alt=""></a>'
        '<a href="/job/{i}"><span>Engineer number {i}</span> <span>Remote, worldwide</span></a></li>'
    )

    assert [row["url"] for row in _rows(_repeat(block))] == [_url(f"/job/{i}") for i in range(4)]


def test_a_pager_or_a_list_of_bare_links_gives_no_rows() -> None:
    # A pager leads to this page in another state (RFC 3986 §3.3); bare links show nothing beyond their label.
    pager = _repeat('<li class="p"><a href="/search?page={i}">{i}</a> results</li>', 6)
    cloud = _repeat('<li class="t"><a href="/tag/{i}">tag {i}</a></li>', 8)

    assert (_groups(pager), _groups(cloud)) == ((), ())


def test_an_items_share_buttons_do_not_hide_its_own_link() -> None:
    share = (
        '<div class="s">'
        + "".join(f'<a href="https://social{k}.example.test/share?u={{i}}">S{k}</a>' for k in range(4))
        + "</div>"
    )
    block = '<li class="r"><a href="/job/{i}">Job {i}</a><span>Remote</span>' + share + "</li>"

    assert [row["url"] for row in _rows(_repeat(block))] == [_url(f"/job/{i}") for i in range(4)]


def test_sections_each_holding_a_list_of_items_are_no_items_themselves() -> None:
    section = (
        '<section class="dept"><h2>Department {d}</h2><ul>'
        + "".join(
            f'<li class="job"><a href="/job/{{d}}-{n}">Job {{d}}-{n}</a><span>Remote</span></li>' for n in range(4)
        )
        + "</ul></section>"
    )
    body = "".join(section.format(d=d) for d in range(3))

    rows = _rows(body)
    assert len(rows) == 4
    assert all(str(row["url"]).startswith(_url("/job/")) for row in rows)


def test_an_overlay_links_label_names_the_item_by_the_text_the_block_shows() -> None:
    # WCAG 2.1 SC 2.5.3 (Label in Name): the accessible name contains the visible label.
    block = (
        '<li class="c"><a href="/p/{i}" aria-label="More about Kettle {i} here"></a>'
        '<img src="/i/{i}.jpg" alt=""><div>Kettle {i}</div><div>{i}9.50 EUR</div></li>'
    )

    assert [row["title"] for row in _rows(_repeat(block))] == [f"Kettle {i}" for i in range(4)]


def test_a_call_to_action_every_block_repeats_names_nothing_and_the_heading_does() -> None:
    block = '<li class="c"><h3>Kettle {i}</h3><a href="/p/{i}">View details</a><span>{i}9.50 EUR</span></li>'
    only_cta = '<li class="c"><a href="/p/{i}">View details</a><span>{i}9.50 EUR</span></li>'

    assert [row["title"] for row in _rows(_repeat(block))] == [f"Kettle {i}" for i in range(4)]
    assert ["title" in row for row in _rows(_repeat(only_cta))] == [False] * 4


def test_a_link_labelled_with_its_own_address_names_nothing() -> None:
    # A URL is not prose (RFC 3986 §4.3).
    block = '<li class="c"><a href="/p/{i}">https://jobs.example.test/p/{i}</a><span>{i}9.50 EUR</span></li>'

    assert ["title" in row for row in _rows(_repeat(block))] == [False] * 4


def test_a_card_that_is_one_link_is_named_by_the_text_its_image_names() -> None:
    # HTML Standard §4.8.4.4: an image's `alt` is its text alternative; the card's text repeating it is the name.
    block = (
        '<li class="c"><a href="/p/{i}"><img src="/i/{i}.jpg" alt="Kettle {i}">'
        "<div>Kettle {i}</div><div>Free delivery</div><div>{i}9.50 EUR</div></a></li>"
    )

    assert [row["title"] for row in _rows(_repeat(block))] == [f"Kettle {i}" for i in range(4)]


def test_a_struck_former_price_is_not_the_price_and_two_shown_prices_decline() -> None:
    # HTML Standard §4.5.4 `s`, §4.7.2 `del`: text no longer accurate.
    struck = '<li class="c"><a href="/p/{i}">Kettle {i}</a><del>{i}9.99 EUR</del> <span>1{i}.50 EUR</span></li>'
    two = '<li class="c"><a href="/p/{i}">Kettle {i}</a><span>{i}9.99 EUR</span> <span>1{i}.50 EUR</span></li>'

    assert [row["price"] for row in _rows(_repeat(struck))] == [
        {"amount": f"1{i}.50", "currency": "EUR"} for i in range(4)
    ]
    (group,) = _groups(_repeat(two))
    prices = [c.normalized for c in group.candidates if c.field == "price"]
    assert len(prices) == 4
    assert all(isinstance(p, Ambiguous) and p.reason == AMBIGUOUS_IN_BLOCK for p in prices)


def test_a_value_every_block_repeats_is_the_templates_beside_varying_prices() -> None:
    block = '<li class="c"><a href="/p/{i}">Kettle {i}</a><span>1{i}.50 EUR</span><small>Free over 50 EUR</small></li>'

    assert [row["price"] for row in _rows(_repeat(block))] == [
        {"amount": f"1{i}.50", "currency": "EUR"} for i in range(4)
    ]


def test_two_blocks_leading_to_one_item_are_one_row() -> None:
    blocks = "".join(
        f'<li class="c"><a href="/p/{i % 3}">Kettle {i % 3}</a><span>{i % 3}5.00 EUR</span></li>' for i in range(5)
    )

    assert [row["url"] for row in _rows(f"<ul>{blocks}</ul>")] == [_url(f"/p/{i}") for i in range(3)]


def test_the_group_aligning_more_fields_comes_first() -> None:
    profiles = _repeat('<li class="pr"><a href="/people/{i}">Person {i}</a><span>Recruiter</span></li>', 8)
    products = _repeat('<li class="pd"><a href="/p/{i}">Kettle {i}</a><span>{i}5.00 EUR</span></li>', 4)

    groups = _groups(profiles + products)
    assert [len(g.blocks) for g in groups] == [4, 8]
    assert groups[0].blocks[0].link == _url("/p/0")


def test_a_detail_schema_or_one_without_an_item_url_reads_no_blocks() -> None:
    body = _repeat('<li class="c"><a href="/p/{i}">Kettle {i}</a><span>{i}5.00 EUR</span></li>')

    assert _groups(body, _schema("detail", title=_TITLE)) == ()
    assert _groups(body, _schema(title=_TITLE, price=_PRICE)) == ()
