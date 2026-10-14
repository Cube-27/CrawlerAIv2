"""The MCP `scrape` tool's markdown pages (SPEC-10 §4.7): following the cursors from the first page reads the markdown
whole, in order, in pages of at most 20,000 characters, and the last page has no cursor."""

import uuid

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.db.models import CaptureId
from crawlerai.mcp_server.output import MARKDOWN_PAGE_CHARS, MarkdownCursor, markdown_page

CAPTURE = CaptureId(uuid.UUID("01a13754-8791-738c-86ed-bc3b329d7fb1"))


def _read_all(markdown: str) -> list[str]:
    pages = []
    offset: int | None = 0
    while offset is not None:
        text, cursor = markdown_page(CAPTURE, markdown, offset)
        pages.append(text)
        offset = None if cursor is None else MarkdownCursor.decode(cursor).offset
    return pages


@given(st.text(min_size=1, max_size=20), st.integers(min_value=0, max_value=3 * MARKDOWN_PAGE_CHARS + 1))
def test_the_pages_read_the_markdown_whole_and_in_order(unit: str, length: int) -> None:
    markdown = (unit * (length // len(unit) + 1))[:length]

    pages = _read_all(markdown)

    assert "".join(pages) == markdown
    assert all(len(page) <= MARKDOWN_PAGE_CHARS for page in pages)
    assert len(pages) == max(1, -(-length // MARKDOWN_PAGE_CHARS))  # ceil, and one empty page for no markdown


def test_a_markdown_of_exactly_one_page_has_no_cursor() -> None:
    assert markdown_page(CAPTURE, "x" * MARKDOWN_PAGE_CHARS, 0) == ("x" * MARKDOWN_PAGE_CHARS, None)


def test_the_cursor_names_the_capture_and_the_next_offset() -> None:
    _, cursor = markdown_page(CAPTURE, "x" * (MARKDOWN_PAGE_CHARS + 1), 0)

    assert cursor is not None
    assert MarkdownCursor.decode(cursor) == MarkdownCursor(CAPTURE, MARKDOWN_PAGE_CHARS)
