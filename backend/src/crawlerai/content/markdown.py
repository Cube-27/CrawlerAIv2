"""The `markdown` content format (rest-api spec): the page minus its furniture, as Markdown.

The page's furniture (`content.regions`: what it never renders, its landmarks and the elements its class and id names
call furniture) is taken out of a copy of the page's lxml tree, so the capture is parsed once (INV-26) and the shared
tree stays as parsed; everything left is written, in document order, as CommonMark with GFM tables. No per-site rules
(C2). A browser capture's body is the rendered DOM, so the same call covers both rungs.

The writer follows the HTML Standard's rendering: an element the user-agent style sheet lays out as a block
(`content.text.LINE_BOXES`, table cells) starts a block of its own, and so does an inline element that holds one (CSS
2 §9.2.1.1: the inline box is broken around the block), but for a hyperlink, which stays one link around its content.
A run of inline content between blocks is a paragraph, its whitespace collapsed to one space (CSS Text Level 3,
`white-space: normal`) and a `br` a line break. Headings (`h1`-`h6`) are ATX headings (CommonMark §4.2); `ul`, `ol`
and `menu` are lists (§5.3), their items' blocks on the item's lines and nested lists indented under them; a table
with no table inside it is a GFM table, its first row the header and each cell's content on one line, while a table
that holds tables lays out the page and is read as blocks; `pre` is a fenced code block (§4.5) of its text as written;
`blockquote` is a block quote (§5.1); `hr` a thematic break (§4.1). Inline, a hyperlink (an `a` with an `href`, HTML
Standard §4.6.1) is a link (§6.3) whose text is its content, else its `aria-label` or `title`; an image is an image
(§6.4) of its `alt`, from its `src`, else, where `src` is an inline `data:` placeholder (RFC 2397), from the `data-src`
a lazy loader keeps it in (HTML Standard §3.2.6.6); `strong`/`b` and `em`/`i` are strong and emphasis (§6.2), `code`,
`kbd` and `samp` code spans (§6.1). A form control's value (`input`, `select`, `textarea`, HTML Standard §4.10) is
what a reader of the page enters, not reads: it is no text.

Link and image targets are resolved against the document base URL (HTML Living Standard §2.4.1; RFC 3986 §5.2), so
the Markdown can be read away from the page. The source's layout whitespace is not content: in Markdown an indent of
four spaces starts a code block and a run of blank lines means one (CommonMark §4.4, §4.9). So a line's leading
whitespace is dropped unless it nests a list item or continues one, and blank-line runs become one; fenced code is
kept as written.

A page that shows nothing once scripts would run (a client-rendered application) is read as a user agent with scripting
disabled renders it: its `noscript` content, which such a page serves to readers that run no script (HTML Standard
§4.12.2), is written too.

A JSON body (an `api` capture's, `ParsedPage.json_body`) is no HTML document: its Markdown is the answer itself,
pretty-printed in one fenced code block whose info string is `json` (CommonMark §4.5), never its text read as HTML
(D-1473).
"""

import json
import re
from collections.abc import Callable, Iterator
from copy import deepcopy

from lxml.html import HtmlElement

from crawlerai.content.dom import document_base_url, tokens
from crawlerai.content.md_blocks import FENCE, LIST_ITEM
from crawlerai.content.page import ParsedPage
from crawlerai.content.regions import drop_furniture
from crawlerai.content.text import CELLS, LINE_BOXES
from crawlerai.core import json_text
from crawlerai.normalize.strings import collapse

_BLOCKS = LINE_BOXES | CELLS
_HEADINGS = {f"h{level}": level for level in range(1, 7)}
_LISTS = frozenset({"ul", "ol", "menu"})
# HTML Standard §4.10: controls whose value the reader enters or picks.
_CONTROLS = frozenset({"input", "select", "textarea", "option", "optgroup", "datalist"})
_STRONG = frozenset({"strong", "b"})
_EMPHASIS = frozenset({"em", "i"})
_CODE = frozenset({"code", "kbd", "samp"})
# HTML Living Standard §2.3.1: ASCII whitespace, which `white-space: normal` collapses.
_WHITESPACE = re.compile(r"[\t\n\f\r ]+")
_SPACED_BREAK = re.compile(r" *\n *")
_SPACES = re.compile(" {2,}")
# HTML Standard §4.5.15: a `code` element names its language with a `language-` class.
_LANGUAGE = "language-"
_INLINE_DATA = "data:"
# CommonMark §4.2: an ATX heading's opening sequence. In a list item a heading is written as its text: an item's lines
# are its own (§5.2), and readers of the Markdown by block (`content.md_blocks`) take a heading line for a section.
_HEADING_MARK = re.compile(r"^#{1,6} ")
_JAVASCRIPT = re.compile(r"\s*javascript:", re.IGNORECASE)


