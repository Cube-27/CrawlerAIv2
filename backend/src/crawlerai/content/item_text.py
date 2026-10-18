"""The text of a listing's items (llm spec, role C on listings): the spans of the cleaned text that the page's repeated
item blocks render (the segment step's first group, `ParsedPage.item_groups`), joined into one text with a map back to
the cleaned text's offsets. Role C reads it on a listing, so a long run of menus or filters before or between the
items does not crowd them out of what the model reads (and its spans still ground in the cleaned text, INV-12).

The item blocks come from the lxml tree and the cleaned text's runs from the selectolax tree. An item's span is its
node path's (`content.segment.text_path`, `ParsedPage.text_spans`); libxml2 and HTML tree construction can build
different trees for malformed markup, so an item whose path no run carries is left out, and a page with fewer than
`MIN_ITEMS` items found has no item text.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from lxml.html import HtmlElement

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import text_path

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

    def slice(self, start: int, end: int) -> "TextView":
        """The view of pieces `start` to `end` (excluded), its text starting at the first of them."""
        if start == 0 and end >= len(self.pieces):
            return self
        kept = self.pieces[start:end]
        shift = kept[0].at
        pieces = tuple(Piece(piece.at - shift, piece.start, piece.length) for piece in kept)
        return TextView(self.text[shift : kept[-1].at + kept[-1].length], pieces)

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
    blocks = page.item_groups[0] if page.item_groups else ()
    spans = [span for span in block_spans(page, blocks) if span is not None]
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
    spans = page.text_spans
    return tuple(spans.get(text_path(block)) for block in blocks)
