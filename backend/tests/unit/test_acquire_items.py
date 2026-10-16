"""A page's repeated items (`acquire.items`, ARCHITECTURE §8.6): sibling blocks one template renders, each holding a
hyperlink, read from the document's structure only. Pages are synthetic."""

from hypothesis import given
from hypothesis import strategies as st
from lxml import html

from crawlerai.acquire.items import item_blocks


def _page(content: str) -> html.HtmlElement:
    return html.document_fromstring(f"<html><body><main><h1>Kettles</h1>{content}</main></body></html>")


def _hrefs(page: html.HtmlElement) -> list[str | None]:
    return [next(block.iter("a")).get("href") for block in item_blocks(page)]


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

    assert item_blocks(page) == ()


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
