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


def _schema(**fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()), origin="user", status="active", name="synthetic", page_kind="listing", fields=fields
    )


LISTING = _schema(title=TITLE, url=URL)


def _row(n: int) -> Entity:
    return Entity(id=f"llm:rows[{n}]", types=("page",), urls=(), parent=None)


def _title(n: int, title: str) -> Candidate:
    return Candidate(
        field="title",
        entity_id=f"llm:rows[{n}]",
        source_kind="llm",
        raw=title,
        normalized=Ok(title),
        locator="text:0-1",
        independent=True,
    )


def _card(title: str, *hrefs: str) -> str:
    links = "".join(f'<a href="{href}">{title}</a>' for href in hrefs)
    return f'<div class="card">{links}<p>5.00 EUR</p></div>'


def _links(cards: list[str], titles: list[str], schema: SchemaDef = LISTING) -> dict[str, tuple[str, JsonValue]]:
    page = ParsedPage(f"<html><body><main>{''.join(cards)}</main></body></html>")
    rows = [_row(n) for n in range(len(titles))]
    candidates = [_title(n, title) for n, title in enumerate(titles)]
    found = row_links(page, schema, CTX, rows, candidates)
    return {c.entity_id: (c.field, c.normalized.value if isinstance(c.normalized, Ok) else None) for c in found}


def test_each_row_takes_the_link_of_the_block_holding_its_title() -> None:
    cards = [_card(f"Widget {n}", f"/p/{n}", f"https://shop.example.test/p/{n}#top") for n in (1, 2, 3)]

    assert _links(cards, ["Widget 1", "Widget   3"]) == {
        "llm:rows[0]": ("url", "https://shop.example.test/p/1"),
        "llm:rows[1]": ("url", "https://shop.example.test/p/3"),
    }


def test_a_title_in_several_blocks_takes_no_link() -> None:
    # "Widget 1" is in the text of "Widget 10" too: which block is the row's, the page does not say.
    cards = [_card(name, f"/p/{i}") for i, name in enumerate(["Widget 1", "Widget 10", "Widget 2"])]

    assert _links(cards, ["Widget 1", "Widget 10"]) == {"llm:rows[1]": ("url", "https://shop.example.test/p/1")}


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
