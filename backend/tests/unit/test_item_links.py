"""Item URLs of role C's listing rows from the repeated item blocks (ARCHITECTURE §8.6, D-1024 option (a)): a row takes
the link of the one block whose span of the cleaned text holds its grounded values (D-1490), and gets none whenever
that is not one block with one link.

Pages are synthetic (`example.test`, C3).
"""

from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.item_links import as_block_links, row_links
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/c/widgets"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
TITLE = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name")
URL = FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url")
PLACE = FieldSpec(type=FieldType.LOCATION, description="d", schema_org="JobPosting.jobLocation")


def _schema(**fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()), origin="user", status="active", name="synthetic", page_kind="listing", fields=fields
    )


LISTING = _schema(title=TITLE, url=URL)


def _row(n: int) -> Entity:
    return Entity(id=f"llm:rows[{n}]", types=("page",), urls=(), parent=None)


def _value(n: int, field: str, value: str, occurrence: int = 0) -> Candidate:
    """Row `n`'s role C value, grounded at its `occurrence`-th place in the cleaned text by `_links` (the locator is a
    placeholder until then)."""
    return Candidate(
        field=field,
        entity_id=f"llm:rows[{n}]",
        source_kind="llm",
        raw=value,
        normalized=Ok(value),
        locator=f"text:{occurrence}-{occurrence + 1}",
        independent=True,
    )


def _title(n: int, title: str, occurrence: int = 0) -> Candidate:
    return _value(n, "title", title, occurrence)


def _grounded(text: str, c: Candidate) -> Candidate:
    """`c` at the `occurrence`-th place of its value in the cleaned `text` (INV-12: a role C value is a span of it)."""
    assert isinstance(c.raw, str)
    start = -1
    for _ in range(int(c.locator.removeprefix("text:").split("-")[0]) + 1):
        start = text.index(c.raw, start + 1)
    return c.model_copy(update={"locator": f"text:{start}-{start + len(c.raw)}"})


def _card(title: str, *hrefs: str) -> str:
    links = "".join(f'<a href="{href}">{title}</a>' for href in hrefs)
    return f'<div class="card">{links}<p>5.00 EUR</p></div>'


def _links(
    cards: list[str], titles: list[str], schema: SchemaDef = LISTING, candidates: list[Candidate] | None = None
) -> dict[str, tuple[str, JsonValue]]:
    page = ParsedPage(f"<html><body><main>{''.join(cards)}</main></body></html>")
    rows = [_row(n) for n in range(len(titles))]
    candidates = [_title(n, title) for n, title in enumerate(titles)] if candidates is None else candidates
    grounded = [_grounded(page.cleaned_text.text, c) for c in candidates]
    found = row_links(page, schema, CTX, rows, grounded)
    return {c.entity_id: (c.field, c.normalized.value if isinstance(c.normalized, Ok) else None) for c in found}


def test_each_row_takes_the_link_of_the_block_holding_its_title() -> None:
    cards = [_card(f"Widget {n}", f"/p/{n}", f"https://shop.example.test/p/{n}#top") for n in (1, 2, 3)]

    assert _links(cards, ["Widget 1", "Widget 3"]) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/1"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/3"),
    }


def test_items_that_repeat_their_values_each_keep_their_own_link() -> None:
    # One product in three colours: the same title and price in each card; each row is placed by where its values
    # are grounded, not by what they say.
    cards = [_card("Widget", f"/p/widget-{colour}") for colour in ("red", "blue", "green")]
    candidates = [c for n in range(3) for c in (_title(n, "Widget", n), _value(n, "price", "5.00 EUR", n))]

    assert _links(cards, ["Widget"] * 3, candidates=candidates) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/widget-red"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/widget-blue"),
        "llm:rows[2]": ("url", "https://shop.example.test/p/widget-green"),
    }


def test_a_row_whose_values_sit_in_two_blocks_takes_no_link() -> None:
    cards = [_card(f"Widget {n}", f"/p/{n}") for n in (1, 2, 3)]
    candidates = [_title(0, "Widget 1"), _value(0, "price", "5.00 EUR", 1), _title(1, "Widget 3")]

    assert _links(cards, ["Widget 1", "Widget 3"], candidates=candidates) == {
        "llm:rows[1]": ("url", "https://shop.example.test/p/3")
    }


def test_two_rows_grounded_in_one_block_take_no_link() -> None:
    cards = [_card("Widget", "/p/1"), _card("Widget", "/p/2"), _card("Gadget", "/p/3")]
    candidates = [_title(0, "Widget"), _title(1, "Widget"), _title(2, "Gadget")]

    assert _links(cards, ["Widget", "Widget", "Gadget"], candidates=candidates) == {
        "llm:rows[2]": ("url", "https://shop.example.test/p/3")
    }


