"""Metrics and the aggregate report (SPEC-03 §4.6, §4.7): each cell of the §4.6 table from hand-built label/output
pairs, listing rows matched by url, zero-touch, acquisition, usage, and min-cell suppression."""

from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.eval.labels import InvalidLabels, Labels
from crawlerai.eval.metrics import (
    EvalCase,
    FieldMetrics,
    FieldOutput,
    PageOutput,
    PrecisionMetrics,
    ReplayFailed,
    Report,
    SchemaFields,
    SourceMetrics,
    Usage,
    ZeroTouch,
    build_report,
)
from crawlerai.schemas.types import FieldSpec, FieldType

EUR_19: JsonValue = {"amount": "19.90", "currency": "EUR"}
EUR_24: JsonValue = {"amount": "24.90", "currency": "EUR"}

DETAIL = SchemaFields(
    name="commerce_detail",
    page_kind="detail",
    fields={"price": FieldSpec(type=FieldType.MONEY), "brand": FieldSpec(type=FieldType.TEXT)},
    required=frozenset({"price"}),
)
LISTING_SPECS: dict[str, FieldSpec] = {
    "title": FieldSpec(type=FieldType.TEXT),
    "url": FieldSpec(type=FieldType.URL),
    "next_page": FieldSpec(type=FieldType.URL, scope="page"),
}
LISTING = SchemaFields(name="commerce_listing", page_kind="listing", fields=LISTING_SPECS, required=frozenset({"url"}))


def label(value: JsonValue = None) -> dict[str, Any]:
    return {"value": value, "absent": value is None, "distractors": []}


def labels(fields: dict[str, Any], rows: list[dict[str, Any]] | None = None, status: str = "checked") -> Labels:
    return Labels.model_validate(
        {
            "label_version": 1,
            "status": status,
            "labeler": "labeler-a",
            "checker": "checker-b" if status == "checked" else None,
            "fields": fields,
            "rows": [{"fields": r} for r in rows or []],
        }
    )


def published(value: JsonValue, evidence: str = "structured") -> FieldOutput:
    return FieldOutput.model_validate({"status": "published", "value": value, "evidence": evidence})


ABSTAINED = FieldOutput(status="abstained")


def detail_case(
    page_id: str,
    price_label: JsonValue,
    price_out: FieldOutput | None,
    *,
    category: str = "custom_store",
    **output: Any,
) -> EvalCase:
    fields = {"price": price_out} if price_out is not None else {}
    return EvalCase.model_validate(
        {
            "page_id": page_id,
            "category": category,
            "schema_def": DETAIL,
            "labels": labels({"price": label(price_label), "brand": label(None)}),
            "output": PageOutput.model_validate({"block_class": "ok", "mode": "adhoc", "fields": fields, **output}),
        }
    )


def report(*cases: EvalCase) -> Report:
    return build_report(cases, "dev", engine_version="e1", git_sha="abc")


def money(r: Report) -> FieldMetrics:
    cell = r.by_field_type["money"]
    assert isinstance(cell, FieldMetrics)
    return cell


@pytest.mark.parametrize("status", ["missing", "conflict"])
def test_fn_not_published_where_label_present(status: str) -> None:
    r = report(detail_case("p1", EUR_19, FieldOutput.model_validate({"status": status})))

    assert money(r) == FieldMetrics(
        precision=None, coverage=0.0, abstain_rate=1.0, false_publish_on_absent=None, wrong_product=0, n=1
    )


def test_tn_not_published_where_label_absent() -> None:
    r = report(detail_case("p1", None, None))

    assert money(r) == FieldMetrics(
        precision=None, coverage=None, abstain_rate=1.0, false_publish_on_absent=0.0, wrong_product=0, n=1
    )


def test_cells_combine_into_the_ratios() -> None:
    # TP, TP, FP, FN, TN, FP on absent: precision 2/4, coverage 2/3 (a wrong publish is not an FN), abstain 2/6,
    # false publish on absent 1/2.
    r = report(
        detail_case("p1", EUR_19, published(EUR_19)),
        detail_case("p2", EUR_19, published(EUR_19)),
        detail_case("p3", EUR_19, published(EUR_24)),
        detail_case("p4", EUR_19, ABSTAINED),
        detail_case("p5", None, ABSTAINED),
        detail_case("p6", None, published(EUR_24)),
    )

    assert money(r) == FieldMetrics(
        precision=0.5, coverage=2 / 3, abstain_rate=2 / 6, false_publish_on_absent=0.5, wrong_product=0, n=6
    )
    assert r.by_field["commerce_detail|price"] == money(r)
    assert r.n_pages == 6


