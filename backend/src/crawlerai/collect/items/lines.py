"""A listing's blocks as role C reads them (llm spec, "Role C on listings"): each block's span of the cleaned text,
verbatim, under its locator (its position in the bound group and its item URL), with the row its values fill and the
row fields that row does not publish.

The span is the one the block's node path carries (`content.segment.text_path`, `ParsedPage.text_spans`), so a value
role C grounds in it is a span of the cleaned text (INV-12). A block whose path no run carries is not read: it renders
no text, or libxml2 and HTML tree construction built different trees there for malformed markup.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from crawlerai.collect.items.bind import RowBlock
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import text_path

# The cleaned text's line break (`content.text`: one between two line boxes).
_BREAK = "\n"


@dataclass(frozen=True, slots=True)
class BlockText:
    """One block as role C reads it: its position in the bound group and its item URL (its locator), the row entity
    its values fill, its text (the cleaned text from `start`, verbatim) and the row fields its row does not publish."""

    index: int
    url: str
    row: str
    start: int
    text: str
    fields: tuple[str, ...]

    @property
    def line(self) -> str:
        """The text on one line, each line break shown as a space: one character for one, so an offset in the line is
        one in the text."""
        return self.text.replace(_BREAK, " ")


def block_text(page: ParsedPage, row_block: RowBlock, fields: Sequence[str]) -> BlockText | None:
    """The block's text for role C to fill `fields` of its row; None when the cleaned text holds none of it."""
    span = page.text_spans.get(text_path(row_block.block.element))
    if span is None or span[0] == span[1]:
        return None
    start, end = span
    text = page.cleaned_text.text[start:end]
    return BlockText(row_block.index, row_block.block.link, row_block.row, start, text, tuple(fields))
