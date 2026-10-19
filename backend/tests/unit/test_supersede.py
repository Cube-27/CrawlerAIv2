"""Fragments of a text, long_text or image list value that another candidate supersedes (resolution spec, source
precedence)."""

import pytest
from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.supersede import superseded
from crawlerai.schemas.types import FieldSpec, FieldType

LONG = "The role owns the example service end to end. It reviews designs, ships changes and answers pages."


_LOCATORS: dict[SourceKind, str] = {
    "og": "meta:og:x0",
    "dom": "dom:/html[1]/body[1]/h1[1]",
    "jsonld": "jsonld:0:$['x0']",
    "microdata": "jsonld:0:$['x1']",
}


def _c(value: JsonValue, kind: SourceKind) -> Candidate:
    return Candidate(
        field="f",
        entity_id="e",
        source_kind=kind,
        raw=value,
        normalized=Ok(value),
        locator=_LOCATORS[kind],
        independent=True,
    )


@pytest.mark.parametrize("cut", [LONG[:40], LONG[:40] + "…", LONG[:40] + " ...", LONG[:40] + "..."])
def test_a_prefix_or_ellipsis_cut_prefix_is_superseded_by_the_longer_text(cut: str) -> None:
    short, full = _c(cut, "jsonld"), _c(LONG, "dom")

    assert superseded(FieldSpec(type=FieldType.LONG_TEXT), [short, full]) == [short]


def test_an_open_graph_summary_yields_to_a_longer_description_of_another_kind() -> None:
    summary, full = _c("See all open roles at Example.", "og"), _c(LONG, "dom")

    assert superseded(FieldSpec(type=FieldType.LONG_TEXT), [summary, full]) == [summary]


@pytest.mark.parametrize(
    "decorated",
    [
        "Desk Lamp | Example Shop",
        "Desk Lamp - Careers at Example",
        "Desk Lamp \u2013 Example",
        "Example Shop | Desk Lamp",
    ],
)
def test_a_value_with_a_separator_and_more_text_yields_to_another_kinds_clean_value(decorated: str) -> None:
    dirty, clean = _c(decorated, "og"), _c("Desk Lamp", "dom")

    assert superseded(FieldSpec(type=FieldType.TEXT), [dirty, clean]) == [dirty]


def test_an_open_graph_image_list_yields_to_a_longer_list_of_another_kind_naming_its_file() -> None:
    images = FieldSpec.model_validate({"type": "list", "item": {"type": "image_url"}})
    cdn = "https://cdn.example.test/p"
    og = _c([f"{cdn}/a.jpg"], "og")
    gallery = _c([f"{cdn}/a.jpg?w=900", f"{cdn}/b.jpg"], "dom")
    other = _c([f"{cdn}/c.jpg", f"{cdn}/d.jpg"], "dom")

    assert superseded(images, [og, gallery]) == [og]
    # A longer list that leaves the Open Graph file out is another set of images, not its gallery.
    assert superseded(images, [og, other]) == []
