"""How the MCP tools answer: markdown in pages with a cursor, and records with a
human-readable summary in which a field without a published value reads "unknown", never as a value.

Every answer carries its structured content and, for clients that read only text, the same content as JSON (MCP
2025-06-18, "Structured content"). Page text in either is data from the open web.
"""

import base64
import json
import uuid
from collections.abc import Sequence
from typing import Any, Final, NamedTuple

from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent

from snowcrawl.db.models import CaptureId
from snowcrawl.services.records import ExtractedRecord

MARKDOWN_PAGE_CHARS: Final = 20_000
UNKNOWN: Final = "unknown"
# A screenshot larger than this is named by its URL only: an image block is carried as base64 text in the answer.
MAX_IMAGE_BYTES: Final = 1_500_000


class InvalidCursor(ValueError):
    pass


class MarkdownCursor(NamedTuple):
    """Where the next page of a capture's markdown starts."""

    capture_id: CaptureId
    offset: int

    def encode(self) -> str:
        return f"{self.capture_id}:{self.offset}"

    @classmethod
    def decode(cls, text: str) -> "MarkdownCursor":
        capture, _, offset = text.partition(":")
        try:
            cursor = cls(CaptureId(uuid.UUID(capture)), int(offset))
        except ValueError as e:
            raise InvalidCursor(f"not a markdown cursor: {text!r}") from e
        if cursor.offset <= 0:
            raise InvalidCursor(f"not a markdown cursor: {text!r}")
        return cursor


def markdown_page(capture_id: CaptureId, markdown: str, offset: int) -> tuple[str, str | None]:
    """The page of `markdown` from `offset`, and the cursor of the page after it; None on the last page."""
    end = offset + MARKDOWN_PAGE_CHARS
    cursor = MarkdownCursor(capture_id, end).encode() if end < len(markdown) else None
    return markdown[offset:end], cursor


def _confidence(value: float | None) -> str:
    return "none" if value is None else f"{value:.2f}"


def records_summary(records: Sequence[ExtractedRecord]) -> str:
    """One block per record: each field's published value, or "unknown" when it has none, with its status and
    confidence, so that an abstention is never read as a value."""
    blocks = []
    for n, record in enumerate(records, start=1):
        completeness = "complete" if record.complete else "incomplete"
        lines = [f"Record {n} ({completeness}; confidence {_confidence(record.confidence)}):"]
        for name, field in record.fields.items():
            shown = json.dumps(field.value, ensure_ascii=False) if field.status == "published" else UNKNOWN
            lines.append(f"- {name}: {shown} [{field.status}, confidence {_confidence(field.confidence)}]")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "No records."


def tool_result(
    structured: dict[str, Any],
    records: Sequence[ExtractedRecord] | None = None,
    image: bytes | None = None,
) -> CallToolResult:
    """`structured` as the answer's structured content and as JSON text, with the records' summary after it when the
    answer holds records, and a PNG `image` as an image block (MCP 2025-06-18, "Image content")."""
    content: list[ContentBlock] = [TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))]
    if records is not None:
        content.append(TextContent(type="text", text=records_summary(records)))
    if image is not None:
        content.append(ImageContent(type="image", data=base64.b64encode(image).decode("ascii"), mimeType="image/png"))
    return CallToolResult(content=content, structuredContent=structured)
