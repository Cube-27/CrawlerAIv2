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

trafilatura reads a listing's item grid as boilerplate (link-dense repeated blocks), so for a page fetched as a listing
the items (`acquire.items.item_blocks`) are taken out of its copy of the tree and written as a Markdown list after the
rest of the content (`_items`): each item's links, images and text, in document order. Other pages are unchanged.
"""

import re
from collections.abc import Iterator
from copy import deepcopy

import trafilatura
from lxml.html import HtmlElement

from crawlerai.acquire.items import is_hyperlink, item_blocks
from crawlerai.content.dom import document_base_url
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import NOT_RENDERED
from crawlerai.db.models import PageKind

# CommonMark §4.5: a fenced code block opens and closes with a run of three or more backticks or tildes.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# CommonMark §5.2: a list item starts with a bullet (`-`, `+`, `*`) or an ordered marker (digits, then `.` or `)`),
# then whitespace; its indentation is what nests it, and its content starts after that whitespace.
_LIST_ITEM = re.compile(r"^([ \t]*(?:[-+*]|\d{1,9}[.)]))([ \t]+)")
# Elements whose content is not an item's text: those never rendered (`content.text`), and form controls (HTML
# Standard §4.10), which a reader of the page uses rather than reads.
_NOT_TEXT = NOT_RENDERED | {"button", "select", "input", "textarea", "option"}


def markdown(page: ParsedPage, final_url: str, page_kind: PageKind | None = None) -> str:
    """The main content as Markdown, with its links and images, and a listing's items; `""` when there is none.
    `page_kind` is the kind the capture was fetched as."""
    tree = _absolute(page, final_url)
    items = item_blocks(tree) if page_kind == "listing" else ()
    for item in items:
        item.drop_tree()  # lxml keeps the item's tail text in the tree
    extracted = trafilatura.extract(
        tree, output_format="markdown", include_links=True, include_images=True, favor_precision=True
    )
    listed = "\n".join(f"- {line}" for line in map(_item, items) if line)
    return _tidy("\n\n".join(part for part in (extracted, listed) if part))


def _absolute(page: ParsedPage, final_url: str) -> HtmlElement:
    """A copy of the page's lxml tree with every link and resource target resolved against the document base URL
    (RFC 3986 §5.2). trafilatura's own `url=` resolves link targets against the host alone, so `about/x` under a base
    of `/site/` would lose `/site/`. A target that does not parse is left as written."""
    tree = deepcopy(page.lxml_tree)
    tree.make_links_absolute(document_base_url(page, final_url), resolve_base_href=False, handle_failures="ignore")
    return tree


def _item(item: HtmlElement) -> str:
    """One item on one line: its hyperlinks as Markdown links (an image link's image as its text), its other images,
    and its other visible text, in document order, whitespace collapsed (CSS Text Level 3, `white-space: normal`)."""
    return " ".join("".join(_parts(item)).split())


def _parts(element: HtmlElement) -> Iterator[str]:
    """The element's content as Markdown pieces, without its tail, which follows it in its parent."""
    if is_hyperlink(element):
        yield f" {_link(element)} "
    elif element.tag == "img":
        yield f" {_image(element)} "
    elif isinstance(element.tag, str) and element.tag not in _NOT_TEXT:  # not a comment or processing instruction
        yield element.text or ""
        for child in element:
            yield from _parts(child)
            yield child.tail or ""


def _link(link: HtmlElement) -> str:
    text = " ".join(link.text_content().split()) or link.get("title", "")
    label = _escaped(text) if text else " ".join(_image(image) for image in link.iter("img"))
    return f"[{label}]({_target(link.get('href', ''))})"


def _image(image: HtmlElement) -> str:
    return f"![{_escaped(' '.join(image.get('alt', '').split()))}]({_target(image.get('src', ''))})"


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
