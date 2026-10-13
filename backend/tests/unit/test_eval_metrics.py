"""Metrics and the aggregate report (SPEC-03 §4.6, §4.7): each cell of the §4.6 table from hand-built label/output
pairs, listing rows matched by url, zero-touch, acquisition, usage, and min-cell suppression."""

import json
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
    Suppressed,
    Usage,
    ZeroTouch,
    build_report,
    export_aggregate,
    generalization_gap,
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


def label(value: JsonValue = None, distractors: tuple[JsonValue, ...] = ()) -> dict[str, Any]:
    return {"value": value, "absent": value is None, "distractors": list(distractors)}


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
    distractors: tuple[JsonValue, ...] = (),
    category: str = "custom_store",
    **output: Any,
) -> EvalCase:
    fields = {"price": price_out} if price_out is not None else {}
    return EvalCase.model_validate(
        {
            "page_id": page_id,
            "category": category,
            "schema_def": DETAIL,
            "labels": labels({"price": label(price_label, distractors), "brand": label(None)}),
            "output": PageOutput.model_validate({"block_class": "ok", "mode": "adhoc", "fields": fields, **output}),
        }
    )


def report(*cases: EvalCase, split: str = "dev") -> Report:
    return build_report(cases, split, engine_version="e1", git_sha="abc")  # type: ignore[arg-type]


def money(r: Report) -> FieldMetrics:
    cell = r.by_field_type["money"]
    assert isinstance(cell, FieldMetrics)
    return cell


def test_tp_published_and_equal() -> None:
    r = report(detail_case("p1", EUR_19, published(EUR_19)))

    assert money(r) == FieldMetrics(
        precision=1.0, coverage=1.0, abstain_rate=0.0, false_publish_on_absent=None, wrong_product=0, n=1
    )


def test_fp_published_and_not_equal() -> None:
    r = report(detail_case("p1", EUR_19, published({"amount": "19.99", "currency": "EUR"})))

    assert money(r) == FieldMetrics(
        precision=0.0, coverage=None, abstain_rate=0.0, false_publish_on_absent=None, wrong_product=0, n=1
    )


def test_fp_absent_published_where_label_absent() -> None:
    r = report(detail_case("p1", None, published(EUR_19)))

    assert money(r) == FieldMetrics(
        precision=0.0, coverage=None, abstain_rate=0.0, false_publish_on_absent=1.0, wrong_product=0, n=1
    )


@pytest.mark.parametrize("status", ["missing", "conflict", "abstained"])
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


