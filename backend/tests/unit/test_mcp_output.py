"""How the MCP tools answer (SPEC-10 §4.7, ARCHITECTURE §13.3): a field without a published value reads "unknown" in
the records' summary, never as a value, and every field shows its status and confidence."""

import json

import pytest
from pydantic import JsonValue

from crawlerai.mcp_server.output import InvalidCursor, MarkdownCursor, records_summary, tool_result
from crawlerai.resolve.types import FieldStatus
from crawlerai.services.records import ExtractedRecord, RecordField


def _field(status: FieldStatus, value: JsonValue, confidence: float | None) -> RecordField:
    return RecordField(
        value=value,
        status=status,
        reason=None,
        evidence=None,
        confidence=confidence,
        calibrated=confidence is not None,
        source_kind=None,
        locator=None,
        derived_by=None,
    )


RECORD = ExtractedRecord(
    mode="adhoc",
    complete=False,
    confidence=None,
    fields={
        "title": _field("published", "Blue kettle", 0.97),
        "price": _field("abstained", None, None),
        "sku": _field("conflict", None, 0.4),
    },
)


def test_a_field_without_a_published_value_reads_unknown_with_its_status_and_confidence() -> None:
    assert records_summary([RECORD]) == (
        "Record 1 (incomplete; confidence none):\n"
        '- title: "Blue kettle" [published, confidence 0.97]\n'
        "- price: unknown [abstained, confidence none]\n"
        "- sku: unknown [conflict, confidence 0.40]"
    )


def test_an_answer_carries_its_structure_as_json_and_the_summary_only_with_records() -> None:
    structured = {"job_id": "j", "markdown": "# Title"}

    plain = tool_result(structured)
    with_records = tool_result(structured, [RECORD])

    assert plain.structuredContent == structured
    assert [json.loads(block.text) for block in plain.content if block.type == "text"] == [structured]
    assert len(with_records.content) == 2
    assert with_records.content[1].type == "text"
    assert with_records.content[1].text == records_summary([RECORD])


@pytest.mark.parametrize(
    "text", ["", "not-a-uuid:10", "01a13754-8791-738c-86ed-bc3b329d7fb1:x", "01a13754-8791-738c-86ed-bc3b329d7fb1:0"]
)
def test_a_malformed_cursor_is_refused(text: str) -> None:
    with pytest.raises(InvalidCursor):
        MarkdownCursor.decode(text)