def test_buckets_and_config_status_count_published_fields() -> None:
    case = detail_case("p1", EUR_19, published(EUR_19, evidence="config_corroborated"))
    case = case.model_copy(update={"config_status": {"price": "corroborated"}})
    r = report(case, detail_case("p2", EUR_19, published(EUR_24, evidence="structured")), detail_case("p3", None, None))

    assert r.by_bucket == {
        "money|config_corroborated": PrecisionMetrics(precision=1.0, n=1),
        "money|structured": PrecisionMetrics(precision=0.0, n=1),
    }
    assert r.by_config_status == {"money|corroborated": PrecisionMetrics(precision=1.0, n=1)}


def test_only_checked_pages_count() -> None:
    labeled = detail_case("p2", EUR_19, published(EUR_24))
    unchecked = labeled.labels.model_copy(update={"status": "labeled", "checker": None})
    labeled = labeled.model_copy(update={"labels": unchecked})

    r = report(detail_case("p1", EUR_19, published(EUR_19)), labeled)

    assert r.n_pages == 1
    assert money(r).n == 1


def test_failed_replay_is_dropped_but_listed_on_dev() -> None:
    failed = detail_case("p2", EUR_19, None).model_copy(update={"output": ReplayFailed(error="bundle missing")})

    r = report(detail_case("p1", EUR_19, published(EUR_19)), failed)

    assert r.n_pages == 1
    assert money(r).n == 1
    assert r.pages is not None
    assert [(p.page_id, p.error, p.judgments) for p in r.pages if p.error] == [("p2", "bundle missing", ())]


def test_labels_must_fit_the_schema() -> None:
    partial = labels({"price": label(EUR_19)})
    output = PageOutput(block_class="ok", mode="adhoc")

    with pytest.raises(InvalidLabels, match="brand: not labeled"):
        EvalCase(page_id="p1", category="mixed", schema_def=DETAIL, labels=partial, output=output)


def listing_case(
    label_rows: list[dict[str, Any]], out_rows: list[dict[str, FieldOutput]], page_id: str = "l1"
) -> EvalCase:
    return EvalCase(
        page_id=page_id,
        category="job_board",
        schema_def=LISTING,
        labels=labels({"next_page": label(None)}, label_rows),
        output=PageOutput(block_class="ok", mode="adhoc", rows=tuple(out_rows)),
    )


def judgments(r: Report) -> list[tuple[str, str, str]]:
    assert r.pages is not None
    return [(j.entity, j.field, j.cell) for p in r.pages for j in p.judgments]


def test_listing_rows_match_by_url_in_any_order() -> None:
    a, b = "https://shop.example.test/a", "https://shop.example.test/b"
    case = listing_case(
        [{"title": label("A"), "url": label(a)}, {"title": label("B"), "url": label(b)}],
        [{"title": published("B wrong"), "url": published(b)}, {"title": published("A"), "url": published(a)}],
    )

    r = report(case)

    assert judgments(r) == [
        ("page", "next_page", "TN"),
        ("row[0]", "title", "TP"),
        ("row[0]", "url", "TP"),
        ("row[1]", "title", "FP"),
        ("row[1]", "url", "TP"),
    ]


def test_unmatched_rows_are_fp_and_fn() -> None:
    case = listing_case(
        [{"title": label("A"), "url": label("https://shop.example.test/a")}],
        [{"title": published("X"), "url": published("https://shop.example.test/x"), "next_page": ABSTAINED}],
    )

    r = report(case)

    assert judgments(r) == [
        ("page", "next_page", "TN"),
        ("row[0]", "title", "FN"),
        ("row[0]", "url", "FN"),
        ("extra[0]", "title", "FP"),
        ("extra[0]", "url", "FP"),
    ]
    assert r.pages is not None
    assert r.pages[0].zero_touch is False


def test_empty_checked_listing_scores() -> None:
    # A checked listing with no rows says the page lists nothing: it counts, and engine rows on it are FP.
    empty = listing_case([], [], page_id="l1")
    with_rows = listing_case([], [{"title": published("X")}], page_id="l2")

    r = report(empty, with_rows)

    assert r.n_pages == 2
    assert judgments(r) == [("page", "next_page", "TN"), ("page", "next_page", "TN"), ("extra[0]", "title", "FP")]
    assert r.by_category == {"job_board": ZeroTouch(zero_touch=0.5, n=2)}


def test_zero_touch_needs_every_required_field_tp() -> None:
    r = report(
        detail_case("p1", EUR_19, published(EUR_19), category="custom_store"),
        detail_case("p2", EUR_19, ABSTAINED, category="custom_store"),
        detail_case("p3", EUR_19, published(EUR_19), category="mixed"),
    )

    assert r.by_category == {"custom_store": ZeroTouch(zero_touch=0.5, n=2), "mixed": ZeroTouch(zero_touch=1.0, n=1)}


