"""Cleaned text, its offsets and the visibility index: rendered from the page's one selectolax
tree."""

import pytest

from snowcrawl.content.page import ParsedPage
from snowcrawl.content.text import TextRun


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
        "<style>p { color: red }</style>",
        "<noscript>enable js</noscript>",
        "<svg><text>drawn</text></svg>",
        "<template><p>later</p></template>",
        "<div hidden>gone</div>",
        "<div aria-hidden='true'>gone</div>",
        "<div style='COLOR: red; Display : None !important'>gone</div>",
        "<div style='visibility:hidden'>gone</div>",
        "<div style='visibility: collapse'>gone</div>",
        "<dialog>closed</dialog>",
        "<input type='HIDDEN' value='secret'>",
    ],
)
def test_hidden_content_is_not_text_and_not_visible(hidden: str) -> None:
    page = ParsedPage(f"<html><head><title>Tab</title></head><body><p>shown</p>{hidden}</body></html>")

    assert page.cleaned_text.text == "shown"
    for value in ("gone", "closed", "secret", "later", "var x = 1;", "Tab", "drawn", "enable js"):
        assert not page.visible_values.visible(value)


def test_only_an_input_shows_its_value() -> None:
    # HTML Standard §4.10.5: a text input shows its value; an option shows its label, not its submitted value.
    page = ParsedPage(
        "<html><body><input value='Typed'><select><option value='4000000000006'>Navy</option></select>"
        "<data value='5000000000005'></data></body></html>"
    )

    assert page.visible_values.visible("Typed")
    assert page.visible_values.visible("Navy")
    assert not page.visible_values.visible("4000000000006")
    assert not page.visible_values.visible("5000000000005")


def test_a_concealed_block_holding_the_pages_title_and_form_is_shown_a_lone_concealed_one_is_not() -> None:
    # A script reveals the page's own content (it holds the one `h1` and the item's form); a variant template does not.
    gated = "<div style='display:none'><h1>Kettle</h1><form><span>12.50 EUR</span></form></div>"
    template = "<div hidden><form><span>9.99 EUR</span></form></div>"

    assert _text(gated + template) == "Kettle\n12.50 EUR"
    assert _text("<h1>Kettle</h1>" + gated.replace("Kettle", "Quick view")) == "Kettle"


def test_the_main_landmark_s_concealed_content_is_shown_when_nothing_else_in_it_renders() -> None:
    # A gate conceals the main landmark's titled content and shows its own message; a lone value is no content.
    content = "<div style='display:none'><h2>Kettles</h2><p>12.50 EUR</p></div>"
    gate = "<div style='display:none'>Locked</div>"

    assert _text(f"<main>{content}{gate}</main>") == "Kettles\n12.50 EUR"
    assert _text(f"<main><p>Open</p>{content}</main>") == "Open"
    assert _text("<main><p style='display:none'>12.50 EUR</p></main>") == ""
