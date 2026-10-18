"""The text of a listing's items (D-1478): the cleaned text's spans of the page's repeated item blocks, mapped back to
the cleaned text's offsets. Synthetic pages only."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.content.item_text import Piece, TextView, item_text
from crawlerai.content.page import ParsedPage

MENU = "".join(f'<div class="menu-entry"><span>Section {n}</span></div>' for n in range(40))


def _card(n: int) -> str:
    return (
        f'<li class="card"><a href="/p/{n}"><img src="/i/{n}.jpg" alt=""></a>'
        f"<h3>Widget {n}</h3><span>{n}.50 EUR</span></li>"
    )


def _listing(cards: int, *, before: str = MENU) -> ParsedPage:
    grid = "".join(_card(n) for n in range(1, cards + 1))
    return ParsedPage(f"<html><body>{before}<main><ul>{grid}</ul></main><footer>Imprint</footer></body></html>")


def test_the_item_text_is_the_items_and_nothing_around_them() -> None:
    page = _listing(4)

    view = item_text(page)

    assert view is not None
    assert view.text == "\n".join(f"Widget {n}\n{n}.50 EUR" for n in range(1, 5))
    assert "Section" not in view.text
    assert "Imprint" not in view.text


def test_every_piece_is_the_cleaned_text_at_its_offsets() -> None:
    page = _listing(5)

    view = item_text(page)

    assert view is not None
    assert len(view.pieces) == 5
    for piece in view.pieces:
        source = page.cleaned_text.text[piece.start : piece.start + piece.length]
        assert view.text[piece.at : piece.at + piece.length] == source


def test_a_span_maps_to_the_cleaned_text_and_one_across_two_items_maps_nowhere() -> None:
    page = _listing(3)
    view = item_text(page)
    assert view is not None

    start = view.text.index("Widget 2")
    located = view.source_span(start, start + len("Widget 2"))
    joined = view.text.index("EUR\nWidget 2")

    assert located is not None
    assert page.cleaned_text.text[located[0] : located[1]] == "Widget 2"
    assert view.source_span(joined, joined + len("EUR\nWidget 2")) is None


def test_a_page_with_too_few_items_has_no_item_text() -> None:
    assert item_text(_listing(2)) is None
    assert item_text(ParsedPage("<html><body><p>Nothing listed</p></body></html>")) is None


def test_the_first_pieces_view_ends_at_its_last_piece() -> None:
    view = item_text(_listing(4))
    assert view is not None

    first = view.first(2)

    assert first.pieces == view.pieces[:2]
    assert first.text == "Widget 1\n1.50 EUR\nWidget 2\n2.50 EUR"
    assert view.first(10) is view


@given(st.text(max_size=60), st.data())
def test_the_whole_view_maps_every_span_to_itself(text: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(0, len(text)))
    end = data.draw(st.integers(start, len(text)))

    assert TextView.whole(text).source_span(start, end) == (start, end)
    assert TextView.whole(text).pieces == (Piece(0, 0, len(text)),)
