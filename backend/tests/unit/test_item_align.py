"""The item layer's align step (listings spec, "Rows from blocks"): which document a block leads to, what names it, and
which values it gives, from structure, types and standards only. Pages are synthetic (RFC 2606 names)."""

from datetime import UTC, datetime

import pytest
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


def test_a_struck_former_price_is_not_the_price_and_two_shown_prices_decline() -> None:
    # HTML Standard §4.5.4 `s`, §4.7.2 `del`: text no longer accurate.
    struck = '<li class="c"><a href="/p/{i}">Kettle {i}</a><del>{i}9.99 EUR</del> <span>1{i}.50 EUR</span></li>'
    two = '<li class="c"><a href="/p/{i}">Kettle {i}</a><span>{i}9.99 EUR</span> <span>1{i}.50 EUR</span></li>'

    assert [row["price"] for row in _rows(_repeat(struck))] == [
        {"amount": f"1{i}.50", "currency": "EUR"} for i in range(4)
    ]
    only_struck = '<li class="c"><a href="/p/{i}">Kettle {i}</a><div><s>{i}9.99 EUR</s></div></li>'
    assert all("price" not in row for row in _rows(_repeat(only_struck)))
    (group,) = _groups(_repeat(two))
    prices = [c.normalized for c in group.candidates if c.field == "price"]
    assert len(prices) == 4
    assert all(isinstance(p, Ambiguous) and p.reason == AMBIGUOUS_IN_BLOCK for p in prices)


def test_adjacent_elements_digits_are_two_numbers_and_own_text_beside_a_child_price_is_read() -> None:
    # `<span>EUR 10.99</span><span>20</span>` renders `EUR 10.9920` with no space: two text nodes are a token boundary.
    joined = '<li class="c"><a href="/p/{i}">Kettle {i}</a><div><span>EUR 1{i}.99</span><span>20</span></div></li>'
    # A former price in a child element and the current one as the parent's own text: two prices, so none.
    nested = '<li class="c"><a href="/p/{i}">Kettle {i}</a><span><span>{i}9.99 EUR</span> now 1{i}.50 EUR</span></li>'

    assert [row["price"] for row in _rows(_repeat(joined))] == [
        {"amount": f"1{i}.99", "currency": "EUR"} for i in range(4)
    ]
    (group,) = _groups(_repeat(nested))
    prices = [c.normalized for c in group.candidates if c.field == "price"]
    assert len(prices) == 4
    assert all(isinstance(p, Ambiguous) and p.reason == AMBIGUOUS_IN_BLOCK for p in prices)


def test_a_name_the_item_states_in_attributes_is_kept_where_the_card_shows_it_over_several_lines() -> None:
    # WAI-ARIA Accessible Name 1.2 and WCAG 2.1 SC 2.5.3 Label in Name: an overlay link's `aria-label` beats a size
    # picker's one-line link; a template's unshown `Details of` goes, an unshown trailing code stays.
    overlay = (
        '<li class="c"><a href="/p/{i}" aria-label="Details of Runner {i} Blue Code{i}"></a>'
        '<div>Runner {i}</div><div>Blue</div><a href="/p/{i}">36 37 38</a><span>1{i}.00 EUR</span></li>'
    )
    # One link of several lines: the image's `alt`, shown as two lines, names the item.
    split = (
        '<li class="c"><a href="/p/{i}"><img src="/i/{i}.jpg" alt="Maker {i} Chair"><p>Maker {i}</p><p>Chair</p></a>'
        "</li>"
    )
    # A line cut short by an ellipsis stands for the stated name it begins.
    cut = '<li class="c"><a href="/p/{i}"><img src="/i/{i}.jpg" alt="Lamp {i} with brass base">Lamp {i} with…</a></li>'
    # The stated name's leading words are a line of their own above the rest, a size line between: a designer line,
    # not the name's visible label, which is the product line.
    apart = (
        '<li class="c"><a href="/p/{i}"><img src="/i/{i}.jpg" alt="{m} Wool Coat {i}"><p>{m}</p><p>xs</p>'
        "<p>Wool Coat {i}</p></a><p>1{i}.00 EUR</p></li>"
    )
    makers = ("Alder", "Birch", "Cedar", "Dogwood")

    assert [row["title"] for row in _rows(_repeat(overlay))] == [f"Runner {i} Blue Code{i}" for i in range(4)]
    assert [row["title"] for row in _rows(_repeat(split))] == [f"Maker {i} Chair" for i in range(4)]
    assert [row["title"] for row in _rows(_repeat(cut))] == [f"Lamp {i} with brass base" for i in range(4)]
    apart_body = "<ul>" + "".join(apart.format(i=i, m=m) for i, m in enumerate(makers)) + "</ul>"
    assert [row["title"] for row in _rows(apart_body)] == [f"Wool Coat {i}" for i in range(4)]


