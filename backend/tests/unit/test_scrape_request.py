"""The `POST /v1/scrape` body (SPEC-07 §4.4): what it accepts, its defaults, and what it refuses."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.content.chunks import ChunkOptions
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
        "fetch": {
            "method_hint": "auto",
            "screenshot": "viewport",
            "respect_robots": True,
            "robots_override_reason": None,
            "proxy_pool": None,
            "max_rows": None,
            "headers": {},
            "cookies": {},
            "wait_for": None,
            "actions": [],
            "cache": "default",
        },
        "locale": None,
        "timeout_s": 60.0,
        "budget": None,
        "browser_actions": None,
        "fit": None,
        "chunking": None,
    }


@pytest.mark.parametrize("url", ["/kettles/blue", "ftp://shop.example.test/a"])
def test_refuses_a_url_that_is_not_absolute_http(url: str) -> None:
    assert _errors({"url": url, "formats": ["markdown"]}) == [("url",)]


@pytest.mark.parametrize("timeout_s", [0, 120.5])
def test_refuses_a_timeout_outside_0_to_120_seconds(timeout_s: float) -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "timeout_s": timeout_s}) == [("timeout_s",)]


@pytest.mark.parametrize("max_rows", [0, -5])
def test_refuses_a_row_target_that_is_not_positive(max_rows: int) -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "fetch": {"max_rows": max_rows}}) == [("fetch", "max_rows")]


def test_takes_a_row_target_for_the_adapters_lists() -> None:
    request = ScrapeRequest.model_validate({"url": URL, "formats": ["markdown"], "fetch": {"max_rows": 40}})

    assert request.fetch.max_rows == 40


def test_refuses_no_format_and_unknown_formats() -> None:
    assert _errors({"url": URL, "formats": []}) == [("formats",)]
    assert _errors({"url": URL, "formats": ["docx"]}) == [("formats", "0")]


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


def test_takes_listing_records() -> None:
    body = {"url": URL, "formats": ["records"], "schema": {"id": SCHEMA_ID}, "page_kind": "listing"}

    assert ScrapeRequest.model_validate(body).page_kind == "listing"


def test_refuses_an_inline_schema_of_another_page_kind() -> None:
    inline = {**INLINE, "page_kind": "listing"}
    body = {"url": URL, "formats": ["records"], "schema": {"inline": inline}, "page_kind": "detail"}

    assert _messages(body) == ["Value error, the inline schema is for listing pages, not detail"]


def test_a_robots_override_needs_its_reason() -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "fetch": {"respect_robots": False}}) == [("fetch",)]


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


@pytest.mark.parametrize("actions", [{"records": 0}, {"hint": "type_text"}, {"max_records": 5}])
def test_refuses_browser_actions_out_of_their_shape(actions: dict[str, Any]) -> None:
    assert _errors({**LISTING, "browser_actions": actions})[0][0] == "browser_actions"


def test_takes_a_hint_and_a_row_target() -> None:
    request = ScrapeRequest.model_validate({**LISTING, "browser_actions": {"records": 30, "hint": "scroll"}})

    assert request.browser_actions is not None
    assert (request.browser_actions.records, request.browser_actions.hint) == (30, "scroll")


def test_a_screenshot_or_pdf_cannot_be_asked_over_http() -> None:
    body = {"url": URL, "formats": ["screenshot"], "fetch": {"method_hint": "http"}}

    assert _messages(body) == ["Value error, screenshot and pdf are made in the browser, so method_hint cannot be http"]
    assert _messages({**body, "formats": ["pdf"]}) == _messages(body)
    assert ScrapeRequest.model_validate({**body, "fetch": {"method_hint": "browser"}}).fetch.method_hint == "browser"


def test_fit_and_chunking_need_their_formats() -> None:
    assert _messages({"url": URL, "formats": ["markdown"], "fit": {"query": "x"}}) == [
        "Value error, fit is the option of the markdown_fit format"
    ]
    assert _messages({"url": URL, "formats": ["markdown"], "chunking": {}}) == [
        "Value error, chunking is the option of the chunks format"
    ]
    both = {"url": URL, "formats": ["markdown_fit", "chunks"], "fit": {"query": "x"}, "chunking": {"size": 9}}
    assert ScrapeRequest.model_validate(both).chunking == ChunkOptions(size=9)


def test_chunking_overlap_must_be_smaller_than_size() -> None:
    body = {"url": URL, "formats": ["chunks"], "chunking": {"size": 4, "overlap": 4}}

    assert _messages(body) == ["Value error, overlap must be smaller than size"]


def test_browser_actions_cannot_ask_a_screenshot() -> None:
    body = {
        "url": URL,
        "formats": ["screenshot"],
        "page_kind": "listing",
        "browser_actions": {"records": 5},
    }

    assert _messages(body) == [
        "Value error, screenshot and pdf are of the page as first rendered, so browser_actions cannot ask them"
    ]
