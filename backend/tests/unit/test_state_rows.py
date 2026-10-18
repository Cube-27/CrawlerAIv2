"""Rows from the page's state JSON (listings spec, "Rows from page state"): an array of objects whose values the page
renders gives a listing's rows when no other source does, each value grounded in the page's text or links. Pages are
synthetic (RFC 2606 names)."""

import json
from typing import Any

from pydantic import JsonValue

from tests.unit.test_pipeline import COMMITTED, _html, _listing, _row_values


def _state(rows: list[dict[str, Any]]) -> str:
    return f'<script type="application/json">{json.dumps({"page": {"items": rows}})}</script>'


def _url(n: int) -> str:
    return f"https://shop.example.test/p/{n}"


def _price(n: int) -> dict[str, JsonValue]:
    return {"amount": f"{n}.50", "currency": "EUR"}


def _item(n: int, **extra: Any) -> dict[str, Any]:
    return {"id": n, "name": f"Widget {n}", "url": f"/p/{n}", "price": f"{n}.50 EUR", **extra}


# The items' text, shown without links: no group of item blocks aligns.
_SHOWN = "".join(f"<p>Widget {n} costs {n}.50 EUR</p>" for n in (1, 2, 3))


def test_state_rows_the_page_shows_are_the_rows_with_state_evidence() -> None:
    result = _listing(_html(body=_state([_item(n) for n in (1, 2, 3)]) + _SHOWN), data=COMMITTED)

    assert _row_values(result) == [{"title": f"Widget {n}", "url": _url(n), "price": _price(n)} for n in (1, 2, 3)]
    assert {row["title"].evidence for row in result.rows} == {"state"}
    assert str(result.rows[0]["title"].locator).endswith("$['page']['items'][0]['name']")


def test_state_rows_the_page_does_not_render_give_no_rows() -> None:
    result = _listing(_html(body=_state([_item(n) for n in (1, 2, 3)]) + "<p>Nothing here</p>"), data=COMMITTED)

    assert result.rows == ()


def test_a_value_the_page_does_not_show_is_not_read() -> None:
    items = [_item(n, price=f"{n}9.00 EUR") for n in (1, 2, 3)]

    result = _listing(_html(body=_state(items) + _SHOWN), data=COMMITTED)

    assert [sorted(row) for row in _row_values(result)] == [["title", "url"]] * 3
