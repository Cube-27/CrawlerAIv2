"""The `POST /v1/crawl` body (SPEC-10 §4.5): what it accepts, and what it refuses."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.services.crawl import CrawlRequest
from crawlerai.services.map import MAX_LIMIT

URL = "https://shop.example.test/"
SCHEMA = {"id": str(uuid.UUID(int=1))}
DETAIL = {"pattern": "https://shop.example.test/p/*", "page_kind": "detail"}


def _errors(body: dict[str, Any]) -> list[tuple[tuple[str, ...], str]]:
    with pytest.raises(ValidationError) as invalid:
        CrawlRequest.model_validate(body)
    return [(tuple(str(part) for part in error["loc"]), error["msg"]) for error in invalid.value.errors()]


def test_a_stored_request_reads_back_as_itself() -> None:
    body = {"url": URL, "formats": ["records"], "schema": SCHEMA, "page_kind_rules": [DETAIL], "exclude": ["*?*"]}
    request = CrawlRequest.model_validate(body)

    assert CrawlRequest.model_validate(request.model_dump(mode="json", by_alias=True)) == request
    assert (request.max_depth, request.limit) == (3, 500)


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
        (
            {"page_kind_rules": [{"pattern": "*", "page_kind": "listing"}]},
            "records of listing pages are not available yet",
        ),
        ({"schema": None}, "the records format needs a schema"),
    ],
)
def test_records_need_a_schema_and_rules_of_its_page_kind(members: dict[str, Any], message: str) -> None:
    body = {"url": URL, "formats": ["records"], "schema": SCHEMA, "page_kind_rules": [DETAIL], **members}

    [(_, error)] = _errors(body)

    assert error == f"Value error, {message}"


def test_formats_take_rules_of_any_page_kind() -> None:
    rules = [DETAIL, {"pattern": "https://shop.example.test/c/*", "page_kind": "listing"}]

    request = CrawlRequest.model_validate({"url": URL, "formats": ["markdown"], "page_kind_rules": rules})

    assert [rule.page_kind for rule in request.page_kind_rules] == ["detail", "listing"]


def test_the_frontier_is_scoped_to_the_start_urls_host() -> None:
    request = CrawlRequest.model_validate({"url": "HTTPS://Shop.Example.Test/a?b=1&a=2#top", "formats": ["markdown"]})

    frontier = request.frontier()

    assert request.start == "https://shop.example.test/a?a=2&b=1"
    assert (frontier.scope.host, frontier.max_depth, frontier.limit) == ("shop.example.test", 3, 500)
