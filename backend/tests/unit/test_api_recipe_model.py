"""The `ApiRecipe` model (SPEC-09 §4.2): a recipe document survives a JSON round trip, and documents that leave a
placeholder unbound, move the host, carry credentials or use paths the engine cannot read are refused."""

import uuid
from typing import Any

import pytest
from pydantic import JsonValue, ValidationError

from crawlerai.collect.api import map_paths, read_map
from crawlerai.config_ir.api_recipe.model import ApiRecipe, Binder, parse_binder

_CAPTURE = str(uuid.UUID(int=1))


def _recipe(**changes: Any) -> dict[str, Any]:
    return {
        "method": "GET",
        "url": "https://api.example.test/v1/products/{slug}?lang={lang}",
        "params_from_url": {"slug": "path:1", "lang": "query:hl"},
        "headers": {"Accept": "application/json", "Referer": "{page_url}"},
        "map": {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
        "pagination": {
            "kind": "param",
            "where": "query",
            "name": "page",
            "start": 1,
            "step": 1,
            "rows": "$['data']['items'][*]",
        },
        "proof": {"validated_on": [_CAPTURE], "headers_tried": 2, "bound_by": "deterministic"},
        **changes,
    }


def test_a_recipe_document_round_trips_through_json() -> None:
    recipe = ApiRecipe.model_validate(_recipe())

    assert ApiRecipe.model_validate_json(recipe.model_dump_json()) == recipe
    assert recipe.model_dump(mode="json") == {**_recipe(), "body": None, "requires_page_fetch": False}
    assert recipe.binders == {"slug": Binder("path", "1"), "lang": Binder("query", "hl")}


def test_a_post_recipe_templates_its_body_and_a_page_data_binder_needs_the_page() -> None:
    document = _recipe(
        method="POST",
        url="https://api.example.test/graphql",
        params_from_url={"slug": "regex:^/p/([^/]+)", "sku": "jsonld:$[0]['sku']"},
        body={"template": '{"variables":{"slug":"{slug}","sku":{sku}}}'},
        requires_page_fetch=True,
    )

    recipe = ApiRecipe.model_validate(document)

    assert recipe.reads_page_data is True
    assert recipe.binders["sku"] == Binder("jsonld", "$[0]['sku']")


@pytest.mark.parametrize(
    ("text", "binder"),
    [
        ("path:0", Binder("path", "0")),
        ("query:id", Binder("query", "id")),
        ("regex:/p/(\\d+)", Binder("regex", "/p/(\\d+)")),
        ("js_state:$['props']['id']", Binder("js_state", "$['props']['id']")),
    ],
)
def test_binders_parse_into_their_kind_and_argument(text: str, binder: Binder) -> None:
    assert parse_binder(text) == binder
    assert str(binder) == text


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("path:01", "not a path segment index"),
        ("query:", "a query binder names a query parameter"),
        ("regex:/p/\\d+", "exactly one capturing group"),
        ("regex:(?<x>a)", "not a portable group"),
        ("jsonld:$.a", "not a query of name, wildcard and index segments"),
        ("host:0", "not a binder kind"),
    ],
)
def test_malformed_binders_are_refused(text: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_binder(text)


def test_a_money_map_entry_joins_its_paths() -> None:
    assert map_paths("$['p']+$['c']") == ["$['p']", "$['c']"]
    assert map_paths("$['a+b']") == ["$['a+b']"]


_REFUSED: dict[str, tuple[dict[str, Any], str]] = {
    "placeholder without binder": ({"params_from_url": {"slug": "path:1"}}, "and binders .* differ"),
    "page_url as parameter": (
        {"url": "https://api.example.test/{page_url}", "params_from_url": {"page_url": "path:0"}},
        "page_url is the page URL, not a parameter",
    ),
    "placeholder in the host": ({"url": "https://{slug}.example.test/x?lang={lang}"}, "the scheme and host are fixed"),
    "brace outside a placeholder": (
        {"url": "https://api.example.test/{slug}/{?lang={lang}"},
        "a brace outside a {name} placeholder",
    ),
    "non-http scheme": ({"url": "ftp://api.example.test/{slug}?lang={lang}"}, "an absolute http"),
    "fragment": ({"url": "https://api.example.test/{slug}?lang={lang}#x"}, "without a fragment"),
    "body on GET": ({"body": {"template": "{}"}}, "only a POST carries a body"),
    "authorization header in any case": ({"headers": {"authorization": "x"}}, "a recipe carries no credentials"),
    "a field the client sets": ({"headers": {"Content-Length": "2"}}, "no field the HTTP client sets itself"),
    "header named twice": ({"headers": {"Accept": "a", "accept": "b"}}, "a header named twice"),
    "header placeholder other than page_url": (
        {"headers": {"X-Id": "{slug}"}},
        "{page_url} is the only placeholder a header value takes",
    ),
    "line break in a header value": ({"headers": {"X-A": "a\r\nX-B: b"}}, "a field value holds no line break"),
    "requires_page_fetch without a page data binder": (
        {"requires_page_fetch": True},
        "requires_page_fetch is true exactly when a binder reads",
    ),
    "dot-notation map path": ({"map": {"title": "$.data['name']"}}, "not a query of name, wildcard and index"),
    "empty map": ({"map": {}}, "at least 1 item"),
    "map field that is not a name": ({"map": {"Title": "$['t']"}}, "should match pattern"),
    "proof without captures": (
        {"proof": {"validated_on": [], "headers_tried": 0, "bound_by": "role_d"}},
        "validated_on",
    ),
    "pagination step zero": (
        {"pagination": {"kind": "param", "where": "query", "name": "p", "start": 0, "step": 0, "rows": "$[*]"}},
        "greater than or equal to 1",
    ),
    "pagination of an unknown kind": ({"pagination": {"kind": "scroll", "rows": "$[*]"}}, "does not match any of"),
    "body pagination without a body": (
        {"pagination": {"kind": "param", "where": "body", "name": "$['page']", "start": 0, "step": 1, "rows": "$[*]"}},
        "needs a request body",
    ),
    "body pagination path with a wildcard": (
        {
            "method": "POST",
            "body": {"template": '{"page":1}'},
            "pagination": {"kind": "cursor", "where": "body", "name": "$[*]", "cursor": "$['c']", "rows": "$[*]"},
        },
        "without wildcards",
    ),
    "next URL path outside the engine subset": (
        {"pagination": {"kind": "next_url", "next": "$.next", "rows": "$[*]"}},
        "not a query of name, wildcard and index",
    ),
}


@pytest.mark.parametrize(
    "pagination",
    [
        {"kind": "cursor", "where": "body", "name": "$['variables']['after']", "cursor": "$['end']", "rows": "$[*]"},
        {"kind": "param", "where": "body", "name": "$['variables']['page']", "start": 1, "step": 1, "rows": "$[*]"},
        {"kind": "next_url", "next": "$['links']['next']", "rows": "$['items'][*]"},
        {"kind": "link", "rows": "$['items'][*]"},
    ],
    ids=["cursor-in-body", "param-in-body", "next_url", "link"],
)
def test_every_pagination_kind_round_trips(pagination: dict[str, Any]) -> None:
    body = {"template": '{"query":"q","variables":{"page":1,"after":null}}'}
    recipe = ApiRecipe.model_validate(_recipe(method="POST", body=body, pagination=pagination))

    assert ApiRecipe.model_validate_json(recipe.model_dump_json()) == recipe
    assert recipe.pagination is not None
    assert recipe.pagination.model_dump() == pagination


@pytest.mark.parametrize(("changes", "reason"), _REFUSED.values(), ids=_REFUSED.keys())
def test_malformed_recipes_are_refused(changes: dict[str, Any], reason: str) -> None:
    document = _recipe(**changes)

    with pytest.raises(ValidationError, match=reason):
        ApiRecipe.model_validate(document)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("$['data']['name']", "Desk Lamp"),
        ("$['data']['price']", 19.5),
        ("$['data']['price']+$['data']['currency']", "19.5 EUR"),
        ("$['data']['missing']", None),
        ("$['data']['tags'][*]", None),  # two nodes
        ("$['data']", None),  # not a scalar
        ("$['data']['price']+$['data']['sale']", None),  # one part is null
    ],
)
def test_a_map_entry_reads_one_scalar_or_its_joined_parts(path: str, expected: object) -> None:
    data: JsonValue = {"name": "Desk Lamp", "price": 19.5, "currency": "EUR", "tags": ["a", "b"], "sale": None}
    document: JsonValue = {"data": data}

    assert read_map(path, document) == expected
