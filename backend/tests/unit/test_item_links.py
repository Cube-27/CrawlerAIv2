"""Item URLs of role C's listing rows from the repeated item blocks (ARCHITECTURE §8.6, D-1024 option (a)): a row takes
the link of the one block holding its text values, and gets none whenever that is not one block with one link.

Pages are synthetic (`example.test`, C3).
"""

from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.item_links import row_links
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


def _value(n: int, field: str, value: str) -> Candidate:
    return Candidate(
        field=field,
        entity_id=f"llm:rows[{n}]",
        source_kind="llm",
        raw=value,
        normalized=Ok(value),
        locator="text:0-1",
        independent=True,
    )


def _title(n: int, title: str) -> Candidate:
    return _value(n, "title", title)


def _card(title: str, *hrefs: str) -> str:
    links = "".join(f'<a href="{href}">{title}</a>' for href in hrefs)
    return f'<div class="card">{links}<p>5.00 EUR</p></div>'


def _links(
    cards: list[str], titles: list[str], schema: SchemaDef = LISTING, candidates: list[Candidate] | None = None
) -> dict[str, tuple[str, JsonValue]]:
    page = ParsedPage(f"<html><body><main>{''.join(cards)}</main></body></html>")
    rows = [_row(n) for n in range(len(titles))]
    candidates = [_title(n, title) for n, title in enumerate(titles)] if candidates is None else candidates
    found = row_links(page, schema, CTX, rows, candidates)
    return {c.entity_id: (c.field, c.normalized.value if isinstance(c.normalized, Ok) else None) for c in found}


def test_each_row_takes_the_link_of_the_block_holding_its_title() -> None:
    cards = [_card(f"Widget {n}", f"/p/{n}", f"https://shop.example.test/p/{n}#top") for n in (1, 2, 3)]

    assert _links(cards, ["Widget 1", "Widget   3"]) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/1"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/3"),
    }


def test_a_title_that_is_an_elements_whole_text_picks_its_block_among_several() -> None:
    # "Widget 1" is in the text of "Widget 10" too, but only the first card has an element whose text it is.
    cards = [_card(name, f"/p/{i}") for i, name in enumerate(["Widget 1", "Widget 10", "Widget 2"])]

    assert _links(cards, ["Widget 1", "Widget 10"]) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/0"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/1"),
    }


def test_a_title_two_blocks_show_as_a_whole_takes_no_link() -> None:
    cards = [_card("Widget", "/p/1"), _card("Widget", "/p/2"), _card("Gadget", "/p/3")]

    assert _links(cards, ["Widget", "Gadget"]) == {"llm:rows[1]": ("url", "https://shop.example.test/p/3")}


def test_every_grounded_value_of_the_row_places_it() -> None:
    # Two cards share a title; the row's grounded place (a location field, not text) is in one of them only.
    cards = [
        '<div class="card"><a href="/j/1">Cook</a><p>Town A</p></div>',
        '<div class="card"><a href="/j/2">Cook</a><p>Town B</p></div>',
        '<div class="card"><a href="/j/3">Baker</a><p>Town A</p></div>',
    ]
    schema = _schema(title=TITLE, url=URL, location=PLACE)
    candidates = [_title(0, "Cook"), _value(0, "location", "Town B"), _title(1, "Baker")]

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