def test_every_grounded_value_of_the_row_places_it() -> None:
    # Two cards share a title; the row's grounded place (a location field, not text) is in the second only.
    cards = [
        '<div class="card"><a href="/j/1">Cook</a><p>Town A</p></div>',
        '<div class="card"><a href="/j/2">Cook</a><p>Town B</p></div>',
        '<div class="card"><a href="/j/3">Baker</a><p>Town A</p></div>',
    ]
    schema = _schema(title=TITLE, url=URL, location=PLACE)
    candidates = [_title(0, "Cook", 1), _value(0, "location", "Town B"), _title(1, "Baker")]

    assert _links(cards, ["Cook", "Baker"], schema, candidates) == {
        "llm:rows[0]": ("url", "https://shop.example.test/j/2"),
        "llm:rows[1]": ("url", "https://shop.example.test/j/3"),
    }


def test_a_title_cut_short_with_an_ellipsis_reads_as_its_title_attribute() -> None:
    # The cleaned text shows the `title` of an element whose text is that title cut short (D-1154), and role C
    # grounds the full title there; the block is read the same way.
    cards = [
        '<div class="card"><a href="/p/1" title="Widget with a long name">Widget with a lo\u2026</a></div>',
        '<div class="card"><a href="/p/2" title="Gadget with a long name">Gadget with a ...</a></div>',
        _card("Gizmo", "/p/3"),
    ]

    assert _links(cards, ["Widget with a long name", "Gadget with a long name"]) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/1"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/2"),
    }


def test_text_a_page_does_not_render_is_not_the_blocks() -> None:
    script = '<script>var related = "Widget 2";</script>'
    first = f'<div class="card"><a href="/p/1">Widget 1</a>{script}</div>'
    cards = [first, _card("Widget 2", "/p/2"), _card("Widget 3", "/p/3")]

    assert _links(cards, ["Widget 2"]) == {"llm:rows[0]": ("url", "https://shop.example.test/p/2")}


def test_a_block_linking_to_several_documents_takes_the_one_its_row_labels() -> None:
    # HTML Standard §4.5.1: an `a` element's content labels its link; only the title's link is labelled by the row.
    card = '<div class="card"><a href="/p/{n}">Widget {n}</a> by <a href="/author/{n}">Ann {n}</a></div>'
    cards = [card.format(n=n) for n in (1, 2, 3)]

    assert _links(cards, ["Widget 1", "Widget 3"]) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/1"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/3"),
    }


def test_the_link_whose_content_holds_a_grounded_value_labels_the_item() -> None:
    # The item link holds the title and the price; the cart and compare links lead elsewhere.
    card = (
        '<li class="product"><a href="/p/{n}"><h2>Coin {n}</h2><span>{n}.50 EUR</span></a>'
        '<a href="?add-to-cart={n}">Add to cart</a><a href="/compare">Compare</a></li>'
    )
    cards = [card.format(n=n) for n in (1, 2, 3)]
    candidates = [_title(0, "Coin 2"), _value(0, "price", "2.50 EUR")]

    assert _links(cards, ["Coin 2"], candidates=candidates) == {"llm:rows[0]": ("url", "https://shop.example.test/p/2")}


def test_links_that_add_a_query_to_the_items_link_refine_it() -> None:
    # Swatches link the item's path with a variant query: the block still links to one item (RFC 3986 §3.3, §3.4).
    card = (
        '<div class="card"><span>Bud {n}</span><a href="/p/bud-{n}"><img alt=""></a>'
        '<a href="/p/bud-{n}?variant=1"><img alt=""></a><a href="/p/bud-{n}?variant=2"><img alt=""></a></div>'
    )
    cards = [card.format(n=n) for n in (1, 2, 3)]

    assert _links(cards, ["Bud 1"]) == {"llm:rows[0]": ("url", "https://shop.example.test/p/bud-1")}


def test_the_group_holding_the_rows_wins_over_a_larger_one() -> None:
    # A pager of five links outnumbers three cards; the rows are in the cards.
    pager = '<ul class="pager">' + "".join(f'<li><a href="?page={n}">{n}</a></li>' for n in range(1, 6)) + "</ul>"
    cards = [_card(f"Widget {n}", f"/p/{n}") for n in (1, 2, 3)]

    assert _links([*cards, pager], ["Widget 1", "Widget 2"]) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/1"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/2"),
    }


def test_a_block_linking_to_several_documents_or_only_to_the_page_gives_no_link() -> None:
    cards = [_card("Widget 1", "/p/1", "/brand/acme"), _card("Widget 2", "#reviews"), _card("Widget 3", "/p/3")]

    assert _links(cards, ["Widget 1", "Widget 2", "Widget 3"]) == {
        "llm:rows[2]": ("url", "https://shop.example.test/p/3")
    }


