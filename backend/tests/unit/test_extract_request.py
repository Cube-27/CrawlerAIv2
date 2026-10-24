"""The `POST /v1/extract` body: what it accepts, what it refuses, and what the SSRF guard checks."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from snowcrawl.services.batch import MAX_URLS
from snowcrawl.services.extract import ExtractRequest

SCHEMA = {"id": str(uuid.UUID(int=1))}
TITLE = {"type": "text", "required": True, "description": "The name"}
BODY: dict[str, Any] = {"urls": ["https://shop.example.test/p/1"], "schema": SCHEMA, "page_kind": "detail"}


def _errors(body: dict[str, Any]) -> list[tuple[tuple[str, ...], str]]:
    with pytest.raises(ValidationError) as invalid:
        ExtractRequest.model_validate(body)
    return [(tuple(str(part) for part in error["loc"]), error["msg"]) for error in invalid.value.errors()]


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("urls", []),
        ("urls", ["https://shop.example.test/p/1"] * (MAX_URLS + 1)),
        ("webhook_url", "hooks/done"),
        ("limit", 0),
        ("limit", MAX_URLS + 1),
        ("page_kind", None),
        ("schema", None),
    ],
)
def test_refuses_a_member_out_of_range(member: str, value: object) -> None:
    errors = _errors(BODY | {member: value})

    assert {location[0] for location, _ in errors} == {member}


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("/p/1", "Value error, urls[1] is not an absolute http or https URL"),
        ("https://*.example.test/p/*", "Value error, urls[1] is not a glob on one http or https host"),
    ],
)
def test_refuses_a_url_or_glob_without_one_http_host(url: str, message: str) -> None:
    assert _errors(BODY | {"urls": ["https://shop.example.test/p/1", url]}) == [(("urls",), message)]


@pytest.mark.parametrize(
    ("members", "message"),
    [
        (
            {"schema": {"inline": {"name": "s", "page_kind": "listing", "fields": {"title": TITLE}}}},
            "Value error, the inline schema is for listing pages, not detail",
        ),
    ],
)
def test_the_schema_is_for_detail_pages_of_the_page_kind(members: dict[str, Any], message: str) -> None:
    assert _errors(BODY | members) == [((), message)]


def test_the_guard_checks_each_url_and_each_globs_origin() -> None:
    request = ExtractRequest.model_validate(
        BODY | {"urls": ["https://shop.example.test/p/1", "https://Other.example.test:443/c/*/p/*"]}
    )

    assert request.targets() == [
        ("urls[0]", "https://shop.example.test/p/1"),
        ("urls[1]", "https://other.example.test/"),
    ]