def markdown(page: ParsedPage, final_url: str, *, prune: Callable[[HtmlElement], None] | None = None) -> str:
    """The page minus its furniture as Markdown, with its links and images; `""` when nothing is left. `prune`, when
    given, takes more out of the copy of the tree that is written, after its furniture (`content.fit`)."""
    if page.json_body:
        return json_block(page.html)
    return _written(page, final_url, prune, scripting=True) or _written(page, final_url, prune, scripting=False)


def _written(page: ParsedPage, final_url: str, prune: Callable[[HtmlElement], None] | None, *, scripting: bool) -> str:
    tree = _absolute(page, final_url)
    drop_furniture(tree, scripting=scripting)
    if prune is not None:
        prune(tree)
    body = tree.find("body")
    return _tidy("\n\n".join(_Writer(tree).blocks(body if body is not None else tree)))


def json_block(text: str) -> str:
    """A JSON text (RFC 8259) pretty-printed, two spaces per level and its characters as written, in a fenced code
    block: the fence is a run of backticks longer than any inside the text, so none closes it (CommonMark §4.5). `""`
    for a text that is no JSON, or holds a number that decodes to no finite value (`1e400`)."""
    try:
        value = json_text.parse(text)
        pretty = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)  # RFC 8259 §6: no Infinity, NaN
    except (ValueError, RecursionError):  # writing a value back nests as deep as reading it
        return ""
    fence = _fence(pretty, "`", 3)
    return f"{fence}json\n{pretty}\n{fence}"


def _fence(text: str, mark: str, least: int) -> str:
    """A run of `mark` longer than any run of it in `text`, and at least `least` long."""
    return mark * max(least, 1 + max((len(run) for run in re.findall(f"{re.escape(mark)}+", text)), default=0))


def _absolute(page: ParsedPage, final_url: str) -> HtmlElement:
    """A copy of the page's lxml tree with every link and resource target resolved against the document base URL
    (RFC 3986 §5.2), a lazy image's source in its `src` first. A target that does not parse is left as written."""
    tree = deepcopy(page.lxml_tree)
    for image in tree.iter("img"):
        _lazy_source(image)
    tree.make_links_absolute(document_base_url(page, final_url), resolve_base_href=False, handle_failures="ignore")
    return tree


