"""The structural DOM collector (SPEC-05 §4.5, ARCHITECTURE §8.1, §22 admitted 2026-10-16): label-value pairs whose
label is a field's name or the schema.org property its path names, and the main content's first image. Every
candidate is the page's, independent, with a `dom:` locator naming the element its value came from. Pages are
synthetic (`example.test`, C3, C9)."""

from datetime import UTC, datetime

import pytest

from crawlerai.collect.base import PAGE
from crawlerai.collect.dom import DomCollector
from crawlerai.collect.locator import parse_locator
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL, html_lang="en")


def _field(type_: FieldType, path: str | None, **params: object) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, "description": "d", "schema_org": path, **params})


def _schema(page_kind: PageKind, **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields=fields,
    )


FIELDS = {
    "title": _field(FieldType.TEXT, "Product.name"),
    "brand": _field(FieldType.TEXT, "Product.brand.name"),
    "sku": _field(FieldType.IDENTIFIER, "Product.sku", scheme="sku"),
    "availability": _field(FieldType.ENUM, "Offer.availability", vocab="schema:ItemAvailability"),
    "review_count": _field(FieldType.COUNT, "Product.aggregateRating.reviewCount"),
    "gender": _field(FieldType.TEXT, "Product.audience.suggestedGender"),
    "image_url": _field(FieldType.IMAGE_URL, "Product.image"),
    "images": _field(FieldType.LIST, "Product.image", item={"type": "image_url"}),
    "note": _field(FieldType.TEXT, None),
}
SCHEMA = _schema("detail", **FIELDS)


def _collect(body: str, schema: SchemaDef = SCHEMA) -> dict[str, list[tuple[object, str]]]:
    candidates = DomCollector().collect(ParsedPage(f"<html><body>{body}</body></html>"), schema, CTX).candidates
    found: dict[str, list[tuple[object, str]]] = {}
    for c in candidates:
        assert (c.entity_id, c.source_kind, c.independent) == (PAGE, "dom", True)
        value = c.normalized.value if isinstance(c.normalized, Ok) else c.normalized
        found.setdefault(c.field, []).append((value, c.locator))
    return found


def test_a_two_cell_table_row_whose_header_names_a_field_gives_its_value() -> None:
    found = _collect(
        "<table><tr><th>Brand:</th><td>Example Brand</td></tr>"
        "<tr><th>SKU</th><td> W-100 </td></tr>"
        "<tr><td>Availability</td><td>In stock (5 available)</td></tr></table>"
    )

    assert found == {
        "brand": [("Example Brand", "dom:/html[1]/body[1]/table[1]/tbody[1]/tr[1]/td[1]")],
        "sku": [({"scheme": "sku", "value": "W-100"}, "dom:/html[1]/body[1]/table[1]/tbody[1]/tr[2]/td[1]")],
        "availability": [("InStock", "dom:/html[1]/body[1]/table[1]/tbody[1]/tr[3]/td[2]")],
    }


def test_a_description_list_gives_each_term_its_descriptions() -> None:
    found = _collect(
        "<dl><dt>Review count</dt><dd>12</dd><div><dt>Gender</dt><dt>Suggested gender</dt><dd>Unisex</dd></div></dl>"
    )

    assert found == {
        "review_count": [(12, "dom:/html[1]/body[1]/dl[1]/dd[1]")],
        # Two terms of one group naming the same field give its description once.
        "gender": [("Unisex", "dom:/html[1]/body[1]/dl[1]/div[1]/dd[1]")],
    }


@pytest.mark.parametrize(
    "body",
    [
        # A row of three cells is a data table's row, not a label and its value.
        "<table><tr><th>Brand</th><td>Example Brand</td><td>x</td></tr></table>",
        # A label that is neither a field name nor the property a field's path names.
        "<table><tr><th>Maker</th><td>Example Brand</td></tr></table>",
        # The property a path goes through is not the one it names (`Product.aggregateRating.reviewCount`).
        "<table><tr><th>Aggregate rating</th><td>12</td></tr></table>",
        # A value the page does not show.
        '<table><tr><th>Brand</th><td style="display:none">Example Brand</td></tr></table>',
        # A field without a schema.org path is matched by its name only, and an empty value is no value.
        "<table><tr><th>Name</th><td> </td></tr></table>",
    ],
)
def test_what_is_not_a_shown_label_value_pair_of_a_field_gives_nothing(body: str) -> None:
    assert _collect(body) == {}


def test_a_value_that_does_not_normalize_is_still_a_candidate() -> None:
    found = _collect("<table><tr><th>Availability</th><td>Ask us</td></tr></table>")

    assert found == {"availability": [(Invalid("not_a_member"), "dom:/html[1]/body[1]/table[1]/tbody[1]/tr[1]/td[1]")]}


def test_a_listing_schema_gets_no_page_level_pairs_or_image() -> None:
    body = '<main><img src="/a.jpg"></main><table><tr><th>Brand</th><td>Example Brand</td></tr></table>'
    assert _collect(body, _schema("listing", **FIELDS)) == {}


def test_the_main_image_is_the_first_image_of_the_main_element_outside_its_navigation() -> None:
    found = _collect(
        '<img src="/logo.png"><main><nav><img src="/menu.png"></nav>'
        '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="><img src="/p/1.jpg"><img src="/p/2.jpg"></main>'
    )

    assert found == {"image_url": [("https://shop.example.test/p/1.jpg", "dom:/html[1]/body[1]/main[1]/img[2]")]}


