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


@pytest.mark.parametrize("kind", ["og", "jsonld"])
def test_an_image_list_yields_to_a_longer_list_of_another_kind_naming_its_files(kind: SourceKind) -> None:
    images = FieldSpec.model_validate({"type": "list", "item": {"type": "image_url"}})
    cdn = "https://cdn.example.test/p"
    main = _c([f"{cdn}/a.jpg"], kind)
    gallery = _c([f"{cdn}/a.jpg?w=900", f"{cdn}/b.jpg"], "dom")
    other = _c([f"{cdn}/c.jpg", f"{cdn}/d.jpg"], "dom")

    assert superseded(images, [main, gallery]) == [main]
    # A longer list that leaves the shorter list's file out is another set of images, not its gallery.
    assert superseded(images, [main, other]) == []
    # A longer list of the same kind is no other source's account of the images.
    assert superseded(images, [main, _c([f"{cdn}/a.jpg", f"{cdn}/b.jpg"], kind)]) == []
    # A rendition an image server writes into the path names the file too (`url.same_file`).
    served = _c([f"{cdn}/v2/p/a.jpg/renditions/600.jpg", f"{cdn}/b.jpg"], "dom")
    assert superseded(images, [main, served]) == [main]


def test_an_open_graph_image_list_yields_to_a_longer_list_naming_its_first_image() -> None:
    # Open Graph "Arrays": the first og:image is preferred; a site default after it is no view of the object.
    images = FieldSpec.model_validate({"type": "list", "item": {"type": "image_url"}})
    cdn = "https://cdn.example.test/p"
    gallery = _c([f"{cdn}/a.jpg", f"{cdn}/b.jpg", f"{cdn}/c.jpg"], "dom")
    og, jsonld = _c([f"{cdn}/a.jpg", f"{cdn}/site.png"], "og"), _c([f"{cdn}/a.jpg", f"{cdn}/site.png"], "jsonld")

    assert superseded(images, [og, jsonld, gallery]) == [og]


def test_a_value_stating_the_open_graph_summary_is_a_summary_whatever_its_kind() -> None:
    summary, tagline, full = _c("See all open roles.", "og"), _c("See all open roles.", "jsonld"), _c(LONG, "dom")

    assert superseded(FieldSpec(type=FieldType.LONG_TEXT), [summary, tagline, full]) == [summary, tagline]


def test_a_text_with_its_line_breaks_dropped_yields_to_the_rendition_that_keeps_them() -> None:
    flat, lined = _c("Includes:• 1 lantern• 2 bulbs", "jsonld"), _c("Includes:\n• 1 lantern\n• 2 bulbs", "dom")
    other = _c("Includes:• 1 lantern• 3 bulbs", "microdata")

    assert superseded(FieldSpec(type=FieldType.LONG_TEXT), [flat, lined, other]) == [flat]


def test_a_text_led_by_its_heading_yields_to_the_longer_text_without_it() -> None:
    # HTML Standard §4.3.6: a heading names its section; text content runs the paragraphs together.
    headed = _c("About this role\n\nThe role owns the example service end to end.  It\nreviews", "microdata")
    full = _c(LONG, "dom")

    assert superseded(FieldSpec(type=FieldType.LONG_TEXT), [headed, full]) == [headed]
