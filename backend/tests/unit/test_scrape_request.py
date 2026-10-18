"""The `POST /v1/scrape` body (rest-api spec): what it accepts, its defaults, and what it refuses."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.services.scrape import ScrapeRequest

URL = "https://shop.example.test/kettles/blue"


def _errors(body: dict[str, Any]) -> list[tuple[str, ...]]:
    with pytest.raises(ValidationError) as invalid:
        ScrapeRequest.model_validate(body)
    return [tuple(str(part) for part in error["loc"]) for error in invalid.value.errors()]


@pytest.mark.parametrize("url", ["/kettles/blue", "ftp://shop.example.test/a"])
def test_refuses_a_url_that_is_not_absolute_http(url: str) -> None:
    assert _errors({"url": url, "formats": ["markdown"]}) == [("url",)]


def test_refuses_no_format_and_unknown_formats() -> None:
    assert _errors({"url": URL, "formats": []}) == [("formats",)]
    assert _errors({"url": URL, "formats": ["docx"]}) == [("formats", "0")]


INLINE = {
    "name": "synthetic_kettle",
    "page_kind": "detail",
    "fields": {"title": {"type": "text", "required": True, "description": "The product's name"}},
}


def _messages(body: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as invalid:
        ScrapeRequest.model_validate(body)
    return [error["msg"] for error in invalid.value.errors()]


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


def test_refuses_an_inline_schema_of_another_page_kind() -> None:
    inline = {**INLINE, "page_kind": "listing"}
    body = {"url": URL, "formats": ["records"], "schema": {"inline": inline}, "page_kind": "detail"}

    assert _messages(body) == ["Value error, the inline schema is for listing pages, not detail"]


def test_refuses_unknown_members() -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "wait_for": 3}) == [("wait_for",)]


# Owner #52: browser actions only for a listing fetched now, in the browser.
LISTING = {"url": URL, "formats": ["markdown"], "page_kind": "listing"}


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"page_kind": "detail"}, "browser_actions needs page_kind listing"),
        ({"page_kind": None}, "browser_actions needs page_kind listing"),
        ({"max_age": 60}, "max_age must be 0"),
        ({"fetch": {"method_hint": "http"}}, "method_hint cannot be http"),
        ({"fetch": {"cache": "only"}}, "fetch.cache cannot be only"),
    ],
)
def test_refuses_browser_actions_outside_a_fresh_listing_fetch(fields: dict[str, Any], message: str) -> None:
    body = {**LISTING, "browser_actions": {}, **fields}

    assert any(message in text for text in _messages(body))


def test_a_screenshot_or_pdf_cannot_be_asked_over_http() -> None:
    body = {"url": URL, "formats": ["screenshot"], "fetch": {"method_hint": "http"}}

    assert _messages(body) == ["Value error, screenshot and pdf are made in the browser, so method_hint cannot be http"]
    assert _messages({**body, "formats": ["pdf"]}) == _messages(body)
    assert ScrapeRequest.model_validate({**body, "fetch": {"method_hint": "browser"}}).fetch.method_hint == "browser"
