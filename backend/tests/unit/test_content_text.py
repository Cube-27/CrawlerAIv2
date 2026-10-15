"""Cleaned text, its offsets and the visibility index (SPEC-05 §4.4): rendered from the page's one selectolax tree."""

import pytest

from crawlerai.content.page import ParsedPage
from crawlerai.content.text import TextRun


def _text(body: str) -> str:
    return ParsedPage(
        f"<!doctype html><html><head><title>Tab</title></head><body>{body}</body></html>"
    ).cleaned_text.text


def test_blocks_are_lines_and_inline_text_joins_as_rendered() -> None:
    page = ParsedPage("<html><body><div>Hello <b>big</b> world</div><p>Sec<i>ond</i></p></body></html>")

    assert page.cleaned_text.text == "Hello big world\nSecond"
    assert page.cleaned_text.offsets == (
        TextRun(0, 5, "/html[1]/body[1]/div[1]"),
        TextRun(6, 9, "/html[1]/body[1]/div[1]/b[1]"),
        TextRun(10, 15, "/html[1]/body[1]/div[1]"),
        TextRun(16, 19, "/html[1]/body[1]/p[1]"),
        TextRun(19, 22, "/html[1]/body[1]/p[1]/i[1]"),
    )


def test_xpath_indexes_count_hidden_siblings_of_the_same_tag() -> None:
    page = ParsedPage("<body><div hidden>a</div><span>b</span><div>c</div></body>")

    assert page.cleaned_text.text == "b\nc"
    assert page.cleaned_text.offsets[1] == TextRun(2, 3, "/html[1]/body[1]/div[2]")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("<div>a</div><div><div>b</div>c</div>", "a\nb\nc"),
        ("<p>one<br>two</p>", "one\ntwo"),
        ("<ul><li>x</li><li>y</li></ul>", "x\ny"),
        ("<table><tr><td>a</td><td>b</td></tr><tr><th>c</th></tr></table>", "a b\nc"),
        ("<p>  lead\n\t and   trail  </p>", "lead and trail"),
        ("<p>a&nbsp;&nbsp;b</p>", "a b"),
        ("<p>a &amp;lt; b</p>", "a &lt; b"),
        ("<p>caf<span>é</span></p>", "café"),
        ("<p>a\u0007b</p>", "ab"),
        ("<span>a</span> <span>b</span>", "a b"),
        ("<div> </div><p>x</p>", "x"),
    ],
)
def test_text_is_decoded_composed_and_collapsed(body: str, expected: str) -> None:
    assert _text(body) == expected


@pytest.mark.parametrize(
    "hidden",
    [
        "<script>var x = 1;</script>",
        "<template><p>later</p></template>",
        "<div hidden>gone</div>",
        "<div aria-hidden='true'>gone</div>",
        "<div style='COLOR: red; Display : None !important'>gone</div>",
        "<div style='visibility:hidden'>gone</div>",
        "<dialog>closed</dialog>",
        "<input type='HIDDEN' value='secret'>",
    ],
)
def test_hidden_content_is_not_text_and_not_visible(hidden: str) -> None:
    page = ParsedPage(f"<html><head><title>Tab</title></head><body><p>shown</p>{hidden}</body></html>")

    assert page.cleaned_text.text == "shown"
    for value in ("gone", "closed", "secret", "later", "var x = 1;", "Tab"):
        assert not page.visible_values.visible(value)


def test_a_visible_descendant_of_a_visibility_hidden_element_is_shown() -> None:
    # CSS 2 §11.2: visibility is inherited, and a descendant with `visibility: visible` is visible.
    page = ParsedPage("<div style='visibility:hidden'>no <span style='visibility:visible'>yes</span></div>")

    assert page.cleaned_text.text == "yes"


def test_aria_hidden_false_and_display_block_are_shown() -> None:
    assert _text("<div aria-hidden='false' style='display:block'>kept</div><dialog open>open</dialog>") == "kept\nopen"


def test_visible_values_match_whole_words_across_inline_elements() -> None:
    index = ParsedPage("<p>Price: <span>$</span><span>19.99</span> each</p>").visible_values

    assert index.visible("$19.99")
    assert index.visible("Price: $19.99 each")
    assert index.visible("19.99")
    assert index.visible("  19.99\n")
    assert not index.visible("9.99")
    assert not index.visible("19.9")
    assert not index.visible("price")
    assert not index.visible("each Price")
    assert not index.visible("")


def test_visible_values_include_the_attributes_of_visible_elements() -> None:
    page = ParsedPage(
        "<img alt='Front view'><a title='More &amp; less'>x</a><input value='42'>"
        "<meta itemprop='sku' content='SKU-1'><div hidden><img alt='Back view'></div>"
    )

    assert page.visible_values.visible("Front view")
    assert page.visible_values.visible("More & less")
    assert page.visible_values.visible("More &amp; less")
    assert page.visible_values.visible("42")
    assert not page.visible_values.visible("SKU-1")  # `meta` is never rendered (HTML Standard, hidden elements)
    assert not page.visible_values.visible("Back view")


def test_paths_address_the_selectolax_tree_with_its_implied_tbody() -> None:
    # HTML tree construction inserts `tbody`; libxml2 does not, so this path is not guaranteed in `lxml_tree`.
    page = ParsedPage("<table><tr><td>x</td></tr></table>")

    assert page.cleaned_text.offsets == (TextRun(0, 1, "/html[1]/body[1]/table[1]/tbody[1]/tr[1]/td[1]"),)
    assert page.lxml_tree.xpath(page.cleaned_text.offsets[0].node_path) == []


def test_a_prefixed_tag_is_addressed_by_name_and_resolves_in_lxml() -> None:
    page = ParsedPage("<p>a<o:p>b</o:p><o:p>c</o:p></p>")

    assert page.cleaned_text.offsets[2] == TextRun(2, 3, "/html[1]/body[1]/p[1]/*[name()='o:p'][2]")
    assert [e.text_content() for e in page.lxml_tree.xpath(page.cleaned_text.offsets[2].node_path)] == ["c"]