def test_a_stated_name_running_over_the_price_is_the_cards_text_and_a_link_name_runs_on_as_pictured() -> None:
    # A name holds no price: an overlay link labelled with the whole card's text (a badge, the heading, the price,
    # unshown colours) is not its name, even where two cards share a heading (HTML Standard §4.3.6) that then names it.
    whole = (
        '<li class="c"><a href="/p/{i}" aria-label="New Coat {n} 1{i}.00 EUR In {i} colours"></a>'
        "<p>New</p><h3>Coat {n}</h3><span>1{i}.00 EUR</span></li>"
    )
    body = "<ul>" + "".join(whole.format(i=i, n=min(i, 2)) for i in range(4)) + "</ul>"
    # WCAG 2.1 SC 2.5.3: the item's stated name (a hidden carousel's `alt`) holds the link's line and the variant line
    # below it, not the colour line after.
    variant = (
        '<li class="c"><div hidden><img src="/i/{i}.jpg" alt="Clog {i} Suede Leather - main view"></div>'
        '<a href="/p/{i}">Clog {i}</a><p>Suede Leather</p><p>Taupe</p><span>1{i}.00 EUR</span></li>'
    )
    # RFC 3986 §3.4: a card's links lead to its item refined by a query, and one card's button to the item itself;
    # its picture's label names it, not the button's.
    card = (
        '<li class="c"><div><a href="/p/{i}?v=1" aria-label="Big Mug {i}"></a><img src="/i/{i}.jpg" alt="Big Mug {i}">'
        '</div><div><a href="/p/{i}?v=1"><p>Big Mug {i}</p><p>Stoneware</p></a><span>1{i}.00 EUR</span>{cta}</div></li>'
    )
    cta = '<div><a href="/p/3" aria-label="Add to cart"><span>Add to cart</span></a></div>'
    button = "<ul>" + "".join(card.format(i=i, cta=cta if i == 3 else "") for i in range(4)) + "</ul>"

    assert [row["title"] for row in _rows(body)] == ["Coat 0", "Coat 1", "Coat 2", "Coat 2"]
    assert [row["title"] for row in _rows(_repeat(variant))] == [f"Clog {i} Suede Leather" for i in range(4)]
    assert [row["title"] for row in _rows(button)] == [f"Big Mug {i}" for i in range(4)]


def test_a_link_showing_its_label_is_named_by_it_and_a_link_running_two_fields_together_by_its_parts() -> None:
    # HTML Standard §4.5.1: a link's content is its label; its `aria-labelledby` naming the card's hidden prices too
    # (WCAG 2.1 SC 2.5.3: the stated name holds the label) is not its name.
    labelled = (
        '<li class="c"><a href="/p/{i}" aria-labelledby="p{i}"><span>Sofa {i}</span></a>'
        '<div id="p{i}" aria-hidden="true">Sofa {i}. Offer 1{i}.00 EUR</div></li>'
    )
    # CSS Text 3: adjacent inline boxes render without a space, so a title and a location run together are two lines a
    # layout sets apart, in every card of the template (here also the last, where a trailing space separates them).
    joined = '<li class="c"><a href="/job/{i}"><span><span>Job {i}{gap}</span><span>City {c}</span></span></a></li>'
    jobs = "<ul>" + "".join(joined.format(i=i, c=i % 2, gap=" " if i == 3 else "") for i in range(4)) + "</ul>"

    assert [row["title"] for row in _rows(_repeat(labelled))] == [f"Sofa {i}" for i in range(4)]
    assert [row["title"] for row in _rows(jobs)] == [f"Job {i}" for i in range(4)]


