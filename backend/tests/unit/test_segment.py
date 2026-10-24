"""A page's repeated item groups and their one ranking (`acquire.items`, `content.segment`): sibling blocks one template
renders, each holding a hyperlink, read from the document's structure
only, ranked by rendered area when measured, else by what the blocks show. Pages are synthetic (RFC 2606 names)."""

from lxml import html

from snowcrawl.acquire.items import element_path, item_groups, shows_more
from snowcrawl.content.page import ParsedPage


def _page(content: str) -> ParsedPage:
    return ParsedPage(f"<html><body><main><h1>Kettles</h1>{content}</main></body></html>")


def _first(page: ParsedPage) -> tuple[html.HtmlElement, ...]:
    return page.item_groups[0] if page.item_groups else ()


def _shown(group: tuple[html.HtmlElement, ...]) -> int:
    """How many of the group's blocks show more than their link."""
    return sum(1 for block in group if shows_more(block))


def _hrefs(page: ParsedPage) -> list[str | None]:
    return [next(block.iter("a")).get("href") for block in _first(page)]


def _grid(classes: list[str]) -> str:
    tiles = "".join(
        f'<div class="{names}"><a href="/p/{i}">Kettle {i}</a><span>{i}9.90 EUR</span></div>'
        for i, names in enumerate(classes)
    )
    return f'<div class="grid">{tiles}</div>'


def test_tiles_whose_class_lists_differ_by_a_per_item_token_are_one_group() -> None:
    # One template renders every tile; a per-item token (its position in the grid) makes each class list unique.
    page = _page(_grid([f"tile span-1 order-{i} bg" for i in range(6)]))

    assert _hrefs(page) == [f"/p/{i}" for i in range(6)]


def test_siblings_that_share_no_class_token_with_most_others_are_not_grouped() -> None:
    # Three blocks of different templates (no token is on most of them) are not a listing's items.
    page = _page(_grid(["hero", "promo", "story"]))

    assert _first(page) == ()


def test_items_in_sibling_sections_of_one_template_are_one_group_however_few_each_holds() -> None:
    # A list split into sections, each a label and its items: sections of one, two and three items are one list.
    sections = "".join(
        f'<div class="team"><div class="label">Team {t}</div>'
        + "".join(f'<div class="job"><a href="/j/{t}{i}">Job {t}{i}</a><span>City</span></div>' for i in range(n))
        + "</div>"
        for t, n in enumerate((1, 2, 3))
    )
    page = _page(f'<div class="board">{sections}</div>')

    assert _hrefs(page) == ["/j/00", "/j/10", "/j/11", "/j/20", "/j/21", "/j/22"]


def test_a_part_each_card_shows_once_is_no_section_run() -> None:
    # Each card's title wrapper is one per card: the cards are the items, not their title wrappers across the grid.
    cards = "".join(
        f'<div class="card"><div class="title"><a href="/p/{i}">Kettle {i}</a></div><span>{i}9.90 EUR</span></div>'
        for i in range(4)
    )
    page = _page(f'<div class="grid">{cards}</div>')

    assert [len(group) for group in page.item_groups] == [4]


def test_a_grid_of_varying_tiles_outranks_a_smaller_pager() -> None:
    pager = '<ol class="pages">' + "".join(f'<li><a href="?page={i}">{i}</a></li>' for i in range(1, 5)) + "</ol>"
    page = _page(_grid([f"tile order-{i}" for i in range(8)]) + pager)

    assert _hrefs(page) == [f"/p/{i}" for i in range(8)]


def test_script_style_and_template_text_is_not_a_run_of_visible_text() -> None:
    # A link-only card that carries script data or a template holds one visible run: its label.
    links = "".join(
        f'<li><a href="/t/{i}">tag{i}</a><script>var n = {i};</script><style>.a {{}}</style>'
        f"<template><b>x</b></template></li>"
        for i in range(4)
    )
    cards = "".join(f'<li><a href="/p/{i}">Kettle {i}</a><span>{i}9.90 EUR</span></li>' for i in range(4))

    assert _shown(_first(_page(f"<ul>{links}</ul>"))) == 0
    assert _shown(_first(_page(f"<ul>{cards}</ul>"))) == 4


def test_measured_areas_rank_a_grid_of_large_cards_over_a_sidebar_of_more_links() -> None:
    # CSSOM View `getBoundingClientRect`: the browser rung's areas, by element path; the sidebar has more blocks.
    side = '<ul class="side">' + "".join(f'<li><a href="/c/{i}">Category {i}</a> x</li>' for i in range(20)) + "</ul>"
    page = _page(side + _grid([f"tile order-{i}" for i in range(6)]))
    groups = item_groups(page.lxml_tree)
    areas = {element_path(b): (300.0 * 400.0 if b.tag == "div" else 200.0 * 20.0) for g in groups for b in g}

    measured = ParsedPage(page.html, item_areas=areas)

    assert _hrefs(measured) == [f"/p/{i}" for i in range(6)]
    assert _hrefs(page) == [f"/c/{i}" for i in range(20)]  # without geometry: as many blocks show more, the larger


def test_a_block_the_html_rendering_rules_hide_is_left_out_without_geometry() -> None:
    # HTML Standard §15.3.1: `[hidden]` is `display: none`; an inline `display: none` hides the block too.
    tiles = [f'<div class="tile"><a href="/p/{i}">Kettle {i}</a><span>{i} EUR</span></div>' for i in range(5)]
    tiles[1] = tiles[1].replace('class="tile"', 'class="tile" hidden')
    tiles[3] = tiles[3].replace('class="tile"', 'class="tile" style="display: none"')

    assert _hrefs(_page(f'<div class="grid">{"".join(tiles)}</div>')) == ["/p/0", "/p/2", "/p/4"]
