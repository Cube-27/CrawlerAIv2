"""JSONPath queries over collector documents (RFC 9535): name, wildcard and index segments, each match with its
normalized path."""

import pytest
from pydantic import JsonValue

from crawlerai.collect.json_doc import select

DOCUMENT: JsonValue = {
    "jobs": [{"title": "A", "location": {"name": "Remote"}}, {"title": "B"}, "not an object"],
    "meta": {"total": 2},
}


def test_name_segments_follow_members_and_skip_nodes_without_them() -> None:
    assert select("$['jobs'][*]['location']['name']", DOCUMENT) == [("$['jobs'][0]['location']['name']", "Remote")]


def test_a_wildcard_selects_every_array_item_and_object_member_in_order() -> None:
    assert select("$['jobs'][*]['title']", DOCUMENT) == [("$['jobs'][0]['title']", "A"), ("$['jobs'][1]['title']", "B")]
    assert select("$['meta'][*]", DOCUMENT) == [("$['meta']['total']", 2)]


@pytest.mark.parametrize("query", ["jobs", "$..title", "$['jobs'][01]", "$['a\\'b']"])
def test_a_query_outside_the_subset_is_refused(query: str) -> None:
    with pytest.raises(ValueError, match="query"):
        select(query, DOCUMENT)
