"""Cleaned text, its offsets and the visibility index (extraction spec): rendered from the page's one selectolax
tree."""

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
