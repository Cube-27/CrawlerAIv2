"""The text of a listing's items (D-1478): the spans of the cleaned text (SPEC-05 §4.4) that the page's repeated item
blocks render (`acquire.items.item_blocks`, ARCHITECTURE §8.6), joined into one text with a map back to the cleaned
text's offsets. Role C reads it on a listing, so a long run of menus or filters before or between the items does not
crowd them out of what the model reads (and its spans still ground in the cleaned text, INV-12).

The item blocks come from the lxml tree and the cleaned text's runs from the selectolax tree. An item's runs are those
whose node path (an XPath 1.0 location path of positional steps, `content.text.node_xpath`) is the item's own path or
starts with it; libxml2 and HTML tree construction can build different trees for malformed markup, so an item whose
path no run carries is left out, and a page with fewer than `MIN_ITEMS` items found has no item text.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from lxml.html import HtmlElement

from crawlerai.acquire.items import MIN_ITEMS, item_blocks
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import CleanedText, xpath_step

# The separator between two items' spans in the joined text: a line break, as between two line boxes (`content.text`).
_SEPARATOR = "\n"


@dataclass(frozen=True)
class Piece:
    """`text[at:at + length]` of a `TextView` is `source[start:start + length]`."""

    at: int
    start: int
    length: int


@dataclass(frozen=True)
class TextView:
    """A text made of pieces of a source text, and where each piece is in the source."""

    text: str
    pieces: tuple[Piece, ...]

    @classmethod
    def whole(cls, text: str) -> "TextView":
        return cls(text, (Piece(0, 0, len(text)),))

    def first(self, count: int) -> "TextView":
        """The view of the first `count` pieces."""
        if count >= len(self.pieces):
            return self
        kept = self.pieces[:count]
        return TextView(self.text[: kept[-1].at + kept[-1].length], kept)

    def piece_text(self, index: int) -> str:
        """The text of the view's piece `index` (cut short when the view's text was cut)."""
        piece = self.pieces[index]
        return self.text[piece.at : piece.at + piece.length]

    def source_span(self, start: int, end: int) -> tuple[int, int] | None:
        """The source offsets of `text[start:end]`, or None when the span is not inside one piece (it would join two
        places of the source that are not adjacent)."""
        for piece in self.pieces:
            if piece.at <= start and end <= piece.at + piece.length:
                shift = piece.start - piece.at
                return start + shift, end + shift
        return None


def item_text(page: ParsedPage) -> TextView | None:
    """The cleaned text's spans of the page's item blocks, in document order; None when fewer than `MIN_ITEMS` of them
    are found in the cleaned text."""
    spans = [span for span in block_spans(page, item_blocks(page.lxml_tree)) if span is not None]
    if len(spans) < MIN_ITEMS:
        return None
    parts: list[str] = []
    pieces: list[Piece] = []
    at = 0
    for start, end in spans:
        pieces.append(Piece(at, start, end - start))
        parts.append(page.cleaned_text.text[start:end])
        at += end - start + len(_SEPARATOR)
    return TextView(_SEPARATOR.join(parts), tuple(pieces))


def block_spans(page: ParsedPage, blocks: Sequence[HtmlElement]) -> tuple[tuple[int, int] | None, ...]:
    """Each block's span of the cleaned text, from its first run's start to its last run's end, by block; None for a
    block whose path no run carries (it renders no text, or the two trees differ there)."""
    return _spans(page.cleaned_text, {_path(block): index for index, block in enumerate(blocks)}, len(blocks))


def _spans(cleaned: CleanedText, paths: dict[str, int], count: int) -> tuple[tuple[int, int] | None, ...]:
    found: dict[int, tuple[int, int]] = {}
    for run in cleaned.offsets:
        item = _owner(run.node_path, paths)
        if item is None:
            continue
        start, end = found.get(item, (run.start, run.end))
        found[item] = (min(start, run.start), max(end, run.end))
    return tuple(found.get(item) for item in range(count))


def _owner(node_path: str, paths: dict[str, int]) -> int | None:
    """The item whose path is `node_path` or one of its ancestors' paths."""
    path = node_path
    while path:
        if (item := paths.get(path)) is not None:
            return item
        path = path.rpartition("/")[0]
    return None


def _path(element: HtmlElement) -> str:
    """The element's location path in the form `content.text.node_xpath` writes: one positional step per ancestor,
    counting element siblings of the same tag (comments and processing instructions are no elements)."""
    steps: list[str] = []
    current: HtmlElement | None = element
    while current is not None:
        index = 1 + sum(1 for sibling in current.itersiblings(preceding=True) if sibling.tag == current.tag)
        steps.append(xpath_step(str(current.tag), index))
        current = current.getparent()
    return "/" + "/".join(reversed(steps))