def test_a_card_that_is_a_link_holding_another_link_is_read_as_the_html_parser_builds_it() -> None:
    # HTML Standard §13.2.6.4.7, the adoption agency algorithm: the inner `a` closes the outer one, which is reopened
    # inside the block; the block's elements and the cleaned text's runs share that one tree.
    card = (
        '<a class="c" href="/job/{i}"><div><h4>Job {i}</h4><p>Posted {i}</p>'
        '<div>Pay {i}<br>Hours {i} <a href="/job/{i}">See more</a></div></div></a>'
    )

    assert [row["title"] for row in _rows("<div>" + "".join(card.format(i=i) for i in range(4)) + "</div>")] == [
        f"Job {i}" for i in range(4)
    ]


def test_a_card_showing_a_second_amount_off_the_aligned_place_declines() -> None:
    # C7: the price place shows a "worth" amount in two tiles whose offer price sits in their button instead.
    tile = (
        '<li class="c"><a href="/p/{i}">Set {i}</a><div><div>{shown} EUR</div></div><a href="/p/{i}">{button}</a></li>'
    )
    tiles = [tile.replace("{shown}", "1{i}.00").replace("{button}", "Buy"), tile.replace("{shown}", "9{i}.00")]
    tiles[1] = tiles[1].replace("{button}", "2{i}.00 EUR")
    body = "<ul>" + "".join(tiles[i >= 3].format(i=i) for i in range(5)) + "</ul>"

    (group,) = _groups(body)
    prices = [c.normalized for c in group.candidates if c.field == "price"]
    assert [p.value if isinstance(p, Ok) else p for p in prices[:3]] == [
        {"amount": f"1{i}.00", "currency": "EUR"} for i in range(3)
    ]
    assert all(isinstance(p, Ambiguous) and p.reason == AMBIGUOUS_IN_BLOCK for p in prices[3:])


def test_options_a_drop_down_list_does_not_display_are_not_the_cards_values() -> None:
    # HTML Standard §4.10.7: a drop-down `select` shows its selected option only; the others are choices (add-ons).
    card = (
        '<li class="c"><a href="/p/{i}">Lamp {i}</a><span>1{i}.00 EUR</span><select>'
        "<option selected>No plan</option><option>Plan 4{i}.95 EUR</option></select></li>"
    )

    assert [row["price"] for row in _rows(_repeat(card))] == [
        {"amount": f"1{i}.00", "currency": "EUR"} for i in range(4)
    ]


def test_helper_text_every_card_repeats_inside_the_name_is_the_templates() -> None:
    # DEPTA: a node whose value never varies across the records is the template's (a screen-reader-only phrase).
    card = '<li class="c"><a href="/p/{i}"><span class="sr">View product</span> Boot {i}</a><b>1{i}.00 EUR</b></li>'

    assert [row["title"] for row in _rows(_repeat(card))] == [f"Boot {i}" for i in range(4)]


def test_a_card_the_chosen_rule_does_not_name_reads_the_line_at_the_groups_name_path() -> None:
    # DEPTA alignment by tag path: a sold-out card's second heading leaves `_heading` nothing; the `h3` path names it.
    card = '<li class="c"><a href="/p/{i}"><img src="/i/{i}.jpg"><h3>Tea {i}</h3><span>1{i}.00 EUR</span></a></li>'
    sold = (
        '<li class="c"><a href="/p/9"><img src="/i/9.jpg"><h2>Sold out</h2><h3>Tea 9</h3><span>19.00 EUR</span></a>'
        "</li>"
    )
    body = "<ul>" + "".join(card.format(i=i) for i in range(4)) + sold + "</ul>"

    assert [row.get("title") for row in _rows(body)] == [*(f"Tea {i}" for i in range(4)), "Tea 9"]