def test_a_block_two_rows_are_in_gives_neither_a_link() -> None:
    cards = [_card("Widget 1 and Gadget 1", "/p/1"), _card("Widget 2", "/p/2"), _card("Widget 3", "/p/3")]

    assert _links(cards, ["Widget 1", "Gadget 1"]) == {}


def test_only_a_field_that_is_the_items_own_url_takes_the_link() -> None:
    cards = [_card(f"Widget {n}", f"/p/{n}") for n in (1, 2, 3)]
    offer_url = FieldSpec(type=FieldType.URL, description="d", schema_org="Product.offers.url")
    unmapped = FieldSpec(type=FieldType.URL, description="d")

    assert _links(cards, ["Widget 1"], _schema(title=TITLE, url=offer_url, link=unmapped)) == {}


def test_a_page_without_repeated_items_gives_no_link() -> None:
    assert _links([_card("Widget 1", "/p/1")], ["Widget 1"]) == {}


def test_hidden_text_is_not_the_blocks() -> None:
    # The cleaned text leaves out `hidden`, `aria-hidden` and `display: none` subtrees, so role C cannot ground there.
    hidden = '<span hidden>Widget 2</span><span aria-hidden="true">Widget 2</span><i style="display:none">Widget 2</i>'
    cards = [
        f'<div class="card"><a href="/p/1">Widget 1</a>{hidden}</div>',
        _card("Widget 2", "/p/2"),
        _card("W", "/p/3"),
    ]

    assert _links(cards, ["Widget 2"]) == {"llm:rows[0]": ("url", "https://shop.example.test/p/2")}


def test_a_decomposed_title_matches_its_composed_grounding() -> None:
    # The cleaned text is NFC (`normalize.text.compose`); the page may write the title decomposed (NFD).
    cards = [_card("Café table", "/p/1"), _card("Chair", "/p/2"), _card("Lamp", "/p/3")]

    assert _links(cards, ["Café table"]) == {"llm:rows[0]": ("url", "https://shop.example.test/p/1")}


def test_a_link_whose_text_only_holds_a_row_value_does_not_label_it() -> None:
    # The row's value "Ann 2" is in the author link's text "Ann 2 Lee", but only a link whose whole text is a row
    # value labels the item; the edition link carries none, so the card names no item link.
    card = '<div class="card"><span>Ann {n}</span> <a href="/p/{n}">Edition</a> <a href="/a/{n}">Ann {n} Lee</a></div>'
    cards = [card.format(n=n) for n in (1, 2, 3)]

    assert _links(cards, ["Ann 2"]) == {}


# --- structured row URLs respelling an item block's link (D-1495) ---


def _structured(n: int, url: str) -> Candidate:
    return Candidate(
        field="url",
        entity_id=f"jsonld:row{n}",
        source_kind="jsonld",
        raw=url,
        normalized=Ok(url),
        locator=f"jsonld:0:$.itemListElement[{n}].url",
        independent=True,
    )


def _respelled(cards: list[str], urls: list[str]) -> list[tuple[str, JsonValue]]:
    page = ParsedPage(f"<html><body><main>{''.join(cards)}</main></body></html>")
    rows = frozenset(f"jsonld:row{n}" for n in range(len(urls)))
    found = as_block_links(page, LISTING, CTX, [_structured(n, url) for n, url in enumerate(urls)], rows)
    return [(c.source_kind, c.normalized.value if isinstance(c.normalized, Ok) else None) for c in found]


def test_a_row_url_with_a_query_or_slash_the_blocks_link_lacks_takes_the_pages_link() -> None:
    cards = [_card(f"Widget {n}", f"/p/{n}?colour=red") for n in (1, 2)] + [_card("Widget 3", "/p/3/")]
    urls = [
        "https://shop.example.test/p/1?colour=red&ref=list",
        "https://shop.example.test/p/2/?colour=red",
        "https://shop.example.test/p/3",
    ]

    assert _respelled(cards, urls) == [
        ("dom", "https://shop.example.test/p/1?colour=red"),
        ("dom", "https://shop.example.test/p/2?colour=red"),
        ("dom", "https://shop.example.test/p/3/"),
    ]


def test_a_row_url_that_is_a_link_another_path_or_one_of_two_links_stays() -> None:
    cards = [_card("Widget 1", "/p/1"), _card("Widget 2", "/p/2?colour=red", "/p/2?colour=blue"), _card("W", "/p/3")]
    urls = [
        "https://shop.example.test/p/1",
        "https://shop.example.test/p/2?colour=red&colour=blue",
        "https://shop.example.test/q/3",
        "https://shop.example.test/p/1?size=s",
    ]

    assert _respelled(cards, urls) == [
        ("jsonld", "https://shop.example.test/p/1"),
        ("jsonld", "https://shop.example.test/p/2?colour=red&colour=blue"),
        ("jsonld", "https://shop.example.test/q/3"),
        ("dom", "https://shop.example.test/p/1"),
    ]
