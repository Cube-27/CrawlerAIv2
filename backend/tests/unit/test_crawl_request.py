"""The `POST /v1/crawl` body: what it accepts, and what it refuses."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from snowcrawl.services.crawl import CrawlRequest
from snowcrawl.services.map import MAX_LIMIT

URL = "https://shop.example.test/"
SCHEMA = {"id": str(uuid.UUID(int=1))}
DETAIL = {"pattern": "https://shop.example.test/p/*", "page_kind": "detail"}


def _errors(body: dict[str, Any]) -> list[tuple[tuple[str, ...], str]]:
    with pytest.raises(ValidationError) as invalid:
        CrawlRequest.model_validate(body)
    return [(tuple(str(part) for part in error["loc"]), error["msg"]) for error in invalid.value.errors()]


@pytest.mark.parametrize(
    ("member", "value"),
    [("url", "/p/1"), ("webhook_url", "hooks/done"), ("limit", 0), ("limit", MAX_LIMIT + 1), ("max_depth", -1)],
)
def test_refuses_a_member_out_of_range(member: str, value: object) -> None:
    [(location, _)] = _errors({"url": URL, "formats": ["markdown"], member: value})

    assert location == (member,)


@pytest.mark.parametrize(
    ("members", "message"),
    [
        (
            {"formats": ["records", "markdown"]},
            "records are asked alone: a crawl's results are records or page outputs",
        ),
        ({"page_kind_rules": []}, "the records format needs page_kind_rules: a page no rule matches is not extracted"),
        (
            {"page_kind_rules": [DETAIL, {"pattern": "*/c/*", "page_kind": "listing"}]},
            "the records format takes rules of one page kind, the schema's",
        ),
        ({"schema": None}, "the records format needs a schema"),
    ],
)
def test_records_need_a_schema_and_rules_of_its_page_kind(members: dict[str, Any], message: str) -> None:
    body = {"url": URL, "formats": ["records"], "schema": SCHEMA, "page_kind_rules": [DETAIL], **members}

    [(_, error)] = _errors(body)

    assert error == f"Value error, {message}"


def test_max_pages_is_the_limit() -> None:
    request = CrawlRequest.model_validate(
        {"url": "https://shop.example.test/", "formats": ["markdown"], "max_pages": 7}
    )

    assert request.limit == 7
    with pytest.raises(ValueError, match="alias"):
        CrawlRequest.model_validate(
            {"url": "https://shop.example.test/", "formats": ["markdown"], "max_pages": 7, "limit": 7}
        )


def test_a_pdf_cannot_be_asked_over_http_and_chunking_needs_the_chunks_format() -> None:
    http = {"url": URL, "formats": ["pdf"], "fetch": {"method_hint": "http"}}
    chunking = {"url": URL, "formats": ["markdown"], "chunking": {}}

    assert [message for _, message in _errors(http)] == [
        "Value error, screenshot and pdf are made in the browser, so method_hint cannot be http"
    ]
    assert [message for _, message in _errors(chunking)] == ["Value error, chunking is the option of the chunks format"]
