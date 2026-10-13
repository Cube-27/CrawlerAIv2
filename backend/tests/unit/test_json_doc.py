"""JSONPath queries over collector documents (RFC 9535): name, wildcard and index segments, each match with its
normalized path."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.json_doc import select

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


@pytest.mark.parametrize(
    "query", ["", "jobs", "$.jobs", "$['jobs'][-1]", "$['jobs'][01]", "$[?@.title]", "$..title", "$['a\\'b']"]
)
def test_a_query_outside_the_subset_is_refused(query: str) -> None:
    with pytest.raises(ValueError, match="query"):
        select(query, DOCUMENT)


@given(document=json_values)
def test_every_match_of_a_wildcard_is_a_child_of_the_node(document: JsonValue) -> None:
    children = list(document.values()) if isinstance(document, dict) else document if isinstance(document, list) else []
    assert [value for _, value in select("$[*]", document)] == children
