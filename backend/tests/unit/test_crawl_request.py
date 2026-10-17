"""The `POST /v1/crawl` body (SPEC-10 §4.5): what it accepts, and what it refuses."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.crawl.rules import MAX_PATTERNS
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


def test_a_budget_is_kept_with_the_request_and_is_none_without_one() -> None:
    body = {"url": URL, "formats": ["markdown"]}

    budgeted = CrawlRequest.model_validate({**body, "budget": {"llm_calls": 3}})

    assert CrawlRequest.model_validate(body).budget is None
    assert budgeted.model_dump(mode="json", by_alias=True)["budget"] == {"llm_calls": 3}


@pytest.mark.parametrize("budget", [{"llm_calls": -1}, {}, {"llm_calls": 1, "pages": 2}])
def test_refuses_a_budget_that_is_not_a_count_of_llm_calls(budget: dict[str, object]) -> None:
    [(location, _)] = _errors({"url": URL, "formats": ["markdown"], "budget": budget})

    assert location[0] == "budget"


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


def test_records_take_listing_rules() -> None:
    rules = [{"pattern": "*", "page_kind": "listing"}]

    request = CrawlRequest.model_validate(
        {"url": URL, "formats": ["records"], "schema": SCHEMA, "page_kind_rules": rules}
    )

    assert [rule.page_kind for rule in request.page_kind_rules] == ["listing"]


def test_formats_take_rules_of_any_page_kind() -> None:
    rules = [DETAIL, {"pattern": "https://shop.example.test/c/*", "page_kind": "listing"}]

    request = CrawlRequest.model_validate({"url": URL, "formats": ["markdown"], "page_kind_rules": rules})

    assert [rule.page_kind for rule in request.page_kind_rules] == ["detail", "listing"]


def test_the_frontier_is_scoped_to_the_start_urls_host() -> None:
    body = {"url": "HTTPS://Shop.Example.Test/a?b=1&a=2#top", "formats": ["markdown"], "max_depth": 2, "limit": 7}
    request = CrawlRequest.model_validate(body)

    frontier = request.frontier()

    assert request.start == "https://shop.example.test/a?a=2&b=1"
    assert (frontier.scope.host, frontier.max_depth, frontier.limit) == ("shop.example.test", 2, 7)


@pytest.mark.parametrize("member", ["include", "exclude"])
def test_takes_at_most_max_patterns_globs_in_a_scope_list(member: str) -> None:
    globs = [f"https://shop.example.test/c{n}/*" for n in range(MAX_PATTERNS + 1)]
    body = {"url": URL, "formats": ["markdown"]}
    accepted = CrawlRequest.model_validate(body | {member: globs[:MAX_PATTERNS]})

    [(location, _)] = _errors(body | {member: globs})

    assert len(getattr(accepted, member)) == MAX_PATTERNS
    assert location == (member,)


def test_max_pages_is_the_limit() -> None:
    request = CrawlRequest.model_validate(
        {"url": "https://shop.example.test/", "formats": ["markdown"], "max_pages": 7}
    )

    assert request.limit == 7
    with pytest.raises(ValueError, match="alias"):
        CrawlRequest.model_validate(
            {"url": "https://shop.example.test/", "formats": ["markdown"], "max_pages": 7, "limit": 7}
        )


def test_a_query_orders_a_best_first_crawl_only() -> None:
    body = {"url": "https://shop.example.test/", "formats": ["markdown"], "query": "kettles"}
    with pytest.raises(ValueError, match="best_first"):
        CrawlRequest.model_validate(body)
    with pytest.raises(ValueError, match="no words"):
        CrawlRequest.model_validate({**body, "strategy": "best_first", "query": "?!"})

    frontier = CrawlRequest.model_validate({**body, "strategy": "best_first", "keywords": ["Tea"]}).frontier()

    assert (frontier.strategy, frontier.wanted) == ("best_first", ("kettles", "tea"))


def test_a_pdf_cannot_be_asked_over_http_and_chunking_needs_the_chunks_format() -> None:
    http = {"url": URL, "formats": ["pdf"], "fetch": {"method_hint": "http"}}
    chunking = {"url": URL, "formats": ["markdown"], "chunking": {}}

    assert [message for _, message in _errors(http)] == [
        "Value error, screenshot and pdf are made in the browser, so method_hint cannot be http"
    ]
    assert [message for _, message in _errors(chunking)] == ["Value error, chunking is the option of the chunks format"]
