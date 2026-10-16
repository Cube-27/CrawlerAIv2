"""JSONPath queries over collector documents (RFC 9535): name, wildcard and index segments, each match with its
normalized path."""

import json
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.json_doc import parse, select

DOCUMENT: JsonValue = {
    "jobs": [{"title": "A", "location": {"name": "Remote"}}, {"title": "B"}, "not an object"],
    "meta": {"total": 2},
}

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=5),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=5), children, max_size=4),
    max_leaves=20,
)


def test_the_root_query_selects_the_document() -> None:
    assert select("$", DOCUMENT) == [("$", DOCUMENT)]


def test_name_segments_follow_members_and_skip_nodes_without_them() -> None:
    assert select("$['jobs'][*]['location']['name']", DOCUMENT) == [("$['jobs'][0]['location']['name']", "Remote")]


def test_a_wildcard_selects_every_array_item_and_object_member_in_order() -> None:
    assert select("$['jobs'][*]['title']", DOCUMENT) == [("$['jobs'][0]['title']", "A"), ("$['jobs'][1]['title']", "B")]
    assert select("$['meta'][*]", DOCUMENT) == [("$['meta']['total']", 2)]


def test_a_member_named_like_a_selector_is_only_that_member() -> None:
    assert select("$['*']", {"*": 1, "a": 2}) == [("$['*']", 1)]
    assert select("$['0']", [5]) == []


def test_an_index_segment_selects_one_array_item_and_a_normalized_path_selects_its_node() -> None:
    assert select("$['jobs'][1]", DOCUMENT) == [("$['jobs'][1]", {"title": "B"})]
    assert select("$['jobs'][3]", DOCUMENT) == []
    assert select("$['meta'][0]", DOCUMENT) == []
    for path, value in select("$['jobs'][*][*]", DOCUMENT):
        assert select(path, DOCUMENT) == [(path, value)]


def test_a_query_starts_at_the_given_path() -> None:
    row: JsonValue = {"title": "A"}
    assert select("$['title']", row, at="$['jobs'][0]") == [("$['jobs'][0]['title']", "A")]


@pytest.mark.parametrize("query", ["jobs", "$..title", "$['jobs'][01]", "$['a\\'b']"])
def test_a_query_outside_the_subset_is_refused(query: str) -> None:
    with pytest.raises(ValueError, match="query"):
        select(query, DOCUMENT)


@given(document=json_values)
def test_every_match_of_a_wildcard_is_a_child_of_the_node(document: JsonValue) -> None:
    children = list(document.values()) if isinstance(document, dict) else document if isinstance(document, list) else []
    assert [value for _, value in select("$[*]", document)] == children


# RFC 8259 §7: a string's control characters (U+0000-U+001F) must be escaped; json.dumps writes them as these escapes.
_CONTROL_ESCAPE = re.compile(r"\\(\\|u00[01][0-9a-f]|[bfnrt])")
_SHORT = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _raw_controls(match: re.Match[str]) -> str:
    """Each control-character escape written back as the raw character; an escaped backslash stays escaped."""
    escape = match[1]
    if escape == "\\":
        return "\\\\"
    return chr(int(escape[1:], 16)) if escape.startswith("u") else _SHORT[escape]


control_text = st.text(alphabet=st.characters(max_codepoint=0x7F), max_size=8)
documents_with_controls = st.recursive(
    st.none() | st.booleans() | st.integers() | control_text,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(control_text, children, max_size=4),
    max_leaves=20,
)


@given(document=documents_with_controls)
def test_raw_control_characters_inside_strings_parse_leniently_as_the_same_document(document: JsonValue) -> None:
    text = _CONTROL_ESCAPE.sub(_raw_controls, json.dumps(document))
    assert parse(text, lenient=True) == document


def test_a_raw_control_character_in_a_string_is_refused_strictly() -> None:
    text = '{"description": "line one\nline two"}'
    with pytest.raises(ValueError, match="control character"):
        parse(text)


@pytest.mark.parametrize("text", ['{"a": 1,}', '{"a": NaN}', '{"a":\x01 1}', "{'a': 1}"])
def test_lenient_parsing_still_refuses_everything_else_that_is_not_json(text: str) -> None:
    with pytest.raises(ValueError):
        parse(text, lenient=True)