def test_a_card_linking_its_item_its_author_and_a_shared_vendor_takes_the_item_at_the_groups_link_place() -> None:
    # DEPTA alignment: a vendor page every card links to is the template's; the item's link is at the place where a
    # quorum of the cards link to a document of their own, a link holding the card's image first.
    body = _repeat(
        '<li class="c"><p>by <a href="/author/{i}">Author {i}</a> at <a href="/vendor">Vendor</a></p>'
        '<a href="/p/{i}"><img src="/i/{i}.jpg" alt=""></a><div><a href="/p/{i}">Book {i}</a></div>'
        "<span>1{i}.50 EUR</span></li>"
    )

    assert [row["url"] for row in _rows(body)] == [_url(f"/p/{i}") for i in range(4)]


def test_a_card_whose_item_author_and_more_links_share_one_tag_path_takes_the_first_of_them() -> None:
    # DEPTA alignment: like elements of one template keep their order, so the title link, the author link and the
    # "more" link written into like elements are three places.
    body = _repeat(
        '<li class="c"><div><div><a href="/p/{i}?r=x">Book {i}</a></div><div>by <a href="/author/{i}">A {i}</a></div>'
        '</div><span>1{i}.50 EUR</span><div><div><a href="/p/{i}/all?r=x">All editions</a></div></div></li>'
    )

    assert [row["url"] for row in _rows(body)] == [_url(f"/p/{i}?r=x") for i in range(4)]


@pytest.mark.parametrize("current", ['href="/search"', 'href="/c/0" aria-current="page"'])
def test_a_group_holding_the_current_page_is_navigation_not_rows(current: str) -> None:
    # WAI-ARIA 1.2 `aria-current="page"`; a link to this very URL: the group lists the page among its documents.
    tile = '<li class="c"><a {link}><img src="/t/{i}.jpg" alt=""> Category {i}</a></li>'
    body = "<ul>" + "".join(tile.format(link=current if i == 0 else f'href="/c/{i}"', i=i) for i in range(4)) + "</ul>"

    assert _groups(body) == ()


@pytest.mark.parametrize("copy", ["nav", "twice"])
@pytest.mark.parametrize(("price", "rows"), [("", 0), ("<span>1{i}.50 EUR</span>", 4)])
def test_tiles_leading_where_the_menu_or_their_copy_leads_are_navigation_unless_they_show_typed_values(
    copy: str, price: str, rows: int
) -> None:
    # The site's chrome (HTML Standard `nav`) links three of the four documents, or the content shows the same tiles
    # again in another container (a desktop and a mobile copy): the site's sections, not the page's items.
    menu = "<nav><ul>" + "".join(f'<li><a href="/c/{i}">Category {i}</a></li>' for i in range(3)) + "</ul></nav>"
    tile = '<li class="c"><a href="/c/{i}"><img src="/t/{i}.jpg" alt=""> Category {i}</a>' + price + "</li>"
    body = menu + _repeat(tile) if copy == "nav" else f"<div>{_repeat(tile)}</div><div>{_repeat(tile)}</div>"

    assert len(_rows(body)) == rows


def test_lists_that_different_sections_hold_are_no_items_own_lists() -> None:
    jobs = "".join(f'<li class="job"><h3><a href="/job/{n}">Job {n}</a></h3><p>Remote</p></li>' for n in range(3))
    pay = "".join(f'<a class="pay" href="/pay/{n}"><b>Role {n}</b><i>9{n} USD</i></a>' for n in range(3))
    body = (
        f'<section class="s"><h2>Jobs</h2><div><ul>{jobs}</ul></div><a href="/jobs">All jobs</a></section>'
        f'<section class="s"><h2>Pay</h2><div><div>{pay}</div></div><a href="/pay">All pay</a></section>'
        '<section class="s"><h2>About</h2><p>Text</p><a href="/about">About</a></section>'
    )

    assert [row["url"] for row in _rows(body, _schema(title=_TITLE, url=_URL))] == [_url(f"/job/{n}") for n in range(3)]