class _Writer:
    """Writes a tree as Markdown blocks (module docstring)."""

    def __init__(self, tree: HtmlElement) -> None:
        # The elements that hold a block: an inline one among them is broken around it.
        self.holding: set[HtmlElement] = set()
        for block in tree.iter(*_BLOCKS):
            for ancestor in block.iterancestors():
                if ancestor in self.holding:
                    break
                self.holding.add(ancestor)

    def is_block(self, element: HtmlElement) -> bool:
        return element.tag in _BLOCKS or (element.tag != "a" and element in self.holding)

    def blocks(self, element: HtmlElement) -> list[str]:
        """The element's content as blocks: each block child's, and each run of inline content between them as a
        paragraph."""
        out: list[str] = []
        run = [_spaced(element.text)]
        for child in element:
            if self.is_block(child):
                _flush(out, run)
                out.extend(self.block(child))
            else:
                run.append(self.inline(child))
            run.append(_spaced(child.tail))
        _flush(out, run)
        return out

    def block(self, element: HtmlElement) -> list[str]:
        tag = element.tag
        if tag in _HEADINGS:
            text = _line(self.inline_content(element))
            return [f"{'#' * _HEADINGS[tag]} {text}"] if text else []
        if tag in _LISTS:
            return [text] if (text := self.listed(element)) else []
        if tag == "table":
            return self.table(element)
        if tag == "pre":
            return _fenced(element)
        if tag == "blockquote":
            return _quoted(self.blocks(element))
        if tag == "hr":
            return ["***"]  # CommonMark §4.1; `---` under a line would make it a setext heading (§4.3)
        return self.blocks(element)

    def inline(self, element: HtmlElement) -> str:
        """The element's content as inline Markdown, without its tail."""
        tag = element.tag
        if not isinstance(tag, str) or tag in _CONTROLS:  # a comment or processing instruction is no content
            return ""
        if tag == "br":
            return "\n"
        if tag == "img":
            return _image(element)
        if tag == "a" and element.get("href") is not None:
            return self.link(element)
        content = self.inline_content(element)
        if tag in _STRONG:
            return _wrapped(content, "**")
        if tag in _EMPHASIS:
            return _wrapped(content, "*")
        if tag in _CODE:
            return _wrapped(content, _fence(content, "`", 1))
        return content

    def inline_content(self, element: HtmlElement) -> str:
        """The element's children and text as inline Markdown, a block among them set apart by spaces."""
        parts = [_spaced(element.text)]
        for child in element:
            piece = self.inline(child)
            parts.append(f" {piece} " if child.tag in _BLOCKS else piece)
            parts.append(_spaced(child.tail))
        return "".join(parts)

    def link(self, link: HtmlElement) -> str:
        label = _line(self.inline_content(link))
        label = label or _escaped(collapse(link.get("aria-label") or link.get("title") or ""))
        href = link.get("href", "")
        if not label or _JAVASCRIPT.match(href):  # a `javascript:` URL runs a script, it leads nowhere
            return label
        return f"[{label}]({_target(href)})"

    def listed(self, element: HtmlElement) -> str:
        """The list's items, numbered from its `start` when ordered; each item's blocks on its lines, indented to its
        content column (CommonMark §5.2)."""
        ordered = element.tag == "ol"
        number = int(start) if (start := element.get("start", "").strip()).isdecimal() and len(start) < 9 else 1
        lines: list[str] = []
        for blocks in self.items(element):
            body = "\n".join(_HEADING_MARK.sub("", block, count=1) for block in blocks if block)
            if not body:
                continue
            marker = f"{number}." if ordered else "-"
            number += 1
            first, *rest = body.split("\n")
            pad = " " * (len(marker) + 1)
            lines += [f"{marker} {first}", *(pad + line if line else "" for line in rest)]
        return "\n".join(lines)

    def items(self, element: HtmlElement) -> Iterator[list[str]]:
        """The blocks of each item of a list: an `li`'s, and each block of anything else the list holds."""
        for child in element:
            if child.tag == "li":
                yield self.blocks(child)
            elif self.is_block(child):
                yield from ([block] for block in self.block(child))
            else:
                yield [_line(self.inline(child))]

    def table(self, table: HtmlElement) -> list[str]:
        """A GFM table of the table's rows, the first the header, after its caption; a table holding tables, or of
        one column, as blocks."""
        if next(table.iterdescendants("table"), None) is not None:
            return self.blocks(table)
        caption = table.find("caption")
        head = [text] if caption is not None and (text := _line(self.inline_content(caption))) else []
        rows = [[self.cell(cell) for cell in row if cell.tag in CELLS] for row in table.iter("tr")]
        rows = [row for row in rows if any(row)]
        width = max((len(row) for row in rows), default=0)
        if width < 2:
            return [*head, *(row[0] for row in rows)]
        lines = [_row(rows[0], width), _row(["---"] * width, width), *(_row(row, width) for row in rows[1:])]
        return [*head, "\n".join(lines)]

    def cell(self, cell: HtmlElement) -> str:
        # GFM tables: a cell is one line, and `|` inside it is escaped.
        return _line(self.inline_content(cell)).replace("|", r"\|")


def _spaced(text: str | None) -> str:
    return _WHITESPACE.sub(" ", text or "")


def _paragraph(text: str) -> str:
    """Inline Markdown as a paragraph: spaces around a line break and runs of spaces collapsed, trimmed."""
    return _SPACES.sub(" ", _SPACED_BREAK.sub("\n", text)).strip()


def _line(text: str) -> str:
    return _paragraph(text).replace("\n", " ")


def _flush(out: list[str], run: list[str]) -> None:
    text = _paragraph("".join(run))
    run.clear()
    if text:
        out.append(text)


def _wrapped(content: str, mark: str) -> str:
    """The content between `mark`s, its outer spaces outside them (CommonMark §6.2: a delimiter run next to a space
    opens or closes nothing)."""
    core = content.strip(" ")
    if not core.strip():
        return content
    lead = content[: len(content) - len(content.lstrip(" "))]
    trail = content[len(content.rstrip(" ")) :]
    if mark.startswith("`") and (core.startswith("`") or core.endswith("`")):
        core = f" {core} "  # CommonMark §6.1: one space each side is stripped from a code span's content
    return f"{lead}{mark}{core}{mark}{trail}"


