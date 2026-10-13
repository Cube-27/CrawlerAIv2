"""Cleaned-text offsets (SPEC-05 §4.4, PR 1): on generated documents, the text is exactly the visible words, each run
is a slice of it that comes from the element its XPath names, and runs are ordered and disjoint."""

from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.content.page import ParsedPage

_word = st.from_regex(r"[a-z0-9]{1,8}", fullmatch=True)
# Whitespace on both sides: text nodes that touch join into one word, as rendered (a unit test covers that).
_space = st.sampled_from([" ", "\n  ", "\t"])
# Tags whose nesting the HTML parser keeps as written, so the generated tree is the parsed tree.
_BLOCK = ["div", "section", "article"]
_INLINE = ["span", "b", "em"]
_HIDING = ["hidden", "aria-hidden='true'", "style='display: none'", "style='visibility:hidden'"]


@dataclass(frozen=True)
class _Doc:
    html: str
    visible_words: tuple[str, ...]


@st.composite
def _text_node(draw: st.DrawFn) -> _Doc:
    words = draw(st.lists(_word, min_size=1, max_size=4))
    text = draw(_space) + " ".join(words) + draw(_space)
    return _Doc(text, tuple(words))


def _element(children: st.SearchStrategy[list[_Doc]]) -> st.SearchStrategy[_Doc]:
    @st.composite
    def element(draw: st.DrawFn) -> _Doc:
        tag = draw(st.sampled_from(_BLOCK + _INLINE))
        hiding = draw(st.none() | st.sampled_from(_HIDING))
        kids = draw(children)
        inner = "".join(kid.html for kid in kids)
        attribute = f" {hiding}" if hiding else ""
        words = () if hiding else tuple(w for kid in kids for w in kid.visible_words)
        return _Doc(f"<{tag}{attribute}>{inner}</{tag}>", words)

    return element()


_node = st.recursive(_text_node(), lambda inner: _element(st.lists(inner, max_size=4)), max_leaves=20)


@given(st.lists(_node, max_size=5))
def test_the_cleaned_text_is_the_visible_words_and_each_run_maps_back_to_its_element(nodes: list[_Doc]) -> None:
    page = ParsedPage("<html><body>" + "".join(n.html for n in nodes) + "</body></html>")
    cleaned = page.cleaned_text

    assert tuple(cleaned.text.split()) == tuple(w for n in nodes for w in n.visible_words)
    previous_end = 0
    for run in cleaned.offsets:
        piece = cleaned.text[run.start : run.end]
        assert previous_end <= run.start < run.end
        assert cleaned.text[previous_end : run.start] in {"", " ", "\n"}
        assert piece == " ".join(piece.split())
        (element,) = page.lxml_tree.xpath(run.node_path)
        own_text = " ".join(" ".join(element.xpath("text()")).split())
        assert piece in own_text
        previous_end = run.end
    assert previous_end == len(cleaned.text)
