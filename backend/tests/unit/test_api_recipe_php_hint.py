"""The PHP hint of an API recipe (SPEC-09 §4.9, ARCHITECTURE §12.2, OPEN_QUESTIONS #12): a curl request rendered from
the recipe's data, with its parameters substituted, its headers, and its JSONPath map as comments. Every recipe string
is written as a PHP single-quoted literal or a JSON-quoted comment, so no recipe value ends a literal, a comment or
PHP mode."""

import json
import re
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.exporters.php_hint import php_comment, php_hint, php_literal
from crawlerai.core.ids import uuid7


def _recipe(**changes: Any) -> ApiRecipe:
    document = {
        "method": "GET",
        "url": "https://api.example.test/v1/items/{slug}?lang={lang}&fmt=json",
        "params_from_url": {"slug": "path:1", "lang": "query:hl"},
        "headers": {"X-Requested-With": "XMLHttpRequest", "Referer": "{page_url}"},
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


def test_the_hint_names_each_parameter_binder_and_each_mapped_path() -> None:
    lines = _lines(php_hint(_recipe()))

    assert '//   "slug": "path:1"' in lines
    assert '//   "lang": "query:hl"' in lines
    assert "//   \"title\": \"$['data']['name']\"" in lines
    assert "//   \"price\": \"$['data']['price']+$['data']['currency']\"" in lines


def test_a_parameter_is_percent_encoded_as_the_engine_encodes_it_in_a_path_and_a_query() -> None:
    lines = _lines(php_hint(_recipe()))

    # RFC 3986 §3.3 and §3.4: rawurlencode keeps the unreserved characters; the hint restores the rest of the
    # characters each part allows unencoded, as `render_url` does.
    assert "$path['{' . $name . '}'] = strtr(rawurlencode($value), " + _decode_map("!$&'()*+,;=:@") + ");" in lines
    assert "$query['{' . $name . '}'] = strtr(rawurlencode($value), " + _decode_map("!$'()*,;:@/?") + ");" in lines


def _decode_map(safe: str) -> str:
    pairs = ", ".join(f"'%{ord(c):02X}' => {php_literal(c)}" for c in safe)
    return f"[{pairs}]"


def test_a_post_hint_fills_its_json_body_and_sends_no_form_content_type() -> None:
    recipe = _recipe(
        method="POST",
        url="https://api.example.test/v1/search",
        params_from_url={"slug": "path:1"},
        body={"template": '{"slug":"{slug}","n":1}'},
    )
    lines = _lines(php_hint(recipe))

    assert "'method' => 'POST'," in lines
    assert "'url' => strtr('https://api.example.test/v1/search', $path)," in lines
    assert """'body' => strtr('{"slug":"{slug}","n":1}', $json),""" in lines
    # curl sends a form content type with a POST; the engine sends none unless the recipe names one.
    assert "'Content-Type:'," in lines


def test_a_recipe_naming_a_content_type_or_accept_replaces_the_default() -> None:
    recipe = _recipe(
        method="POST",
        url="https://api.example.test/v1/search",
        params_from_url={"slug": "path:1"},
        headers={"accept": "application/vnd.test+json", "Content-Type": "application/json"},
        body={"template": '{"q":"{slug}"}'},
    )
    lines = _lines(php_hint(recipe))

    assert "'accept: application/vnd.test+json'," in lines
    assert "'Content-Type: application/json'," in lines
    assert "'Accept: application/json'," not in lines
    assert "'Content-Type:'," not in lines


def test_a_hint_that_reads_page_data_says_the_page_is_fetched_first() -> None:
    recipe = _recipe(
        url="https://api.example.test/v1/items/{sku}",
        params_from_url={"sku": "jsonld:$[0]['sku']"},
        headers={},
        requires_page_fetch=True,
    )
    text = php_hint(recipe)

    assert '//   "sku": "jsonld:$[0][\'sku\']"' in _lines(text)
    assert "// This recipe reads the page's JSON documents: fetch the page's HTML first." in _lines(text)


def test_a_paginated_hint_says_how_the_next_page_is_requested() -> None:
    pagination = {"kind": "param", "name": "offset", "start": 0, "step": 20, "rows": "$['items'][*]"}
    lines = _lines(php_hint(_recipe(pagination=pagination)))

    rows = "\"$['items'][*]\""
    assert f'// Pagination: set query parameter "offset" to 0, 20, 40, ... until {rows} selects nothing.' in lines


def test_a_hint_without_pagination_says_nothing_about_it() -> None:
    assert "Pagination" not in php_hint(_recipe())


def test_recipe_strings_that_look_like_php_stay_inside_their_literal_or_comment() -> None:
    hostile = "a'b\\c?>d"
    recipe = _recipe(
        url="https://api.example.test/v1/items/{slug}?q=" + "x'?>",
        params_from_url={"slug": "path:1"},
        headers={"X-K": hostile},
        map={"title": "$['a?>b']"},
    )
    text = php_hint(recipe)

    assert "'X-K: a\\'b\\\\c?>d'," in _lines(text)
    assert '//   "title": "$[\'a?\\u003eb\']"' in _lines(text)
    assert _outside_literals(text).count("?>") == 0


def _outside_literals(text: str) -> str:
    """`text` without its PHP single-quoted literals (PHP manual, "Single quoted": `\\'` and `\\\\` are the escapes)."""
    return re.sub(r"'(?:[^'\\]|\\.)*'", "''", text)


def _php_single_quoted(literal: str) -> str:
    """The value of a PHP single-quoted literal: `\\'` is `'`, `\\\\` is `\\`, any other backslash is itself."""
    assert literal[0] == literal[-1] == "'"
    return re.sub(r"\\([\\'])", r"\1", literal[1:-1])


@given(st.text())
def test_a_literal_reads_back_as_the_string_it_was_made_from(value: str) -> None:
    literal = php_literal(value)

    assert _php_single_quoted(literal) == value
    assert re.fullmatch(r"'(?:[^'\\]|\\.)*'", literal, re.DOTALL) is not None


@given(st.text())
def test_a_comment_is_one_line_reading_back_as_the_string_it_was_made_from(value: str) -> None:
    comment = php_comment(value)

    assert json.loads(comment) == value
    assert "?>" not in comment
    assert comment.isascii() and comment.isprintable()
