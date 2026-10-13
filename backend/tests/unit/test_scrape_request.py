"""The `POST /v1/scrape` body (SPEC-07 §4.4): what it accepts, its defaults, and what it refuses."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.services.scrape import SchemaPrompt, ScrapeRequest

URL = "https://shop.example.test/kettles/blue"


def _errors(body: dict[str, Any]) -> list[tuple[str, ...]]:
    with pytest.raises(ValidationError) as invalid:
        ScrapeRequest.model_validate(body)
    return [tuple(str(part) for part in error["loc"]) for error in invalid.value.errors()]


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


def test_reads_the_schema_member_by_its_name() -> None:
    request = ScrapeRequest.model_validate({"url": URL, "formats": ["markdown"], "schema": {"prompt": "kettles"}})

    assert request.schema_ == SchemaPrompt(prompt="kettles")


@pytest.mark.parametrize("url", ["/kettles/blue", "ftp://shop.example.test/a", "kettles", ""])
def test_refuses_a_url_that_is_not_absolute_http(url: str) -> None:
    assert _errors({"url": url, "formats": ["markdown"]}) == [("url",)]


@pytest.mark.parametrize("timeout_s", [0, -1, 120.5])
def test_refuses_a_timeout_outside_0_to_120_seconds(timeout_s: float) -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "timeout_s": timeout_s}) == [("timeout_s",)]


def test_refuses_no_format_and_unknown_formats() -> None:
    assert _errors({"url": URL, "formats": []}) == [("formats",)]
    assert _errors({"url": URL, "formats": ["pdf"]}) == [("formats", "0")]


def test_refuses_records_until_it_is_available() -> None:
    assert _errors({"url": URL, "formats": ["markdown", "records"]}) == [("formats",)]


def test_a_robots_override_needs_its_reason() -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "fetch": {"respect_robots": False}}) == [("fetch",)]


def test_refuses_unknown_members() -> None:
    assert _errors({"url": URL, "formats": ["markdown"], "wait_for": 3}) == [("wait_for",)]
