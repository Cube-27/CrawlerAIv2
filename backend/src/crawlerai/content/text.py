"""Cleaned page text with its offsets, and the visibility index (SPEC-05 §4.4), rendered in one walk of the page's
selectolax tree.

The text is the page as a reader sees it, without a CSS engine: the HTML Standard's rendering rules (its user-agent
style sheet) decide which elements are hidden and which start a line, and inline `style` declarations and the
`hidden`/`aria-hidden` attributes hide what the page hides itself. Style sheets and scripts are not evaluated.

Node paths address the selectolax tree, which HTML tree construction builds (implied `tbody`, reparented
misnested tags). The lxml tree comes from libxml2's own HTML parser, so a path is not guaranteed to resolve there.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, NamedTuple

from selectolax.lexbor import LexborHTMLParser, LexborNode

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
# Unicode: U+2026 HORIZONTAL ELLIPSIS, whose compatibility decomposition (NFKC) is three U+002E FULL STOPs.
_ELLIPSIS = "..."
_ELLIPSES = ("\u2026", _ELLIPSIS)


class TextRun(NamedTuple):
    """`text[start:end]` came from a text node child of the element at `node_path`: an XPath 1.0 location path in the
    selectolax tree (see the module docstring)."""

    start: int
    end: int
    node_path: str


MarkKind = Literal["link", "image"]


class Mark(NamedTuple):
    """A shown link (`a` with `href`, HTML Standard §4.6.1 hyperlink) or image (`img` with `src`): `text[start:end]` is
    what it renders (empty for an image), `target` its `href` or `src` as the document states it, and `name` the name
    it announces beside its text: WAI-ARIA `aria-label` or the HTML `title` for a link, else the `alt` of the image it
    holds; an image's `alt` (HTML Standard §4.8.4.4)."""

    kind: MarkKind
    start: int
    end: int
    path: str
    target: str
    name: str


@dataclass(frozen=True)
class CleanedText:
    """Lines of visible text, one per line box, separated by `\\n`; the runs are ordered and disjoint. `marks` are the
    shown links and images in document order."""

    text: str
    offsets: tuple[TextRun, ...]
    marks: tuple[Mark, ...] = ()


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
        elif isinstance(item, _Mark):
            builder.mark(item)
        else:
            stack.extend(reversed(_enter(item, shown, len(builder.runs))))
    return CleanedText("".join(builder.parts), tuple(builder.runs), tuple(builder.marks)), tuple(shown)


def fragment_text(value: str) -> str | None:
    """The text `value` renders when it is an HTML fragment holding element markup, as structured data's text
    sometimes is (a description written as `<p>…</p><ul>…</ul>`), else `None`: a value without an element (`1 < 2`)
    is text. HTML Standard parsing builds the fragment's elements and decodes its character references once; its text
    is rendered as the page's (`render`), block boxes on lines of their own."""
    if "<" not in value:
        return None
    body = LexborHTMLParser(value).body
    if body is None or next(body.iter(), None) is None:  # no element child, so no element at all
        return None
    return render(body)[0].text


class _Enter(NamedTuple):
    node: LexborNode
    path: str
    invisible: bool


class _Text(NamedTuple):
    text: str
    path: str


class _Separate(NamedTuple):
    separator: str


class _Mark(NamedTuple):
    """Ends a shown link or image; `first_run` is the number of text runs written before it began."""

    kind: MarkKind
    path: str
    target: str
    name: str
    first_run: int


_Item = _Enter | _Text | _Separate | _Mark


def _enter(item: _Enter, shown: list[str], runs: int) -> list[_Item]:
    """What an element contributes, in document order: its children, between the separators of its box, and its mark
    when it is a shown link or image (`runs`: the text runs written so far). Adds its shown attributes to `shown` when
    it is visible."""
    attributes = item.node.attributes
    tag = item.node.tag or ""
    style = _declarations(attributes)
    if _hidden(tag, attributes, style):
        return []
    invisible = _invisible(style.get("visibility"), inherited=item.invisible)
    if not invisible:
        shown.extend(value for name in _SHOWN_ATTRIBUTES if (value := attributes.get(name)))
    full = None if invisible else _completed(item.node, attributes.get("title"))
    children: list[_Item] = [_Text(full, item.path)] if full else _children(item.node, item.path, invisible)
    mark = None if invisible else _mark(item.node, tag, item.path, runs)
    children.extend((mark,) if mark else ())
    separator = _separator(tag)
    return [_Separate(separator), *children, _Separate(separator)] if separator else children


