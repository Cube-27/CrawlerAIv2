"""The `POST /v1/batch/scrape` body (SPEC-10 §4.3): what it accepts, and what it refuses."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.services.batch import MAX_URLS, BatchScrapeRequest

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


@pytest.mark.parametrize("count", [0, MAX_URLS + 1])
def test_takes_1_to_1000_urls(count: int) -> None:
    [(location, _)] = _errors({"urls": [URL] * count, "formats": ["markdown"]})

    assert location == ("urls",)


def test_names_the_url_that_is_not_absolute_http() -> None:
    [(location, message)] = _errors({"urls": [URL, "/kettles/red"], "formats": ["markdown"]})

    assert (location, message) == (("urls",), "Value error, urls[1] is not an absolute http or https URL")


def test_refuses_a_webhook_url_that_is_not_absolute_http() -> None:
    [(location, _)] = _errors({"urls": [URL], "formats": ["markdown"], "webhook_url": "hooks/done"})

    assert location == ("webhook_url",)


def test_asks_records_alone() -> None:
    body = {"urls": [URL], "formats": ["records", "markdown"], "schema": SCHEMA, "page_kind": "detail"}

    [(_, message)] = _errors(body)

    assert message == "Value error, records are asked alone: a batch's results are records or page outputs"


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


def test_has_no_browser_actions() -> None:
    # Owner #52: browser actions are for a single-URL listing scrape only.
    body = {"urls": [URL], "formats": ["markdown"], "page_kind": "listing", "browser_actions": {}}

    assert _errors(body) == [(("browser_actions",), "Extra inputs are not permitted")]
