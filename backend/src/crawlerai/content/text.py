"""Cleaned page text with its offsets, and the visibility index (SPEC-05 §4.4), rendered in one walk of the page's
selectolax tree.

The text is the page as a reader sees it, without a CSS engine: the HTML Standard's rendering rules (its user-agent
style sheet) decide which elements are hidden and which start a line, and inline `style` declarations and the
`hidden`/`aria-hidden` attributes hide what the page hides itself. Style sheets and scripts are not evaluated.

Node paths address the selectolax tree, which HTML tree construction builds (implied `tbody`, reparented
misnested tags). The lxml tree comes from libxml2's own HTML parser, so a path is not guaranteed to resolve there.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple

from selectolax.lexbor import LexborNode

from crawlerai.normalize.text import compose, text_form

# HTML Standard, Rendering, "Hidden elements": the user-agent style sheet gives these `display: none`. SPEC-05 §4.4
# also drops `noscript` (its content is for user agents without scripting) and `svg` (graphics, not page text);
# `iframe` content is parsed as raw text and never rendered (HTML Standard, parsing: the generic raw text algorithm).
NOT_RENDERED = frozenset(
    {
        *("area", "base", "basefont", "datalist", "head", "link", "meta", "noembed", "noframes", "param", "rp"),
        *("script", "style", "template", "title", "noscript", "svg", "iframe"),
    }
)
# HTML Standard, Rendering, the user-agent style sheet: elements that are `display: block`, `list-item` or a table
# box other than a cell. Their text starts and ends a line, as the `innerText` getter breaks it.
_LINE_BOXES = frozenset(
    {
        *("html", "body", "address", "blockquote", "center", "dialog", "div", "figure", "figcaption", "footer"),
        *("form", "header", "hr", "legend", "listing", "main", "p", "plaintext", "pre", "search", "xmp"),
        *("article", "aside", "h1", "h2", "h3", "h4", "h5", "h6", "hgroup", "nav", "section"),
        *("dir", "dd", "dl", "dt", "menu", "ol", "ul", "li", "fieldset", "details", "summary"),
        *("table", "caption", "thead", "tbody", "tfoot", "tr"),
    }
)
# `display: table-cell`: adjacent cells are separate boxes, so their texts are separated (by a tab in `innerText`).
CELLS = frozenset({"td", "th"})
# HTML attributes whose values the page shows or announces for a visible element (SPEC-05 §4.4).
_SHOWN_ATTRIBUTES = ("alt", "title", "value", "content")
# Namespaces in XML 1.0, NCName: a name without a colon, starting with a letter or `_` (`[^\W\d]`), then letters,
# digits, `.`, `-` or `_`. Only an NCName can be an XPath 1.0 name test.
_NCNAME = re.compile(r"[^\W\d][\w.\-]*")

_Attributes = dict[str, str | None]


class TextRun(NamedTuple):
    """`text[start:end]` came from a text node child of the element at `node_path`: an XPath 1.0 location path in the
    selectolax tree (see the module docstring)."""

    start: int
    end: int
    node_path: str


@dataclass(frozen=True)
class CleanedText:
    """Lines of visible text, one per line box, separated by `\\n`; the runs are ordered and disjoint."""

    text: str
    offsets: tuple[TextRun, ...]


class VisibleIndex:
    """The visible text lines and the shown attributes of visible elements, in the SPEC-04 text form."""

    def __init__(self, cleaned: CleanedText, shown: Iterable[str]) -> None:
        # One entry per line and per attribute: a match never spans two of them.
        strings = [*cleaned.text.split("\n"), *shown]
        self._haystack = "\n".join(form for form in map(text_form, strings) if form)

    def visible(self, value: str) -> bool:
        """Whether `value`, in the text form, appears on the page without splitting a word. Word edges approximate
        Unicode word boundaries (UAX #29) by letters and digits (`str.isalnum`, Unicode categories L and N)."""
        needle = text_form(value)
        if not needle:
            return False
        start = self._haystack.find(needle)
        while start >= 0:
            end = start + len(needle)
            before = self._haystack[start - 1] if start else " "
            after = self._haystack[end] if end < len(self._haystack) else " "
            if not (needle[0].isalnum() and before.isalnum()) and not (needle[-1].isalnum() and after.isalnum()):
                return True
            start = self._haystack.find(needle, start + 1)
        return False


def render(root: LexborNode) -> tuple[CleanedText, tuple[str, ...]]:
    """The cleaned text of the document whose root element is `root`, and the shown attribute values of its visible
    elements (with the text, the input of its `VisibleIndex`)."""
    builder = _TextBuilder()
    shown: list[str] = []
    # Explicit stack, not recursion: document depth is not bounded by the interpreter's recursion limit.
    stack: list[_Item] = [_Enter(root, "/" + xpath_step(root.tag or "", 1), invisible=False)]
    while stack:
        item = stack.pop()
        if isinstance(item, _Text):
            builder.add(item.text, item.path)
        elif isinstance(item, _Separate):
            builder.separate(item.separator)
        else:
            stack.extend(reversed(_enter(item, shown)))
    return CleanedText("".join(builder.parts), tuple(builder.runs)), tuple(shown)


class _Enter(NamedTuple):
    node: LexborNode
    path: str
    invisible: bool


class _Text(NamedTuple):
    text: str
    path: str


class _Separate(NamedTuple):
    separator: str


_Item = _Enter | _Text | _Separate


def _enter(item: _Enter, shown: list[str]) -> list[_Item]:
    """What an element contributes, in document order: its children, between the separators of its box. Adds its
    shown attributes to `shown` when it is visible."""
    attributes = item.node.attributes
    tag = item.node.tag or ""
    style = _declarations(attributes)
    if _hidden(tag, attributes, style):
        return []
    invisible = _invisible(style.get("visibility"), inherited=item.invisible)
    if not invisible:
        shown.extend(value for name in _SHOWN_ATTRIBUTES if (value := attributes.get(name)))
    children = _children(item.node, item.path, invisible)
    separator = _separator(tag)
    return [_Separate(separator), *children, _Separate(separator)] if separator else children


def _separator(tag: str) -> str:
    """What separates an element's box from its siblings' text."""
    # HTML Standard, Rendering: `br` is a forced line break.
    if tag in _LINE_BOXES or tag == "br":
        return "\n"
    return " " if tag in CELLS else ""


def xpath_step(tag: str, index: int) -> str:
    """The XPath 1.0 step to the `index`th element child named `tag` (1-based, counting hidden siblings too)."""
    return f"{name_test(tag)}[{index}]"


def name_test(tag: str) -> str:
    """The XPath 1.0 test for elements named `tag`. A tag that is not an NCName (a prefixed `o:p`) is matched by
    `name()`, since a name test would read its prefix as a namespace."""
    if _NCNAME.fullmatch(tag):
        return tag
    quote = "'" if "'" not in tag else '"'
    return f"*[name()={quote}{tag}{quote}]"


def _children(node: LexborNode, path: str, invisible: bool) -> list[_Item]:
    counts: dict[str, int] = {}
    children: list[_Item] = []
    for child in node.iter(include_text=True):
        if child.is_element_node and child.tag:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            children.append(_Enter(child, f"{path}/{xpath_step(child.tag, counts[child.tag])}", invisible))
        elif child.is_text_node and not invisible:
            children.append(_Text(child.text_content or "", path))
    return children


def _hidden(tag: str, attributes: _Attributes, style: dict[str, str]) -> bool:
    """Not rendered at all, with its whole subtree."""
    # HTML Standard, Rendering, "Hidden elements": `[hidden]`, `input[type=hidden i]`, `dialog:not([open])`.
    if tag in NOT_RENDERED or "hidden" in attributes:
        return True
    if tag == "input" and (attributes.get("type") or "").strip().lower() == "hidden":
        return True
    if tag == "dialog" and "open" not in attributes:
        return True
    # WAI-ARIA 1.2, `aria-hidden="true"`: the element and its subtree are hidden from every user.
    if (attributes.get("aria-hidden") or "").strip().lower() == "true":
        return True
    return style.get("display") == "none"


def _invisible(visibility: str | None, *, inherited: bool) -> bool:
    # CSS 2 §11.2: `visibility` is inherited; `hidden` and `collapse` hide the box, `visible` shows it again.
    if visibility in ("hidden", "collapse"):
        return True
    return inherited and visibility != "visible"


def _declarations(attributes: _Attributes) -> dict[str, str]:
    """The inline `style` declarations, by lower-cased property name; a later declaration wins (CSS Cascade)."""
    # CSS Syntax: declarations are separated by `;`, name from value by `:`. Property names and keyword values are
    # ASCII case-insensitive, and `!important` is a priority, not part of the value.
    declarations: dict[str, str] = {}
    for declaration in (attributes.get("style") or "").split(";"):
        name, colon, value = declaration.partition(":")
        if colon:
            declarations[name.strip().lower()] = value.lower().replace("!important", "").strip()
    return declarations


class _TextBuilder:
    """CSS Text 3 §4.1 white-space collapsing (`white-space: normal`) across text nodes, with Unicode White_Space as
    the collapsible set, as the SPEC-04 text rules collapse it."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.runs: list[TextRun] = []
        self._length = 0
        self._pending = ""

    def separate(self, separator: str) -> None:
        # A line break outranks a space; nothing separates the first text from the start of the document.
        if self._length and (separator == "\n" or not self._pending):
            self._pending = separator

    def add(self, raw: str, path: str) -> None:
        text = compose(raw)
        if text[:1].isspace():
            self.separate(" ")
        words = text.split()
        if words:
            if self._pending:
                self._append(self._pending)
                self._pending = ""
            start = self._length
            self._append(" ".join(words))
            self.runs.append(TextRun(start, self._length, path))
        if text[-1:].isspace():
            self.separate(" ")

    def _append(self, piece: str) -> None:
        self.parts.append(piece)
        self._length += len(piece)
