"""Fragments of a text or long_text value that another candidate supersedes (resolution spec, source precedence)."""

import pytest

from crawlerai.collect.base import Candidate
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.supersede import superseded
from crawlerai.schemas.types import FieldType

LONG = "The role owns the example service end to end. It reviews designs, ships changes and answers pages."


_LOCATORS: dict[SourceKind, str] = {
    "og": "meta:og:x0",
    "dom": "dom:/html[1]/body[1]/h1[1]",
    "jsonld": "jsonld:0:$['x0']",
    "microdata": "jsonld:0:$['x1']",
}


def _c(value: str, kind: SourceKind) -> Candidate:
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

    assert superseded(FieldType.LONG_TEXT, [short, full]) == [short]


def test_a_prefix_is_compared_in_collapsed_whitespace() -> None:
    short, full = _c("The role owns the\n\nexample service", "jsonld"), _c(LONG, "dom")

    assert superseded(FieldType.LONG_TEXT, [short, full]) == [short]


def test_an_open_graph_summary_yields_to_a_longer_description_of_another_kind() -> None:
    summary, full = _c("See all open roles at Example.", "og"), _c(LONG, "dom")

    assert superseded(FieldType.LONG_TEXT, [summary, full]) == [summary]


def test_an_open_graph_description_longer_than_the_others_is_not_superseded() -> None:
    og, other = _c(LONG, "og"), _c("A different tagline.", "jsonld")

    assert superseded(FieldType.LONG_TEXT, [og, other]) == []


def test_an_entity_like_literal_is_not_decoded_again() -> None:
    literal, other = _c("Tom &amp; Jerry", "jsonld"), _c("Tom & Jerry and the full story of the cat.", "dom")

    assert superseded(FieldType.LONG_TEXT, [literal, other]) == []


def test_unrelated_or_equal_long_texts_supersede_nothing() -> None:
    a, b, c = _c(LONG, "jsonld"), _c(LONG, "dom"), _c("Unrelated description of another kind.", "microdata")

    assert superseded(FieldType.LONG_TEXT, [a, b, c]) == []


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

    assert superseded(FieldType.TEXT, [dirty, clean]) == [dirty]


@pytest.mark.parametrize(
    ("longer", "shorter"),
    [
        ("Desk Lamp Pro", "Desk Lamp"),  # no separator
        ("Desk Lamp + Shade", "Desk Lamp"),  # a plus joins products, it does not decorate
        ("Desk Lamp (white)", "Desk Lamp"),
        ("Desk Lamp-Example", "Desk Lamp"),  # no spaces
    ],
)
def test_a_longer_text_without_a_spaced_separator_is_not_decoration(longer: str, shorter: str) -> None:
    assert superseded(FieldType.TEXT, [_c(longer, "og"), _c(shorter, "dom")]) == []


def test_decoration_is_judged_between_source_kinds_only() -> None:
    assert superseded(FieldType.TEXT, [_c("Desk Lamp | Example", "dom"), _c("Desk Lamp", "dom")]) == []


def test_other_types_supersede_nothing() -> None:
    assert superseded(FieldType.URL, [_c("Desk Lamp | Example", "og"), _c("Desk Lamp", "dom")]) == []
