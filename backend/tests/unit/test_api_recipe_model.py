"""The `ApiRecipe` model (SPEC-09 §4.2): a recipe document survives a JSON round trip, and documents that leave a
placeholder unbound, move the host, carry credentials or use paths the engine cannot read are refused."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.config_ir.api_recipe.model import ApiRecipe, Binder, RequestSpec, map_paths, parse_binder

_CAPTURE = str(uuid.UUID(int=1))


def _recipe(**changes: Any) -> dict[str, Any]:
    return {
        "method": "GET",
        "url": "https://api.example.test/v1/products/{slug}?lang={lang}",
        "params_from_url": {"slug": "path:1", "lang": "query:hl"},
        "headers": {"Accept": "application/json", "Referer": "{page_url}"},
        "map": {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
        "pagination": {"kind": "param", "name": "page", "start": 1, "step": 1, "rows": "$['data']['items'][*]"},
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
    "text",
    ["path:01", "path:-1", "query:", "regex:/p/\\d+", "regex:(a)(b)", "regex:(?<x>a)", "jsonld:$.a", "host:0", "x"],
)
def test_malformed_binders_are_refused(text: str) -> None:
    with pytest.raises(ValueError, match=r"binder|index|group|query|not"):
        parse_binder(text)


def test_a_money_map_entry_joins_its_paths() -> None:
    assert map_paths("$['p']+$['c']") == ["$['p']", "$['c']"]
    assert map_paths("$['a+b']") == ["$['a+b']"]


_REFUSED: dict[str, dict[str, Any]] = {
    "placeholder without binder": {"params_from_url": {"slug": "path:1"}},
    "binder without placeholder": {"params_from_url": {"slug": "path:1", "lang": "query:hl", "x": "path:0"}},
    "page_url as parameter": {"url": "https://api.example.test/{page_url}", "params_from_url": {"page_url": "path:0"}},
    "placeholder in the host": {"url": "https://{slug}.example.test/x?lang={lang}"},
    "brace outside a placeholder": {"url": "https://api.example.test/{slug}/{?lang={lang}"},
    "relative URL": {"url": "/v1/{slug}?lang={lang}"},
    "non-http scheme": {"url": "ftp://api.example.test/{slug}?lang={lang}"},
    "fragment": {"url": "https://api.example.test/{slug}?lang={lang}#x"},
    "body on GET": {"body": {"template": "{}"}},
    "cookie header": {"headers": {"Cookie": "a=b"}},
    "authorization header in any case": {"headers": {"authorization": "x"}},
    "header named twice": {"headers": {"Accept": "a", "accept": "b"}},
    "header placeholder other than page_url": {"headers": {"X-Id": "{slug}"}},
    "line break in a header value": {"headers": {"X-A": "a\r\nX-B: b"}},
    "requires_page_fetch without a page data binder": {"requires_page_fetch": True},
    "page data binder without requires_page_fetch": {"params_from_url": {"slug": "jsonld:$['s']", "lang": "query:hl"}},
    "dot-notation map path": {"map": {"title": "$.data['name']"}},
    "empty map": {"map": {}},
    "map field that is not a name": {"map": {"Title": "$['t']"}},
    "proof without captures": {"proof": {"validated_on": [], "headers_tried": 0, "bound_by": "role_d"}},
    "pagination step zero": {"pagination": {"kind": "param", "name": "p", "start": 0, "step": 0, "rows": "$[*]"}},
}


@pytest.mark.parametrize("changes", _REFUSED.values(), ids=_REFUSED.keys())
def test_malformed_recipes_are_refused(changes: dict[str, Any]) -> None:
    document = _recipe(**changes)

    with pytest.raises(ValidationError):
        ApiRecipe.model_validate(document)


def test_a_request_spec_needs_no_map_or_proof() -> None:
    spec = RequestSpec.model_validate({"method": "GET", "url": "https://api.example.test/items"})

    assert (spec.params_from_url, spec.headers, spec.body, spec.requires_page_fetch) == ({}, {}, None, False)