def _mark(node: LexborNode, tag: str, path: str, runs: int) -> _Mark | None:
    """The mark of a link (HTML Standard §4.6.1: an `a` element with an `href` is a hyperlink) or an image (§4.8.4: an
    `img` with a `src`), else None. A link's announced name is WAI-ARIA 1.2's `aria-label`, then the HTML `title`
    (advisory information), then the `alt` of the first image it holds, its replacement text."""
    attributes = node.attributes
    if tag == "img" and (src := attributes.get("src")):
        return _Mark("image", path, src, _collapsed(attributes.get("alt")), runs)
    if tag != "a" or not (href := attributes.get("href")):
        return None
    name = attributes.get("aria-label") or attributes.get("title")
    if not name and (image := node.css_first("img[alt]")) is not None:
        name = image.attributes.get("alt")
    return _Mark("link", path, href, _collapsed(name), runs)


def _collapsed(value: str | None) -> str:
    return " ".join(compose(value or "").split())


def _completed(node: LexborNode, title: str | None) -> str | None:
    return completed(node.text(deep=True), title)


def completed(text: str, title: str | None) -> str | None:
    """An element's `title` when its `text` is that title cut short: the text ends in an ellipsis (U+2026, or the
    three full stops it decomposes to under NFKC) and the title starts with the text before it and goes on. HTML
    Standard §3.2.6.1: `title` is advisory information for its element, here the full text the element shows cut."""
    if not title:
        return None
    shown_text = " ".join(compose(text).split())
    if not shown_text.endswith(_ELLIPSES):
        return None
    cut = unicodedata.normalize("NFKC", shown_text).removesuffix(_ELLIPSIS).rstrip()
    full = " ".join(compose(title).split())
    return full if cut and full.startswith(cut) and len(full) > len(cut) else None


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


def shown(node: LexborNode) -> bool:
    """Whether the element is shown by the rules that make the cleaned text: neither it nor an ancestor is hidden
    (`_hidden`), and the nearest `visibility` it inherits (CSS 2 §11.2) does not hide it."""
    visibility: str | None = None
    current: LexborNode | None = node
    while current is not None and current.is_element_node:
        attributes = current.attributes
        style = _declarations(attributes)
        if _hidden(current.tag or "", attributes, style):
            return False
        visibility = visibility or style.get("visibility")
        current = current.parent
    return not _invisible(visibility, inherited=False)


def hidden(tag: str, attributes: _Attributes) -> bool:
    """Whether an element with `tag` and `attributes` is not rendered, with its whole subtree (`_hidden`)."""
    return _hidden(tag, attributes, _declarations(attributes))


def concealed(attributes: _Attributes) -> bool:
    """Whether an element's own attributes keep it and its subtree from rendering, as a document hides content it may
    show later (a streamed segment before its script moves it into place): the `hidden` attribute (HTML Standard §6.1)
    or an inline `display: none` (CSS Display 3 §2.5)."""
    return _concealed(attributes, _declarations(attributes))


def _concealed(attributes: _Attributes, style: dict[str, str]) -> bool:
    return "hidden" in attributes or style.get("display") == "none"


def _hidden(tag: str, attributes: _Attributes, style: dict[str, str]) -> bool:
    """Not rendered at all, with its whole subtree."""
    # HTML Standard, Rendering, "Hidden elements": `[hidden]`, `input[type=hidden i]`, `dialog:not([open])`.
    if tag in NOT_RENDERED or _concealed(attributes, style):
        return True
    if tag == "input" and (attributes.get("type") or "").strip().lower() == "hidden":
        return True
    if tag == "dialog" and "open" not in attributes:
        return True
    # WAI-ARIA 1.2, `aria-hidden="true"`: the element and its subtree are hidden from every user.
    return (attributes.get("aria-hidden") or "").strip().lower() == "true"


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
        self.marks: list[Mark] = []
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

    def mark(self, mark: _Mark) -> None:
        """Records a link or image that ends here: its span runs from the first text run written inside it, if any."""
        written = self.runs[mark.first_run :]
        start = written[0].start if written else self._length
        self.marks.append(Mark(mark.kind, start, self._length, mark.path, mark.target, mark.name))

    def _append(self, piece: str) -> None:
        self.parts.append(piece)
        self._length += len(piece)