def _lazy_source(image: HtmlElement) -> None:
    """Moves a lazy loader's `data-src` into an image's `src` that is missing or an inline placeholder."""
    source = image.get("src", "").strip()
    lazy = image.get("data-src", "").strip()
    if (not source or source.startswith(_INLINE_DATA)) and lazy:
        image.set("src", lazy)


def _image(image: HtmlElement) -> str:
    source = image.get("src", "").strip()
    if not source or source.startswith(_INLINE_DATA):
        return ""
    return f"![{_escaped(collapse(image.get('alt', '')))}]({_target(source)})"


def _fenced(pre: HtmlElement) -> list[str]:
    text = pre.text_content().strip("\n")
    if not text.strip():
        return []
    code = pre.find(".//code")
    names = tokens(pre.get("class")) + (tokens(code.get("class")) if code is not None else [])
    language = next((name[len(_LANGUAGE) :] for name in names if name.startswith(_LANGUAGE)), "")
    fence = _fence(text, "`", 3)
    return [f"{fence}{language}\n{text}\n{fence}"]


def _quoted(blocks: list[str]) -> list[str]:
    inner = "\n\n".join(blocks)
    return ["\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))] if inner else []


def _row(cells: list[str], width: int) -> str:
    return "| " + " | ".join([*cells, *([""] * (width - len(cells)))]) + " |"


def _escaped(text: str) -> str:
    # CommonMark §6.3: brackets in link text are escaped with a backslash, as is the backslash.
    return text.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")


def _target(url: str) -> str:
    # CommonMark §6.3: a link destination holds no spaces or unbalanced parentheses; RFC 3986 §2.1 percent-encodes them.
    return url.strip().replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _tidy(text: str) -> str:
    """Layout whitespace dropped as the module docstring says; fenced code untouched."""
    lines: list[str] = []
    fence: str | None = None
    items: list[int] = []  # the content columns of the list items open above, outermost first
    for line in text.splitlines():
        opened = FENCE.match(line)
        if fence is None and opened is None:
            _add_text_line(lines, line, items)
            continue
        lines.append(line)
        if fence is None:
            fence = opened.group(1) if opened is not None else None
        elif _closes(opened, fence):
            fence = None
    return "\n".join(lines).strip("\n")


def _add_text_line(lines: list[str], line: str, items: list[int]) -> None:
    """Adds the line, and updates `items` to the list items open after it. A list item keeps the indentation that
    nests it, in the open items whose content columns it reaches, and closes the deeper ones. Any other line indented
    to an open item's content column continues the deepest such item (CommonMark §5.2), closing the deeper ones, and
    is indented to exactly that column, so further layout indentation starts no code block inside it. Any other line
    loses its layout indentation and, unless it continues the paragraph right above (a lazy continuation line), closes
    every item. A blank line right after another is dropped."""
    marker = LIST_ITEM.match(line)
    text = line.strip()
    indent = len(line) - len(line.lstrip())
    if marker is not None:
        del items[_reached(items, indent) :]
        items.append(_content_column(marker))
        kept = line.rstrip()
    elif text and items and indent >= items[0]:
        del items[_reached(items, indent) :]
        kept = " " * items[-1] + text
    else:
        kept = text
        if text and not (lines and lines[-1]):  # not a lazy continuation
            items.clear()
    if kept or (lines and lines[-1]):
        lines.append(kept)


def _reached(items: list[int], indent: int) -> int:
    """How many of the open items, outermost first, a line indented by `indent` stays in: those whose content column
    it reaches."""
    return next((depth for depth, column in enumerate(items) if column > indent), len(items))


def _content_column(marker: re.Match[str]) -> int:
    # CommonMark §5.2: the content starts after the marker's spaces; after five or more, the first is the separator and
    # the rest start an indented code block, so the content column is the marker's end plus one.
    spaces = len(marker[2])
    return marker.end(1) + (spaces if spaces <= 4 else 1)


def _closes(opened: re.Match[str] | None, fence: str) -> bool:
    # CommonMark §4.5: the closing fence uses the opening's character, at least as many times.
    return opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence)
