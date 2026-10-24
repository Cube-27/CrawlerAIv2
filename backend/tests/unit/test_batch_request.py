"""The `POST /v1/batch/scrape` body: what it accepts, and what it refuses."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from snowcrawl.services.batch import BatchScrapeRequest

URL = "https://shop.example.test/kettles/blue"
SCHEMA = {"id": str(uuid.UUID(int=1))}


def _errors(body: dict[str, Any]) -> list[tuple[tuple[str, ...], str]]:
    with pytest.raises(ValidationError) as invalid:
        BatchScrapeRequest.model_validate(body)
    return [(tuple(str(part) for part in error["loc"]), error["msg"]) for error in invalid.value.errors()]


def test_a_stored_request_reads_back_as_itself() -> None:
    request = BatchScrapeRequest.model_validate(
        {"urls": [URL], "formats": ["records"], "schema": SCHEMA, "page_kind": "detail", "webhook_url": URL}
    )

    assert BatchScrapeRequest.model_validate(request.model_dump(mode="json", by_alias=True)) == request


@pytest.mark.parametrize("min_confidence", [-0.1, 1.1])
def test_refuses_a_minimum_confidence_outside_0_to_1(min_confidence: float) -> None:
    [(location, _)] = _errors({"urls": [URL], "formats": ["markdown"], "min_confidence": min_confidence})

    assert location == ("min_confidence",)


def test_records_need_a_schema_and_a_page_kind() -> None:
    assert [message for _, message in _errors({"urls": [URL], "formats": ["records"], "page_kind": "detail"})] == [
        "Value error, the records format needs a schema"
    ]
    assert [message for _, message in _errors({"urls": [URL], "formats": ["records"], "schema": SCHEMA})] == [
        "Value error, the records format needs a page_kind"
    ]


def test_refuses_a_prompt() -> None:
    body = {"urls": [URL], "formats": ["records"], "schema": {"prompt": "kettles"}, "page_kind": "detail"}

    assert {location[:2] for location, _ in _errors(body)} == {
        ("schema", "SchemaById"),
        ("schema", "SchemaInline"),
        ("schema", "SchemaFields"),
    }


def test_fit_and_chunking_need_their_formats_and_are_stored_with_the_request() -> None:
    assert _errors({"urls": [URL], "formats": ["markdown"], "fit": {"query": "x"}}) == [
        ((), "Value error, fit is the option of the markdown_fit format")
    ]
    request = BatchScrapeRequest.model_validate(
        {"urls": [URL], "formats": ["markdown_fit", "chunks"], "fit": {"query": "x"}, "chunking": {"size": 50}}
    )

    stored = request.model_dump(mode="json", by_alias=True)
    assert (stored["fit"], stored["chunking"]["size"]) == ({"query": "x", "max_blocks": None}, 50)
    assert BatchScrapeRequest.model_validate(stored) == request