@pytest.mark.parametrize(
    ("sku", "gtin", "zero_touch"),
    [
        (published("S1"), ABSTAINED, True),  # one member TP is enough
        (ABSTAINED, ABSTAINED, False),  # no member published
        (published("S1"), published("G-wrong"), False),  # a wrong member
    ],
)
def test_zero_touch_required_groups(sku: FieldOutput, gtin: FieldOutput, zero_touch: bool) -> None:
    schema = SchemaFields(
        name="ids",
        page_kind="detail",
        fields={
            "sku": FieldSpec(type=FieldType.IDENTIFIER, scheme="sku"),
            "gtin": FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin"),
        },
        required_groups=(frozenset({"sku", "gtin"}),),
    )
    case = EvalCase(
        page_id="p1",
        category="mixed",
        schema_def=schema,
        labels=labels({"sku": label("S1"), "gtin": label("G1")}),
        output=PageOutput(block_class="ok", mode="adhoc", fields={"sku": sku, "gtin": gtin}),
    )

    assert report(case).by_category == {"mixed": ZeroTouch(zero_touch=float(zero_touch), n=1)}


def test_acquisition_mix_and_usage_per_mode() -> None:
    r = report(
        detail_case("p1", EUR_19, published(EUR_19), llm_calls=2),
        detail_case("p2", EUR_19, None, block_class="blocked"),
        detail_case("p3", EUR_19, published(EUR_19), mode="config"),
    )

    assert r.acquisition == {"custom_store": {"blocked": 1, "ok": 2}}
    assert r.usage == {
        "adhoc": Usage(llm_calls_per_1k_pages=1000.0, n=2),
        "config": Usage(llm_calls_per_1k_pages=0.0, n=1),
    }


def test_report_round_trips_through_json() -> None:
    r = report(detail_case("p1", EUR_19, published(EUR_19)), listing_case([], []))

    assert Report.model_validate_json(r.model_dump_json()) == r


# Per source kind (SPEC-05 §4.11): every kind that offered a kept value is scored, whether or not it won.

TITLED = SchemaFields(
    name="titled",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT),
        "images": FieldSpec(type=FieldType.LIST, item=FieldSpec(type=FieldType.IMAGE_URL)),
    },
)


def titled_case(page_id: str, title: JsonValue, out: dict[str, Any], field: str = "title") -> EvalCase:
    return EvalCase.model_validate(
        {
            "page_id": page_id,
            "category": "mixed",
            "schema_def": TITLED,
            "labels": labels({"title": label(title), "images": label(None)}),
            "output": {"block_class": "ok", "mode": "adhoc", "fields": {field: out}},
        }
    )


def test_each_kind_that_offered_a_value_is_scored_against_the_label() -> None:
    won = titled_case("p1", "A", {**published("A").model_dump(), "offered": {"jsonld": ["A"], "og": ["B"]}})
    split = titled_case("p2", "A", {"status": "conflict", "offered": {"jsonld": ["A", "C"]}})
    absent = titled_case("p3", None, {"status": "missing", "offered": {"og": ["X"]}})
    unlabeled = titled_case("p4", "A", {"status": "missing"})

    r = report(won, split, absent, unlabeled)

    # Three title labels hold a value: coverage is a kind's right values over them.
    assert r.by_source == {
        "text|jsonld": SourceMetrics(precision=0.5, coverage=1 / 3, n=2),
        "text|og": SourceMetrics(precision=0.0, coverage=0.0, n=2),
    }
    assert r.pages is not None
    assert [j.sources for j in r.pages[0].judgments if j.field == "title"] == [{"jsonld": "TP", "og": "FP"}]


def test_a_list_is_measured_as_its_item_type() -> None:
    # A list ranks by its item type's order (SPEC-05 §4.7), so its kinds are measured under that type.
    case = titled_case("p1", "A", {"status": "missing", "offered": {"og": [["u"]]}}, field="images")

    assert report(case).by_source == {"image_url|og": SourceMetrics(precision=0.0, coverage=None, n=1)}


def test_an_unmatched_rows_offering_kinds_are_false() -> None:
    row = {
        "url": FieldOutput.model_validate(
            {
                **published("https://shop.example.test/x").model_dump(),
                "offered": {"jsonld": ["https://shop.example.test/x"]},
            }
        )
    }
    case = listing_case([], [row])

    assert report(case).by_source == {"url|jsonld": SourceMetrics(precision=0.0, coverage=None, n=1)}
