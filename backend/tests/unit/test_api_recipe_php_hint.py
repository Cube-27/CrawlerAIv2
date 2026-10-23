"""The PHP hint of an API recipe (OPEN_QUESTIONS #12): a curl request rendered from
the recipe's data, with its parameters substituted, its headers, and its JSONPath map as comments. Every recipe string
is written as a PHP single-quoted literal or a JSON-quoted comment, so no recipe value ends a literal, a comment or
PHP mode."""

from typing import Any

import pytest

from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.exporters.php_hint import php_hint
from crawlerai.core.ids import uuid7


def _recipe(**changes: Any) -> ApiRecipe:
    document = {
        "method": "GET",
        "url": "https://api.example.test/v1/items/{slug}?lang={lang}&fmt=json",
        "params_from_url": {"slug": "path:1", "lang": "query:hl"},
        "headers": [
            {"name": "X-Requested-With", "value": "XMLHttpRequest"},
            {"name": "Referer", "value": "{page_url}"},
        ],
        "map": {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
        "proof": {"validated_on": [str(uuid7())], "headers_tried": 2, "bound_by": "deterministic"},
        **changes,
    }
    return ApiRecipe.model_validate(document)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()]


def test_a_get_hint_substitutes_the_parameters_into_the_url_and_sends_the_headers() -> None:
    lines = _lines(php_hint(_recipe()))

    assert lines[0] == "<?php"
    assert "'method' => 'GET'," in lines
    url = "strtr('https://api.example.test/v1/items/{slug}', $path) . '?' . strtr('lang={lang}&fmt=json', $query)"
    assert f"'url' => {url}," in lines
    assert "'body' => null," in lines
    assert "'Accept: application/json'," in lines
    assert "'X-Requested-With: XMLHttpRequest'," in lines
    assert "str_replace('{page_url}', $page_url, 'Referer: {page_url}')," in lines


_ROWS = "\"$['items'][*]\""


@pytest.mark.parametrize(
    ("pagination", "line"),
    [
        (
            {"kind": "param", "where": "query", "name": "offset", "start": 0, "step": 20, "rows": "$['items'][*]"},
            f'// Pagination: set "query" value "offset" to 0, 20, 40, ... until {_ROWS} selects nothing.',
        ),
        (
            {"kind": "cursor", "where": "query", "name": "after", "cursor": "$['next']", "rows": "$['items'][*]"},
            '// Pagination: set "query" value "after" to the value the previous response holds at "$[\'next\']", '
            f"until it holds none or {_ROWS} selects nothing.",
        ),
        (
            {"kind": "next_url", "next": "$['links']['next']", "rows": "$['items'][*]"},
            "// Pagination: request the URL the previous response holds at \"$['links']['next']\" (RFC 3986 "
            f"resolution, same origin), until it holds none or {_ROWS} selects nothing.",
        ),
        (
            {"kind": "link", "rows": "$['items'][*]"},
            '// Pagination: request the target of the previous response\'s Link header with rel="next" (RFC 8288, '
            f"same origin), until there is none or {_ROWS} selects nothing.",
        ),
    ],
    ids=["param", "cursor", "next_url", "link"],
)
def test_a_paginated_hint_says_how_the_next_page_is_requested(pagination: dict[str, object], line: str) -> None:
    assert line in _lines(php_hint(_recipe(pagination=pagination)))
    assert "Pagination" not in php_hint(_recipe())
