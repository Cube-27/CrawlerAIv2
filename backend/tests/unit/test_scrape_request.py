"""The `POST /v1/scrape` body (SPEC-07 §4.4): what it accepts, its defaults, and what it refuses."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.services.scrape import ScrapeRequest
from crawlerai.services.scrape_steps import SchemaFields, SchemaPrompt

URL = "https://shop.example.test/kettles/blue"


def _errors(body: dict[str, Any]) -> list[tuple[str, ...]]:
    with pytest.raises(ValidationError) as invalid:
        ScrapeRequest.model_validate(body)
    return [tuple(str(part) for part in error["loc"]) for error in invalid.value.errors()]


# SPEC-07 §4.4: the documented request defaults (a promise to API callers).
def test_takes_the_documented_defaults() -> None:
    request = ScrapeRequest.model_validate({"url": URL, "formats": ["markdown"]})

    assert request.model_dump(mode="json", by_alias=True) == {
        "url": URL,
        "formats": ["markdown"],
        "schema": None,
        "page_kind": None,
        "max_age": 0,
        "fetch": {"method_hint": "auto", "respect_robots": True, "robots_override_reason": None, "proxy_pool": None},
        "locale": None,
        "timeout_s": 60.0,
        "budget": {"llm_calls": 10},
    }


@pytest.mark.parametrize("url", ["/kettles/blue", "ftp://shop.example.test/a"])
def test_refuses_a_url_that_is_not_absolute_http(url: str) -> None:
    assert _errors({"url": url, "formats": ["markdown"]}) == [("url",)]


@pytest.mark.parametrize("timeout_s", [0, 120.5])
def test_refuses_a_timeout_outside_0_to_120_seconds(timeout_s: float) -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "timeout_s": timeout_s}) == [("timeout_s",)]


def test_refuses_no_format_and_unknown_formats() -> None:
    assert _errors({"url": URL, "formats": []}) == [("formats",)]
    assert _errors({"url": URL, "formats": ["pdf"]}) == [("formats", "0")]


INLINE = {
    "name": "synthetic_kettle",
    "page_kind": "detail",
    "fields": {"title": {"type": "text", "required": True, "description": "The product's name"}},
}
SCHEMA_ID = "0192f5a4-0000-7000-8000-000000000001"


def _messages(body: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as invalid:
        ScrapeRequest.model_validate(body)
    return [error["msg"] for error in invalid.value.errors()]


def test_takes_records_with_a_schema_and_a_detail_page_kind() -> None:
    # The body's `schema` member is read by its name.
    request = ScrapeRequest.model_validate(
        {"url": URL, "formats": ["markdown", "records"], "schema": {"prompt": "kettle names"}, "page_kind": "detail"}
    )

    assert (request.schema_, request.page_kind) == (SchemaPrompt(prompt="kettle names"), "detail")


def test_takes_field_names_as_the_schema() -> None:
    request = ScrapeRequest.model_validate(
        {"url": URL, "formats": ["records"], "schema": {"fields": ["title", "price"]}, "page_kind": "detail"}
    )

    assert request.schema_ == SchemaFields(fields=["title", "price"])


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (["title", "title"], "Value error, a field name is given twice"),
        (["Unit price"], "String should match pattern '^[a-z][a-z0-9_]{0,63}$'"),
        ([], "List should have at least 1 item after validation, not 0"),
        ([f"f{n}" for n in range(51)], "List should have at most 50 items after validation, not 51"),
    ],
)
def test_refuses_field_names_that_are_not_distinct_schema_names(fields: list[str], message: str) -> None:
    body = {"url": URL, "formats": ["records"], "schema": {"fields": fields}, "page_kind": "detail"}

    assert message in _messages(body)


def test_records_need_a_schema() -> None:
    assert _messages({"url": URL, "formats": ["records"], "page_kind": "detail"}) == [
        "Value error, the records format needs a schema"
    ]


def test_records_need_a_page_kind() -> None:
    assert _messages({"url": URL, "formats": ["records"], "schema": {"id": SCHEMA_ID}}) == [
        "Value error, the records format needs a page_kind"
    ]


def test_refuses_listing_records_until_they_are_available() -> None:
    body = {"url": URL, "formats": ["records"], "schema": {"id": SCHEMA_ID}, "page_kind": "listing"}

    assert _messages(body) == ["Value error, records of listing pages are not available yet"]


def test_refuses_an_inline_schema_of_another_page_kind() -> None:
    inline = {**INLINE, "page_kind": "listing"}
    body = {"url": URL, "formats": ["records"], "schema": {"inline": inline}, "page_kind": "detail"}

    assert _messages(body) == ["Value error, the inline schema is for listing pages, not detail"]


def test_a_robots_override_needs_its_reason() -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "fetch": {"respect_robots": False}}) == [("fetch",)]


def test_refuses_unknown_members() -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "wait_for": 3}) == [("wait_for",)]
