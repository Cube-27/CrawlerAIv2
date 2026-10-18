"""Dev scoring rules (D-1480, D-1484, D-1487): engine rows bounded to the labeled page, image renditions of one file,
and a place whose label states only its text. Every value is synthetic (RFC 2606 hosts, C3, C9)."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import EvalCase, FieldMetrics, FieldOutput, PageOutput, SchemaFields, build_report
from crawlerai.eval.scoring import same
from crawlerai.schemas.types import FieldSpec, FieldType

LISTING = SchemaFields(
    name="synthetic_listing",
    page_kind="listing",
    fields={"title": FieldSpec(type=FieldType.TEXT), "url": FieldSpec(type=FieldType.URL)},
)
IMAGE = FieldSpec(type=FieldType.IMAGE_URL)
IMAGES = FieldSpec(type=FieldType.LIST, item=IMAGE)
PLACE = FieldSpec(type=FieldType.LOCATION)
PLACES = FieldSpec(type=FieldType.LIST, item=PLACE)


def _labels(rows: list[dict[str, Any]]) -> Labels:
    return Labels.model_validate(
        {
            "label_version": 1,
            "status": "draft",
            "prefill_source": "none",
            "fields": {},
            "rows": [{"fields": {k: {"value": v, "absent": False} for k, v in r.items()}} for r in rows],
        }
    )


def _row(n: int) -> dict[str, FieldOutput]:
    return {
        "title": FieldOutput(status="published", value=f"Item {n}", evidence="adapter"),
        "url": FieldOutput(status="published", value=f"https://shop.example.com/p/{n}", evidence="adapter"),
    }


def _listing(label_rows: int, engine_rows: list[int]) -> EvalCase:
    labels = _labels([{"title": f"Item {n}", "url": f"https://shop.example.com/p/{n}"} for n in range(label_rows)])
    output = PageOutput(block_class="ok", mode="adhoc", rows=tuple(_row(n) for n in engine_rows))
    return EvalCase(page_id="p1", category="platform_store", schema_def=LISTING, labels=labels, output=output)


def _url_cell(case: EvalCase, rows: Any) -> FieldMetrics:
    report = build_report([case], "dev", "e1", "abc", frozenset({"draft", "checked"}), rows=rows)
    found = report.by_field_type["url"]
    assert isinstance(found, FieldMetrics)
    assert report.rows_scored == rows
    return found


@given(labeled=st.integers(min_value=1, max_value=8), further=st.integers(min_value=0, max_value=20))
def test_rows_past_the_labeled_page_count_only_in_the_all_rows_report(labeled: int, further: int) -> None:
    # An adapter reads the list's further pages: the label holds the first page's rows, which come first.
    case = _listing(labeled, list(range(labeled + further)))
    bounded, every = _url_cell(case, "labeled"), _url_cell(case, "all")
    assert (bounded.precision, bounded.coverage, bounded.n) == (1.0, 1.0, labeled)
    assert every.precision == labeled / (labeled + further)


def test_an_unmatched_row_inside_the_labeled_count_is_still_a_false_positive() -> None:
    # Label rows 0..2; the engine's first three rows are 0, 9 and 1, then 2 and 8: row 9 is on the labeled page, row 8
    # is past it, and row 2 still matches its label row wherever it is.
    case = _listing(3, [0, 9, 1, 2, 8])
    bounded = _url_cell(case, "labeled")
    assert (bounded.precision, bounded.coverage) == (3 / 4, 1.0)


def test_only_a_dev_report_bounds_its_rows() -> None:
    with pytest.raises(ValueError, match="only a dev report bounds"):
        build_report([], "hidden", "e1", "abc", rows="labeled")


@pytest.mark.parametrize(
    ("output", "label"),
    [
        ("http://cdn.example.com/i/a.jpg?v=1", "https://cdn.example.com/i/a.jpg?v=1&width=2000"),
        ("https://cdn.example.com/i/a.jpg?w=100", "https://cdn.example.com/i/a.jpg"),
    ],
)
def test_renditions_of_one_image_file_score_as_the_same_image(output: str, label: str) -> None:
    assert same(output, label, IMAGE)
    assert same([output, "https://cdn.example.com/i/b.jpg"], ["https://cdn.example.com/i/b.jpg?w=1", label], IMAGES)


@pytest.mark.parametrize(
    ("output", "label"),
    [
        ("https://cdn.example.com/i/a_1200x.jpg", "https://cdn.example.com/i/a_1024x.jpg"),  # another path
        ("https://cdn.example.net/i/a.jpg", "https://cdn.example.com/i/a.jpg"),  # another host
        ("not a url", "not a url either"),
    ],
)
def test_images_of_other_files_do_not(output: str, label: str) -> None:
    assert not same(output, label, IMAGE)


def _place(text: str | None, **parts: Any) -> JsonValue:
    return {"text": text, "locality": None, "region": None, "country": None, "remote_flag": None, **parts}


def test_a_text_only_label_scores_an_output_with_parsed_parts_whose_text_agrees() -> None:
    label = _place("Example City, Example Land")
    assert same(_place("example city,  example land", locality="Example City", country="EX"), label, PLACE)
    assert not same(_place("Other Town", locality="Other Town"), label, PLACE)
    # The remote flag still counts: it is stated, not a parsed part.
    assert not same(_place("Example City, Example Land", remote_flag=True), label, PLACE)


def test_a_label_with_parts_still_compares_its_parts() -> None:
    label = _place("Example City", locality="Example City")
    assert not same(_place("Example City", locality="Other Town"), label, PLACE)


def test_lists_of_places_pair_each_label_place_with_one_output_place() -> None:
    labels = [_place("Alpha"), _place("Beta")]
    assert same([_place("Beta", locality="Beta"), _place("Alpha", country="EX")], labels, PLACES)
    assert not same([_place("Alpha", locality="Alpha"), _place("Alpha")], labels, PLACES)
    assert not same([_place("Alpha")], labels, PLACES)
