"""A listing's blocks as role C reads them (llm spec, "Role C on listings"): each block's span of the cleaned text,
verbatim, under its locator (its position in the bound group and its item URL), with the row its values fill and the
row fields that row does not publish.

The span is the one the block's node path carries (`content.segment.text_path`, `ParsedPage.text_spans`), so a value
role C grounds in it is a span of the cleaned text (INV-12). A block whose path no run carries is not read: it renders
no text, or libxml2 and HTML tree construction built different trees there for malformed markup.

**Enclosing items.** A listing may nest its items: each item of an outer repeated group (a building, a store, a date)
holds a repeated group of its own (its units, products, sessions), and states once, before that group, what all of
them share (a name, an address, column headings). Rows then are the inner blocks, and what they share is not in their
span. A block that lies inside a block of another repeated group, where two or more blocks of that group hold rows
(the nesting repeats per outer item; one section holding a grid is no nesting), is read with that enclosing block's
text before its first inner item (the first block of any repeated group inside it): its context, a span of the cleaned
text too.
"""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from lxml.html import HtmlElement

from crawlerai.collect.items.bind import RowBlock
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import text_path

# The cleaned text's line break (`content.text`: one between two line boxes).
_BREAK = "\n"
# HTML Standard §4.3.6: the heading content elements.
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
# A span of the cleaned text: its start offset and its text.
Segment = tuple[int, str]


@dataclass(frozen=True, slots=True)
class BlockText:
    """One block as role C reads it: its position in the bound group and its item URL (its locator), the row entity
    its values fill, its text (the cleaned text from `start`, verbatim), the row fields its row does not publish, and
    the text its enclosing item states for it (from `context_start`; empty when none, module docstring). `breaks` are
    the offsets in the cleaned text, inside its text or context, where two text runs meet (an element boundary the
    text shows no space at); `heading` is the span of its first heading (`h1`-`h6`, HTML Standard §4.3.6: the
    heading of the item it is), None when it has none."""

    index: int
    url: str
    row: str
    start: int
    text: str
    fields: tuple[str, ...]
    context: str = ""
    context_start: int = 0
    breaks: frozenset[int] = frozenset()
    heading: tuple[int, int] | None = None

    @property
    def line(self) -> str:
        """The context, then the text, on one line, each line break shown as a space."""
        shown = f"{self.context}{_BREAK}{self.text}" if self.context else self.text
        return shown.replace(_BREAK, " ")

    @property
    def segments(self) -> tuple[Segment, ...]:
        """The spans a claim of this block is grounded in: its own text first, then its context."""
        own: Segment = (self.start, self.text)
        return (own, (self.context_start, self.context)) if self.context else (own,)

    def cut(self, limit: int) -> "BlockText":
        """The block within `limit` characters of line: its own text cut to it, the context left out when both do not
        fit (the block's text is what its row is)."""
        text = self.text[:limit]
        context = self.context if len(self.context) + len(_BREAK) + len(text) <= limit else ""
        return replace(self, text=text, context=context, context_start=self.context_start if context else 0)


def block_texts(
    page: ParsedPage, blocks: Sequence[RowBlock], fields: Mapping[str, Sequence[str]]
) -> tuple[BlockText, ...]:
    """The text of each of `blocks` whose row (`RowBlock.row`) `fields` asks fields of, for role C to fill them, with
    its enclosing item's context (module docstring); a block the cleaned text holds none of is left out."""
    contexts = _contexts(page, [row_block.block.element for row_block in blocks])
    texts = (
        _block_text(page, row_block, fields[row_block.row], contexts.get(row_block.block.element))
        for row_block in blocks
        if fields.get(row_block.row)
    )
    return tuple(text for text in texts if text is not None)


def _block_text(
    page: ParsedPage, row_block: RowBlock, fields: Sequence[str], context: Segment | None = None
) -> BlockText | None:
    """The block's text for role C to fill `fields` of its row; None when the cleaned text holds none of it."""
    span = page.text_spans.get(text_path(row_block.block.element))
    if span is None or span[0] == span[1]:
        return None
    start, end = span
    text = page.cleaned_text.text[start:end]
    context_start, context_text = context if context is not None else (0, "")
    breaks = _breaks(page, start, end) | _breaks(page, context_start, context_start + len(context_text))
    return BlockText(
        row_block.index,
        row_block.block.link,
        row_block.row,
        start,
        text,
        tuple(fields),
        context_text,
        context_start,
        breaks,
        _heading(page, row_block.block.element),
    )


def _breaks(page: ParsedPage, start: int, end: int) -> frozenset[int]:
    """The offsets inside `[start, end)` where a text run of the cleaned text starts."""
    starts = page.run_starts
    return frozenset(starts[bisect_right(starts, start) : bisect_left(starts, end)])


def _heading(page: ParsedPage, element: HtmlElement) -> tuple[int, int] | None:
    """The span of the element's first heading (HTML Standard §4.3.6) in the cleaned text, None when it has none or it
    renders no text."""
    heading = next(element.iterdescendants(*_HEADINGS), None)
    return None if heading is None else page.text_spans.get(text_path(heading))


def _contexts(page: ParsedPage, elements: Sequence[HtmlElement]) -> dict[HtmlElement, Segment]:
    """Each element's enclosing item's context (module docstring), for the elements that have one."""
    group_of = {block: number for number, group in enumerate(page.item_groups) for block in group}
    enclosed: dict[HtmlElement, list[HtmlElement]] = defaultdict(list)
    for element in elements:
        if (owner := _enclosing(element, group_of)) is not None:
            enclosed[owner].append(element)
    # The nesting repeats: two or more blocks of the enclosing group hold rows.
    holding = Counter(group_of[owner] for owner in enclosed)
    contexts: dict[HtmlElement, Segment] = {}
    for owner, inner in enclosed.items():
        if holding[group_of[owner]] < 2 or (context := _context(page, owner, _first_item(owner, group_of))) is None:
            continue
        contexts.update(dict.fromkeys(inner, context))
    return contexts


def _first_item(owner: HtmlElement, group_of: Mapping[HtmlElement, int]) -> HtmlElement | None:
    """The first block of any repeated group inside the enclosing block, in document order: its text and what follows
    are the inner items', not what they share."""
    return next((node for node in owner.iterdescendants() if node in group_of), None)


def _enclosing(element: HtmlElement, group_of: Mapping[HtmlElement, int]) -> HtmlElement | None:
    """The nearest ancestor of a block of a repeated group that is a block of another one; None for a top-level
    block or one outside every group."""
    if element not in group_of:
        return None
    node = element.getparent()
    while node is not None and node not in group_of:
        node = node.getparent()
    return node


def _context(page: ParsedPage, owner: HtmlElement, first: HtmlElement | None) -> Segment | None:
    """The enclosing block's text before `first`, its first inner item; None when it shows none."""
    if first is None:
        return None
    outer = page.text_spans.get(text_path(owner))
    inner = page.text_spans.get(text_path(first))
    if outer is None or inner is None or inner[0] <= outer[0]:
        return None
    text = page.cleaned_text.text[outer[0] : inner[0]].rstrip()
    return (outer[0], text) if text.strip() else None
