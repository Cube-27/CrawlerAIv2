"""The `ApiRecipe` model (SPEC-09 §4.2): a recipe document survives a JSON round trip, and documents that leave a
placeholder unbound, move the host, carry credentials or use paths the engine cannot read are refused."""

import uuid
from typing import Any

import pytest

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
