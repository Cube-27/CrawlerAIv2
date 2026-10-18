"""The item layer's bind step through the pipeline (listings spec, "Stated rows and blocks", "Row item URL"): stated
rows and blocks become one row per item; state rows bind by URL and lend a key the blocks prove. Pages are synthetic
(RFC 2606 names)."""

import json
from typing import Any

from pydantic import JsonValue

from crawlerai.normalize.base import Ok
from tests.unit.test_pipeline import (
    COMMITTED,
    _html,
    _item_list,
    _listing,
    _row,
    _row_values,
)


def _card(n: int, *, href: str | None = None, title: bool = True, price: str | None = None) -> str:
    name = (
        f'<h3><a href="{href or f"/p/{n}"}">Widget {n}</a></h3>'
        if title
        else f'<a href="{href or f"/p/{n}"}"><img src="/t/{n}.png" alt=""></a>'
    )
    shown = price if price is not None else f"{n}.50 EUR"
    return f'<li class="card"><img src="/i/{n}.jpg" alt="">{name}<span>{shown}</span></li>'


def _cards(*cards: str) -> str:
    return f'<ul class="grid">{"".join(cards)}</ul>'


def _url(n: int, suffix: str = "") -> str:
    return f"https://shop.example.test/p/{n}{suffix}"


def _price(n: int) -> dict[str, JsonValue]:
    return {"amount": f"{n}.50", "currency": "EUR"}


def test_stub_rows_take_their_blocks_titles_prices_and_links() -> None:
    stubs = _item_list(*({"@type": "Product", "url": _url(n)} for n in (1, 2, 3)))

    result = _listing(_html(stubs, body=_cards(*(_card(n) for n in (1, 2, 3)))), data=COMMITTED)

    assert _row_values(result) == [{"title": f"Widget {n}", "url": _url(n), "price": _price(n)} for n in (1, 2, 3)]
    assert {row["title"].source_kind for row in result.rows} == {"dom"}


def test_a_grown_list_extends_the_stated_rows_with_the_blocks_none_names() -> None:
    stated = _item_list(*(_row(n) for n in (1, 2, 3)))

    result = _listing(_html(stated, body=_cards(*(_card(n) for n in range(1, 7)))), data=COMMITTED)

    assert [row["url"] for row in _row_values(result)] == [_url(n) for n in range(1, 7)]
    assert [row["title"].source_kind for row in result.rows[3:]] == ["dom"] * 3


def test_a_stated_url_the_page_links_with_a_trailing_slash_takes_the_blocks_spelling() -> None:
    stated = _item_list(*(_row(n, url=_url(n, "/?ref=list")) for n in (1, 2, 3)))

    result = _listing(_html(stated, body=_cards(*(_card(n) for n in (1, 2, 3)))), data=COMMITTED)

    assert [row["url"] for row in _row_values(result)] == [_url(n) for n in (1, 2, 3)]


def test_a_stated_url_with_another_path_or_more_of_one_parameter_names_another_item() -> None:
    # RFC 3986 §6.2.4: one trailing slash aside, `/p/1//` is another path; a parameter repeated is two values.
    stated = _item_list(_row(1, url=_url(1, "//")), _row(2, url=_url(2, "?c=r&c=r")), _row(3, url=_url(3, "?c=r")))
    cards = _cards(_card(1), _card(2, href="/p/2?c=r&d=1"), _card(3, href="/p/3?c=r&d=1"))

    result = _listing(_html(stated, body=cards), data=COMMITTED)

    # Only the third binds (its query is among its block's); the others and their blocks stay apart.
    assert [row["url"] for row in _row_values(result)][2] == _url(3, "?c=r&d=1")
    assert len(result.rows) == 5


def test_a_block_two_stated_rows_name_binds_neither_and_adds_no_row() -> None:
    # C7: two candidates for one join decline it; the block is not counted as a further item either.
    stated = _item_list(_row(1), _row(1, url=_url(1, "?ref=a")), _row(2), _row(3))

    result = _listing(_html(stated, body=_cards(*(_card(n) for n in (1, 2, 3)))), data=COMMITTED)

    assert len(result.rows) == 4


def test_a_stub_no_block_takes_stays_a_row() -> None:
    stubs = _item_list(*({"@type": "Product", "url": _url(n)} for n in (1, 2, 3, 9)))

    result = _listing(_html(stubs, body=_cards(*(_card(n) for n in (1, 2, 3)))), data=COMMITTED)

    assert [row["url"] for row in _row_values(result)] == [*(_url(n) for n in (1, 2, 3)), _url(9)]


def test_a_blocks_ambiguous_price_publishes_the_option_its_stated_row_agrees_with() -> None:
    stated = _item_list(*(_row(n) for n in (1, 2, 3)))
    cards = _cards(*(_card(n, price=f"{n}.50 EUR</span> <span>{n}.95 EUR") for n in (1, 2, 3)))

    result = _listing(_html(stated, body=cards), data=COMMITTED)

    assert [row["price"] for row in _row_values(result)] == [_price(n) for n in (1, 2, 3)]
    joined = [c for c in result.candidates if c.field == "price" and c.source_kind == "dom"]
    assert [c.normalized for c in joined] == [Ok(_price(n)) for n in (1, 2, 3)]


def test_a_state_key_the_blocks_titles_prove_reads_the_title_of_the_row_whose_block_shows_none() -> None:
    # `collect.induce`: the key whose values equal the blocks' titles on three rows is the title's key for all four. A
    # state value has the evidence bucket `state` and ranks last (resolution spec): the fourth row publishes it.
    state: dict[str, Any] = {"items": [{"label": f"Widget {n}", "path": f"/p/{n}"} for n in (1, 2, 3, 4)]}
    script = f'<script type="application/json">{json.dumps(state)}</script>'
    cards = _cards(*(_card(n, title=n != 4) for n in (1, 2, 3, 4)))

    result = _listing(_html(body=script + cards), data=COMMITTED)

    (induced,) = [c for c in result.candidates if c.field == "title" and c.raw == "Widget 4"]
    assert (induced.source_kind, induced.independent) == ("js_state", False)
    assert induced.locator.endswith("$['items'][3]['label']")
    assert [row.get("title") for row in _row_values(result)] == ["Widget 1", "Widget 2", "Widget 3", "Widget 4"]
    assert result.rows[3]["title"].evidence == "state"


def test_a_products_offer_url_is_its_rows_item_url() -> None:
    # schema.org Offer.url: the row's item URL when the Product states none (listings spec, "Row item URL").
    items = [
        {
            "@type": "Product",
            "name": f"Widget {n}",
            "offers": {"@type": "Offer", "url": _url(n), "price": f"{n}.50", "priceCurrency": "EUR"},
        }
        for n in (1, 2, 3)
    ]

    result = _listing(_html(_item_list(*items)), data=COMMITTED)

    assert [row.get("url") for row in _row_values(result)] == [_url(n) for n in (1, 2, 3)]


def test_a_products_main_entity_of_page_is_its_rows_item_url_after_its_own_url() -> None:
    items: list[dict[str, Any]] = [
        {"@type": "Product", "name": "Widget 1", "url": _url(1), "mainEntityOfPage": _url(7)},
        {"@type": "Product", "name": "Widget 2", "mainEntityOfPage": {"@type": "WebPage", "url": _url(2)}},
        {"@type": "Product", "name": "Widget 3", "mainEntityOfPage": _url(3)},
    ]

    result = _listing(_html(_item_list(*items)), data=COMMITTED)

    assert [row.get("url") for row in _row_values(result)] == [_url(1), _url(2), _url(3)]
