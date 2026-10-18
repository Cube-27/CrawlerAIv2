"""Dev scoring rules (D-1480, D-1484, D-1487): engine rows bounded to the labeled page, image renditions of one file,
and a place whose label states only its text. Every value is synthetic (RFC 2606 hosts, C3, C9)."""

from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.eval.scoring import same
from crawlerai.schemas.types import FieldSpec, FieldType

IMAGE = FieldSpec(type=FieldType.IMAGE_URL)
IMAGES = FieldSpec(type=FieldType.LIST, item=IMAGE)
PLACE = FieldSpec(type=FieldType.LOCATION)


@pytest.mark.parametrize(
    ("output", "label"),
    [
        ("http://cdn.example.com/i/a.jpg?v=1", "https://cdn.example.com/i/a.jpg?v=1&width=2000"),
        ("https://cdn.example.com/i/a.jpg?w=100", "https://cdn.example.com/i/a.jpg"),
        ("https://cdn.example.com/i/a_1200x.jpg", "https://cdn.example.com/i/a_1024x.jpg"),  # a size the path states
    ],
)
def test_renditions_of_one_image_file_score_as_the_same_image(output: str, label: str) -> None:
    assert same(output, label, IMAGE)
    assert same([output, "https://cdn.example.com/i/b.jpg"], ["https://cdn.example.com/i/b.jpg?w=1", label], IMAGES)


def _place(text: str | None, **parts: Any) -> JsonValue:
    return {"text": text, "locality": None, "region": None, "country": None, "remote_flag": None, **parts}


def test_a_text_only_label_scores_an_output_with_parsed_parts_whose_text_agrees() -> None:
    label = _place("Example City, Example Land")
    assert same(_place("example city,  example land", locality="Example City", country="EX"), label, PLACE)
    assert not same(_place("Other Town", locality="Other Town"), label, PLACE)
    # The remote flag still counts: it is stated, not a parsed part.
    assert not same(_place("Example City, Example Land", remote_flag=True), label, PLACE)
