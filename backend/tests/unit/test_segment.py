"""A page's repeated item groups and their one ranking (listings spec, "Item groups"; `acquire.items`,
`content.segment`): sibling blocks one template renders, each holding a hyperlink, read from the document's structure
only, ranked by rendered area when measured, else by what the blocks show. Pages are synthetic (RFC 2606 names)."""

from hypothesis import given
from hypothesis import strategies as st
from lxml import html

from crawlerai.acquire.items import element_path, item_groups, lxml_root
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import rank, shown_blocks


def _page(content: str) -> ParsedPage:
    return ParsedPage(f"<html><body><main><h1>Kettles</h1>{content}</main></body></html>")


def _first(page: ParsedPage) -> tuple[html.HtmlElement, ...]:
    return page.item_groups[0] if page.item_groups else ()


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


def test_a_tile_marked_with_an_extra_token_stays_in_the_group() -> None:
    page = _page(_grid(["tile", "tile", "tile featured", "tile", "tile sale"]))

    assert _hrefs(page) == [f"/p/{i}" for i in range(5)]


def test_siblings_that_share_no_class_token_with_most_others_are_not_grouped() -> None:
    # Three blocks of different templates (no token is on most of them) are not a listing's items.
    page = _page(_grid(["hero", "promo", "story"]))

    assert _first(page) == ()


def test_a_sibling_without_the_tokens_most_share_is_left_out() -> None:
    page = _page(_grid(["tile a", "tile b", "tile c", "banner"]))

    assert _hrefs(page) == ["/p/0", "/p/1", "/p/2"]


def test_a_grid_of_varying_tiles_outranks_a_smaller_pager() -> None:
    pager = '<ol class="pages">' + "".join(f'<li><a href="?page={i}">{i}</a></li>' for i in range(1, 5)) + "</ol>"
    page = _page(_grid([f"tile order-{i}" for i in range(8)]) + pager)

    assert _hrefs(page) == [f"/p/{i}" for i in range(8)]


_TOKEN = st.from_regex(r"[a-z]{1,6}(-\d{1,2})?", fullmatch=True)


@given(
    shared=st.lists(_TOKEN, min_size=1, max_size=4, unique=True),
    extras=st.lists(st.lists(_TOKEN, max_size=3), min_size=3, max_size=20),
)
def test_every_tile_carrying_the_shared_tokens_is_an_item_in_document_order(
    shared: list[str], extras: list[list[str]]
) -> None:
    # Each tile adds tokens of its own to the template's (`_` and its position make them its own): whatever they are,
    # every tile is one of the items.
    classes = [" ".join([*(f"{token}_{i}" for token in extra), *shared]) for i, extra in enumerate(extras)]
    page = _page(_grid(classes))

    assert _hrefs(page) == [f"/p/{i}" for i in range(len(extras))]


def test_a_bare_tag_cloud_does_not_outrank_a_grid_of_richer_items() -> None:
    cloud = '<ul class="cloud">' + "".join(f'<li><a href="/t/{i}">tag{i}</a></li>' for i in range(30)) + "</ul>"
    grid = (
        '<div class="grid">'
        + "".join(
            f'<div class="card"><a href="/p/{i}"><img src="/i/{i}.jpg" alt=""></a><a href="/p/{i}">Kettle {i}</a>'
            f"<span>{i}9.90 EUR</span></div>"
            for i in range(4)
        )
        + "</div>"
    )

    assert _hrefs(_page(cloud + grid)) == [f"/p/{i}" for i in range(4)]
    assert _hrefs(_page(grid + cloud)) == [f"/p/{i}" for i in range(4)]


def test_with_equal_evidence_the_larger_group_wins() -> None:
    small = "".join(f'<p class="a"><a href="/a/{i}">A{i}</a> note</p>' for i in range(3))
    large = "".join(f'<p class="b"><a href="/b/{i}">B{i}</a> note</p>' for i in range(5))

    assert _hrefs(_page(f"<div>{small}</div><div>{large}</div>")) == [f"/b/{i}" for i in range(5)]


def test_a_group_of_bare_links_is_still_found_when_it_is_the_only_one() -> None:
    cloud = '<ul class="cloud">' + "".join(f'<li><a href="/t/{i}">tag{i}</a></li>' for i in range(5)) + "</ul>"

    assert _hrefs(_page(cloud)) == [f"/t/{i}" for i in range(5)]