def test_wrong_product_is_a_published_distractor() -> None:
    r = report(detail_case("p1", EUR_19, published(EUR_24), distractors=(EUR_24,)))

    assert money(r) == FieldMetrics(
        precision=0.0, coverage=None, abstain_rate=0.0, false_publish_on_absent=None, wrong_product=1, n=1
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


def test_pages_are_kept_for_dev_only() -> None:
    case = detail_case("p1", EUR_19, published(EUR_19))

    assert report(case, split="hidden").pages is None
    assert report(case, split="dev").pages is not None


def test_export_suppresses_cells_under_ten() -> None:
    big = [detail_case(f"p{i:02}", EUR_19, published(EUR_19)) for i in range(10)]
    small = [detail_case(f"q{i}", EUR_19, published(EUR_19), category="mixed") for i in range(3)]

    agg = export_aggregate(report(*big, *small))

    assert agg.pages is None
    assert money(agg).n == 13
    assert agg.by_field_type["text"] == FieldMetrics(
        precision=None, coverage=None, abstain_rate=1.0, false_publish_on_absent=0.0, wrong_product=0, n=13
    )
    assert agg.by_category == {"custom_store": ZeroTouch(zero_touch=1.0, n=10), "mixed": Suppressed(n=3)}
    assert agg.acquisition == {"custom_store": {"ok": 10}, "mixed": Suppressed(n=3)}
    assert agg.by_bucket == {"money|structured": PrecisionMetrics(precision=1.0, n=13)}
    assert agg.by_field["commerce_detail|price"] == money(agg)


def test_export_reduces_a_small_cell_to_its_n() -> None:
    agg = export_aggregate(report(detail_case("p1", EUR_19, published(EUR_19)), split="hidden"))

    as_json = json.loads(agg.model_dump_json())
    assert as_json["by_field"] == {}
    assert as_json["by_field_type"] == {"money": {"n": 1}, "text": {"n": 1}}
    assert as_json["by_bucket"] == {"money|structured": {"n": 1}}
    assert as_json["usage"] == {"adhoc": {"n": 1}}


def test_report_round_trips_through_json() -> None:
    r = report(detail_case("p1", EUR_19, published(EUR_19)), listing_case([], []))

    assert Report.model_validate_json(r.model_dump_json()) == r
    agg = export_aggregate(r)
    assert Report.model_validate_json(agg.model_dump_json()) == agg


def test_generalization_gap_is_dev_minus_fresh() -> None:
    dev = report(*[detail_case(f"p{i}", EUR_19, published(EUR_19)) for i in range(4)])
    fresh = report(
        detail_case("f1", EUR_19, published(EUR_19)),
        detail_case("f2", EUR_19, published(EUR_24)),
        split="fresh",
    )

    assert generalization_gap(dev, fresh) == {"money": 0.5}
    assert generalization_gap(dev, export_aggregate(fresh)) == {}


def _precision_table(cells: dict[str, int]) -> dict[str, PrecisionMetrics | Suppressed]:
    return {k: PrecisionMetrics(precision=1.0, n=n) for k, n in cells.items()}


def _report(split: str = "hidden", **tables: Any) -> Report:
    return Report.model_validate(
        {
            "engine_version": "e1",
            "git_sha": "abc",
            "split": split,
            "n_pages": 50,
            "by_field_type": {},
            "by_field": {},
            "by_bucket": {},
            "by_config_status": {},
            "by_category": {},
            "acquisition": {},
            "usage": {},
            **tables,
        }
    )


def test_a_lone_small_bucket_takes_the_next_smallest_of_its_type_with_it() -> None:
    r = _report(
        by_bucket=_precision_table({"money|structured": 30, "money|agreed": 12, "money|adapter": 4, "text|agreed": 5})
    )

    agg = export_aggregate(r)

    assert agg.by_bucket == {
        "money|structured": PrecisionMetrics(precision=1.0, n=30),
        "money|agreed": Suppressed(n=12),
        "money|adapter": Suppressed(n=4),
        "text|agreed": Suppressed(n=5),
    }


def test_a_lone_small_config_status_takes_the_next_smallest_of_its_type_with_it() -> None:
    r = _report(
        by_config_status=_precision_table({"money|corroborated": 15, "money|operator": 11, "money|suspended": 2})
    )

    agg = export_aggregate(r)

    assert agg.by_config_status == {
        "money|corroborated": PrecisionMetrics(precision=1.0, n=15),
        "money|operator": Suppressed(n=11),
        "money|suspended": Suppressed(n=2),
    }


def test_two_small_cells_need_no_complement() -> None:
    r = _report(by_bucket=_precision_table({"money|structured": 30, "money|agreed": 3, "money|adapter": 4}))

    agg = export_aggregate(r)

    assert agg.by_bucket["money|structured"] == PrecisionMetrics(precision=1.0, n=30)


def test_categories_and_their_acquisition_are_complemented_as_one_group() -> None:
    # Category cells count pages, and together they count every page in `n_pages`.
    r = _report(
        by_category={
            "custom_store": ZeroTouch(zero_touch=0.5, n=25),
            "mixed": ZeroTouch(zero_touch=0.5, n=11),
            "job_board": ZeroTouch(zero_touch=1.0, n=3),
        },
        acquisition={"custom_store": {"ok": 25}, "mixed": {"ok": 10, "shell": 1}, "job_board": {"ok": 3}},
    )

    agg = export_aggregate(r)

    assert agg.by_category == {
        "custom_store": ZeroTouch(zero_touch=0.5, n=25),
        "mixed": Suppressed(n=11),
        "job_board": Suppressed(n=3),
    }
    assert agg.acquisition == {"custom_store": {"ok": 25}, "mixed": Suppressed(n=11), "job_board": Suppressed(n=3)}


def test_usage_modes_are_complemented_as_one_group() -> None:
    r = _report(
        usage={"adhoc": Usage(llm_calls_per_1k_pages=400.0, n=45), "config": Usage(llm_calls_per_1k_pages=0.0, n=5)}
    )

    agg = export_aggregate(r)

    assert agg.usage == {"adhoc": Suppressed(n=45), "config": Suppressed(n=5)}


def test_dev_keeps_primary_suppression_only() -> None:
    r = _report("dev", by_bucket=_precision_table({"money|structured": 30, "money|agreed": 12, "money|adapter": 4}))

    agg = export_aggregate(r)

    assert agg.by_bucket == {
        "money|structured": PrecisionMetrics(precision=1.0, n=30),
        "money|agreed": PrecisionMetrics(precision=1.0, n=12),
        "money|adapter": Suppressed(n=4),
    }


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


def test_per_kind_cells_stay_in_dev() -> None:
    cases = [titled_case(f"p{i:02}", "A", {"status": "missing", "offered": {"og": ["A"]}}) for i in range(12)]

    assert export_aggregate(report(*cases)).by_source == {"text|og": SourceMetrics(precision=1.0, coverage=1.0, n=12)}
    assert report(*cases, split="hidden").by_source == {}
    assert export_aggregate(report(*cases, split="hidden")).by_source == {}


def test_a_small_per_kind_cell_is_reduced_to_its_n_on_dev() -> None:
    case = titled_case("p1", "A", {"status": "missing", "offered": {"og": ["A"]}})

    assert export_aggregate(report(case)).by_source == {"text|og": Suppressed(n=1)}
