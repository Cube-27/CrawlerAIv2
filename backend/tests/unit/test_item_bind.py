"""The item layer's bind step through the pipeline (listings spec, "Stated rows and blocks", "Row item URL"): stated
rows and blocks become one row per item; state rows bind by URL and lend a key the blocks prove. Pages are synthetic
(RFC 2606 names)."""

from pydantic import JsonValue

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


def test_a_stated_url_with_another_path_or_more_of_one_parameter_names_another_item() -> None:
    # RFC 3986 §6.2.4: one trailing slash aside, `/p/1//` is another path; a parameter repeated is two values.
    stated = _item_list(_row(1, url=_url(1, "//")), _row(2, url=_url(2, "?c=r&c=r")), _row(3, url=_url(3, "?c=r")))
    cards = _cards(_card(1), _card(2, href="/p/2?c=r&d=1"), _card(3, href="/p/3?c=r&d=1"))

    result = _listing(_html(stated, body=cards), data=COMMITTED)

    # Only the third binds (its query is among its block's); the others and their blocks stay apart.
    assert [row["url"] for row in _row_values(result)][2] == _url(3, "?c=r&d=1")
    assert len(result.rows) == 5


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


def _section(*cards: str) -> str:
    return f"<section>{_cards(*cards)}</section>"


def test_every_section_of_one_row_shape_gives_rows_each_item_once() -> None:
    # Two lists of the same cards: the second repeats item 3, which stays one row.
    body = _section(*(_card(n) for n in (1, 2, 3))) + _section(*(_card(n) for n in (3, 4, 5, 6)))

    result = _listing(_html(body=body), data=COMMITTED)

    assert [row["url"] for row in _row_values(result)] == [_url(n) for n in (1, 2, 3, 4, 5, 6)]
    assert all(row["price"] == _price(n) for n, row in zip(range(1, 7), _row_values(result), strict=True))


def test_a_cards_shown_amount_rivals_its_stated_rows_and_two_shown_amounts_contest_it() -> None:
    # Resolution spec, "the visible price": a card's one shown amount publishes over its row's stated one, flagged; a
    # card showing two amounts, neither the stated one, leaves the price a conflict; one of them equal to it agrees.
    offer = {"@type": "Offer", "price": "28.59", "priceCurrency": "EUR"}
    stated = _item_list(*(_row(n, offers=offer) for n in range(1, 6)))
    two = "</span><span>".join
    shown = [
        "15.58 EUR",
        two(["15.58 EUR", "17.29 EUR"]),
        two(["28.59 EUR", "31.00 EUR"]),
        two(["28.59 EUR", "31.00 EUR"]),
    ]
    cards = _cards(*(_card(n, price=price) for n, price in enumerate(shown, 1)), _card(5))

    result = _listing(_html(stated, body=cards), data=COMMITTED)

    outcomes = [(row["price"].status, row["price"].value, row["price"].reason) for row in result.rows]
    assert outcomes[0] == ("published", {"amount": "15.58", "currency": "EUR"}, "disagree")
    assert outcomes[1] == ("conflict", None, "disagree")
    assert outcomes[2] == ("published", {"amount": "28.59", "currency": "EUR"}, None)
    assert outcomes[4] == ("published", _price(5), "disagree")


def test_a_rows_price_inside_its_aggregate_offer_is_the_rows() -> None:
    # schema.org `offers`: an AggregateOffer's Offers offer its item, so their price is the row's.
    def aggregate(n: int) -> dict[str, JsonValue]:
        offer: dict[str, JsonValue] = {"@type": "Offer", "price": f"{n}.50", "priceCurrency": "EUR"}
        return {"@type": "AggregateOffer", "offerCount": 1, "offers": [offer]}

    result = _listing(_html(_item_list(*(_row(n, offers=aggregate(n)) for n in (1, 2, 3)))), data=COMMITTED)

    assert [row.get("price") for row in _row_values(result)] == [_price(n) for n in (1, 2, 3)]


def test_a_strip_repeating_the_listings_items_or_past_its_next_page_link_is_no_section() -> None:
    grid = _section(*(_card(n) for n in range(1, 7)))
    featured = _section(*(_card(n) for n in (1, 2, 3, 9)))
    pager = '<a rel="next" href="/c/widgets?page=3">Next</a>'
    after = _section(*(_card(n) for n in (7, 8, 9)))

    for body in (grid + featured, grid + pager + after):
        assert [row["url"] for row in _row_values(_listing(_html(body=body), data=COMMITTED))] == [
            _url(n) for n in range(1, 7)
        ]


def test_of_several_item_lists_the_pages_main_entity_or_the_one_its_grid_shows_gives_the_rows() -> None:
    # schema.org `mainEntity`: the page's own list; a related list beside it is not its rows.
    main = {"@type": "WebPage", "mainEntity": _item_list(*(_row(n) for n in (1, 2, 3)))}
    related = _item_list(*(_row(n) for n in (7, 8, 9)))

    from_main = _listing(_html(main, related), data=COMMITTED)
    from_grid = _listing(
        _html(related, _item_list(*(_row(n) for n in (1, 2, 3))), body=_cards(*(_card(n) for n in (1, 2, 3)))),
        data=COMMITTED,
    )

    assert [row["url"] for row in _row_values(from_main)] == [_url(n) for n in (1, 2, 3)]
    assert [row["url"] for row in _row_values(from_grid)] == [_url(n) for n in (1, 2, 3)]