def test_script_style_and_template_text_is_not_a_run_of_visible_text() -> None:
    # A link-only card that carries script data or a template holds one visible run: its label.
    links = "".join(
        f'<li><a href="/t/{i}">tag{i}</a><script>var n = {i};</script><style>.a {{}}</style>'
        f"<template><b>x</b></template></li>"
        for i in range(4)
    )
    cards = "".join(f'<li><a href="/p/{i}">Kettle {i}</a><span>{i}9.90 EUR</span></li>' for i in range(4))

    assert shown_blocks(_first(_page(f"<ul>{links}</ul>"))) == 0
    assert shown_blocks(_first(_page(f"<ul>{cards}</ul>"))) == 4


def test_measured_areas_rank_a_grid_of_large_cards_over_a_sidebar_of_more_links() -> None:
    # CSSOM View `getBoundingClientRect`: the browser rung's areas, by element path; the sidebar has more blocks.
    side = '<ul class="side">' + "".join(f'<li><a href="/c/{i}">Category {i}</a> x</li>' for i in range(20)) + "</ul>"
    page = _page(side + _grid([f"tile order-{i}" for i in range(6)]))
    groups = item_groups(page.lxml_tree)
    areas = {element_path(b): (300.0 * 400.0 if b.tag == "div" else 200.0 * 20.0) for g in groups for b in g}

    measured = ParsedPage(page.html, item_areas=areas)

    assert _hrefs(measured) == [f"/p/{i}" for i in range(6)]
    assert _hrefs(page) == [f"/c/{i}" for i in range(20)]  # without geometry: as many blocks show more, the larger


def test_a_block_with_no_rendered_area_is_not_one_of_its_groups_blocks() -> None:
    page = _page(_grid([f"tile order-{i}" for i in range(4)]))
    (group,) = item_groups(page.lxml_tree)
    areas = {element_path(block): 0.0 if i == 1 else 100.0 for i, block in enumerate(group)}

    assert _hrefs(ParsedPage(page.html, item_areas=areas)) == ["/p/0", "/p/2", "/p/3"]


def test_a_block_the_html_rendering_rules_hide_is_left_out_without_geometry() -> None:
    # HTML Standard §15.3.1: `[hidden]` is `display: none`; an inline `display: none` hides the block too.
    tiles = [f'<div class="tile"><a href="/p/{i}">Kettle {i}</a><span>{i} EUR</span></div>' for i in range(5)]
    tiles[1] = tiles[1].replace('class="tile"', 'class="tile" hidden')
    tiles[3] = tiles[3].replace('class="tile"', 'class="tile" style="display: none"')

    assert _hrefs(_page(f'<div class="grid">{"".join(tiles)}</div>')) == ["/p/0", "/p/2", "/p/4"]


def test_a_group_left_with_no_rendered_block_is_dropped() -> None:
    page = _page(_grid([f"tile order-{i}" for i in range(3)]))
    groups = item_groups(page.lxml_tree)

    assert rank(groups, dict.fromkeys((element_path(b) for g in groups for b in g), 0.0)) == ()


def test_an_element_path_names_the_same_element_in_a_parse_of_the_same_document() -> None:
    # DOM Standard `document.evaluate`: the browser evaluates the path on the document the capture keeps.
    page = _page("<!-- a comment --><p>x</p>" + _grid([f"tile order-{i}" for i in range(4)]))
    again = lxml_root(page.html)

    for block in _first(page):
        (found,) = again.xpath(element_path(block))
        assert next(found.iter("a")).get("href") == next(block.iter("a")).get("href")


def test_a_block_past_the_measuring_cap_has_no_area_entry_and_stays() -> None:
    # The browser rung measures at most 2,000 blocks; an unmeasured block is no unrendered one.
    page = _page(_grid([f"tile order-{i}" for i in range(4)]))
    (group,) = item_groups(page.lxml_tree)
    areas = {element_path(block): 100.0 for block in group[:2]}

    assert _hrefs(ParsedPage(page.html, item_areas=areas)) == [f"/p/{i}" for i in range(4)]