@pytest.mark.parametrize(
    ("body", "image"),
    [
        ('<div role="main"><img srcset="/p/s.jpg 1x, /p/l.jpg 2x"></div>', "https://shop.example.test/p/s.jpg"),
        (
            '<article><header><img src="/h.png"></header><img src="/p/a.jpg"></article>',
            "https://shop.example.test/p/a.jpg",
        ),
    ],
)
def test_the_main_region_is_a_main_landmark_or_the_one_article(body: str, image: str) -> None:
    assert [value for value, _ in _collect(body).get("image_url", [])] == [image]


@pytest.mark.parametrize(
    "body",
    [
        '<div><img src="/p/1.jpg"></div>',  # no main region
        '<article><img src="/a.jpg"></article><article><img src="/b.jpg"></article>',  # two articles, neither main
        '<main><aside><img src="/ad.jpg"></aside></main>',  # only tangential content
    ],
)
def test_without_one_main_region_image_there_is_no_main_image(body: str) -> None:
    assert _collect(body) == {}


@pytest.mark.parametrize(
    "wrapper",
    [
        '<div role="dialog" aria-modal="true">{}</div>',  # WAI-ARIA 1.2 dialog: a window apart from the page
        '<div role="alertdialog">{}</div>',
        "<dialog open>{}</dialog>",  # HTML Standard §4.11.4
        '<div aria-hidden="true"><div>{}</div></div>',  # hidden from every user, as in the cleaned text
        "<div hidden>{}</div>",
        '<div style="display: none">{}</div>',
        '<div style="visibility: hidden"><span>{}</span></div>',  # CSS 2 §11.2: inherited
    ],
)
def test_an_image_in_a_dialog_or_a_hidden_subtree_is_not_the_main_image(wrapper: str) -> None:
    # D-1023: a drawer or modal inside `main` holds images of its own (a badge, a size chart), not the entity's.
    found = _collect(f'<main>{wrapper.format("<img src=/badge.png>")}<img src="/p/1.jpg"></main>')

    assert [value for value, _ in found["image_url"]] == ["https://shop.example.test/p/1.jpg"]


def test_a_hidden_main_region_has_no_main_image() -> None:
    assert _collect('<div aria-hidden="true"><main><img src="/p/1.jpg"></main></div>') == {}


def test_locators_parse_as_dom_xpaths() -> None:
    candidates = (
        DomCollector()
        .collect(
            ParsedPage('<html><body><main><img src="/p.jpg"></main><dl><dt>SKU</dt><dd>W-1</dd></dl></body></html>'),
            SCHEMA,
            CTX,
        )
        .candidates
    )
    assert [parse_locator(c.locator).scheme for c in candidates] == ["dom", "dom"]


@pytest.mark.parametrize(
    "other",
    [
        '<img src="/deco.jpg" alt="">',  # HTML Standard §4.8.4.4: an empty `alt` marks an image as decorative
        '<img src="/deco.jpg" alt=" " role="none">',  # WAI-ARIA 1.2: roles `none`, `presentation`
        '<img src="/deco.jpg" alt="x" role="presentation">',
        # HTML Standard §4.8.9, §4.8.7: a media element's children are fallback content, not shown where it is
        '<video poster="/poster.jpg"><img src="/poster.jpg"></video>',
        '<object data="/x.pdf"><img src="/x.png"></object>',
        # A link card: an image whose block holds one hyperlink to another document is that document's teaser.
        '<ul><li><div><img src="/c/a.jpg" alt="A"><p>Type A</p><a href="/c/a">Shop now</a></div></li>'
        '<li><div><img src="/c/b.jpg" alt="B"><p>Type B</p><a href="/c/b">Shop now</a></div></li></ul>',
        '<a href="https://promo.example.test/sale"><img src="/banner.jpg" alt="Sale"></a>',
        '<div><a href="/c/a"><img src="/c/a.jpg" alt="A"></a><a href="/c/a">Type A</a></div>',
    ],
)
def test_a_decorative_fallback_or_link_card_image_is_not_the_main_image(other: str) -> None:
    found = _collect(f'<main>{other}<img src="/p/1.jpg" alt="Product"></main>')

    assert [value for value, _ in found["image_url"]] == ["https://shop.example.test/p/1.jpg"]


@pytest.mark.parametrize(
    "wrapper",
    [
        '<a href="/p/1-large.jpg">{}</a>',  # a link to an image resource (RFC 6838 `image/*`) is the image itself
        '<a href="#zoom">{}</a>',  # a fragment link stays on this page (RFC 3986 §4.4)
        '<a href="/p/1">{}</a><a href="/p/1#reviews">Reviews</a>',  # links to this page itself
        '<div><a href="/c/a">Category A</a> <a href="/c/b">Category B</a>{}</div>',  # links to several documents
        # The nearest block with a link holds other images too: a gallery beside a link, not one card.
        '<div>{}<img src="/p/2.jpg" alt="Back"><a href="/c/a">Category A</a></div>',
    ],
)
def test_an_image_linked_to_itself_this_page_or_several_documents_stays_the_main_image(wrapper: str) -> None:
    found = _collect(f"<main>{wrapper.format(chr(60) + 'img src=/p/1.jpg alt=Product>')}</main>")

    assert [value for value, _ in found["image_url"]] == ["https://shop.example.test/p/1.jpg"]
