"""The `markdown` content format (SPEC-07 §4.5, ARCHITECTURE §8.5): the page's main content, by trafilatura.

trafilatura reads the page's lxml tree, not the body, so the capture is parsed once (INV-26). This module resolves
link targets on a copy of that tree, so the shared tree stays as parsed. No per-site rules (C2). A browser capture's
body is the rendered DOM, so the same call covers both rungs.

Link and image targets are resolved against the document base URL (HTML Living Standard §2.4.1; RFC 3986 §5.2), so
the Markdown can be read away from the page. The source's layout whitespace is not content: outside `pre`, HTML
renders indentation and line breaks as one space (CSS Text Level 3, `white-space: normal`), while in Markdown an
indent of four spaces starts a code block and a run of blank lines means one (CommonMark §4.4, §4.9). So a line's
leading whitespace is dropped unless it nests a list item or continues one, and blank-line runs become one; fenced
code is kept as written.
"""

import re
from copy import deepcopy

import trafilatura
from lxml.html import HtmlElement

from crawlerai.content.dom import document_base_url
from crawlerai.content.page import ParsedPage

# CommonMark §4.5: a fenced code block opens and closes with a run of three or more backticks or tildes.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# CommonMark §5.2: a list item starts with a bullet (`-`, `+`, `*`) or an ordered marker (digits, then `.` or `)`),
# then whitespace; its indentation is what nests it, and its content starts after that whitespace.
_LIST_ITEM = re.compile(r"^([ \t]*(?:[-+*]|\d{1,9}[.)]))([ \t]+)")


def markdown(page: ParsedPage, final_url: str) -> str:
    """The main content as Markdown, with its links and images; `""` when trafilatura finds none."""
    extracted = trafilatura.extract(
        _absolute(page, final_url),
        output_format="markdown",
        include_links=True,
        include_images=True,
        favor_precision=True,
    )
    return _tidy(extracted or "")


def _absolute(page: ParsedPage, final_url: str) -> HtmlElement:
    """A copy of the page's lxml tree with every link and resource target resolved against the document base URL
    (RFC 3986 §5.2). trafilatura's own `url=` resolves link targets against the host alone, so `about/x` under a base
    of `/site/` would lose `/site/`. A target that does not parse is left as written."""
    tree = deepcopy(page.lxml_tree)
    tree.make_links_absolute(document_base_url(page, final_url), resolve_base_href=False, handle_failures="ignore")
    return tree


def _tidy(text: str) -> str:
    """Layout whitespace dropped as the module docstring says; fenced code untouched."""
    lines: list[str] = []
    fence: str | None = None
    items: list[int] = []  # the content columns of the list items open above, outermost first
    for line in text.splitlines():
        opened = _FENCE.match(line)
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
    marker = _LIST_ITEM.match(line)
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
