"""Row-mapped field metrics (SPEC-13 §4.10): engine rows matched to label rows by key, `list.<type>` cells, row
precision and recall, wrong product from `distractor_keys`, and their suppression in an aggregate (INV-25)."""

from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import (
    MIN_CELL,
    EvalCase,
    FieldMetrics,
    FieldOutput,
    PageOutput,
    PrecisionMetrics,
    Report,
    RowMetrics,
    SchemaFields,
    Suppressed,
    ZeroTouch,
    build_report,
    export_aggregate,
)
from crawlerai.schemas.types import FieldSpec, FieldType

# A row sub-field's cell (SPEC-13 §4.10), built from its type: the literal would read as a hostname to the C3 scan.
LIST_MONEY = f"list.{FieldType.MONEY.value}"

VARIANTS = FieldSpec.model_validate(
    {
        "type": "list",
        "schema_org": "ProductGroup.hasVariant|Product.offers",
        "key": ["sku", "url"],
        "item": {
            "type": "object",
            "fields": {
                "sku": {"type": "identifier", "scheme": "sku", "schema_org": "Product.sku|Offer.sku"},
                "price": {"type": "money", "schema_org": "Offer.price+priceCurrency"},
                "url": {"type": "url", "schema_org": "Product.url|Offer.url"},
            },
        },
    }
)
SCHEMA = SchemaFields(
    name="commerce_detail",
    page_kind="detail",
    fields={"title": FieldSpec.model_validate({"type": "text"}), "variants": VARIANTS},
    required=frozenset({"title"}),
)
TITLE = "Synthetic widget"
PAGE_URL = "https://shop.example.test/p/1"


def sku(value: str) -> JsonValue:
    return {"scheme": "sku", "value": value}


def eur(amount: str) -> JsonValue:
    return {"amount": amount, "currency": "EUR"}


def sub(value: JsonValue) -> dict[str, Any]:
    return {"absent": True} if value is None else {"value": value, "absent": False}


def label_row(code: str | None, amount: str | None = "10.00", url: str | None = None) -> dict[str, Any]:
    fields = {"sku": sku(code) if code else None, "price": eur(amount) if amount else None, "url": url}
    return {"fields": {name: sub(value) for name, value in fields.items()}}


def published(value: JsonValue, evidence: str = "structured") -> FieldOutput:
    return FieldOutput.model_validate({"status": "published", "value": value, "evidence": evidence})


def engine_row(code: str | None, amount: str | None = "10.00", url: str | None = None) -> dict[str, FieldOutput]:
    values = {"sku": sku(code) if code else None, "price": eur(amount) if amount else None, "url": url}
    return {name: published(v) if v is not None else FieldOutput(status="missing") for name, v in values.items()}


def case(
    page_id: str,
    rows: list[dict[str, Any]] | None,
    engine: list[dict[str, FieldOutput]],
    *,
    distractor_keys: list[dict[str, Any]] = (),  # type: ignore[assignment]
    label_version: int = 2,
) -> EvalCase:
    doc: dict[str, Any] = {
        "label_version": label_version,
        "status": "checked",
        "labeler": "labeler-a",
        "checker": "checker-b",
        "fields": {"title": sub(TITLE)},
    }
    if rows is not None:
        variants = {"absent": not rows, "rows": rows, "distractor_keys": list(distractor_keys)}
        doc["lists"] = {"variants": variants}
    items = tuple(engine)
    outputs = {"title": published(TITLE)}
    if items:
        outputs["variants"] = FieldOutput(status="published", value=[], evidence="structured", items=items)
    return EvalCase(
        page_id=page_id,
        category="custom_store",
        schema_def=SCHEMA,
        labels=Labels.model_validate(doc),
        output=PageOutput(block_class="ok", mode="adhoc", fields=outputs),
    )


def report(*cases: EvalCase, split: Any = "dev") -> Report:
    return build_report(cases, split, "0.0.0+cal.0", "a" * 40)


def metrics(cell: object) -> FieldMetrics:
    assert isinstance(cell, FieldMetrics), cell
    return cell


def test_rows_match_by_key_whatever_their_order() -> None:
    r = report(
        case("p1", [label_row("W-11"), label_row("W-12", "12.00")], [engine_row("W-12", "12.00"), engine_row("W-11")])
    )

    identifier, money = metrics(r.by_field_type["list.identifier"]), metrics(r.by_field_type[LIST_MONEY])
    assert (identifier.precision, identifier.coverage, identifier.n) == (1.0, 1.0, 2)
    assert (money.precision, money.n) == (1.0, 2)
    # Both urls are labeled absent and not published: TN.
    assert metrics(r.by_field_type["list.url"]).abstain_rate == 1.0
    assert metrics(r.by_field["commerce_detail|variants.sku"]).n == 2
    assert r.by_bucket[f"{LIST_MONEY}|structured"] == PrecisionMetrics(precision=1.0, n=2)
    assert r.row_matching == RowMetrics(row_precision=1.0, row_recall=1.0, engine_rows=2, n=2)
    # A top-level field's cells are untouched.
    assert metrics(r.by_field_type["text"]).n == 1


def test_an_unmatched_engine_row_is_fp_and_an_unmatched_label_row_fn() -> None:
    r = report(case("p1", [label_row("W-11"), label_row("W-12", "12.00")], [engine_row("W-11"), engine_row("W-13")]))

    identifier = metrics(r.by_field_type["list.identifier"])
    # W-11 matched (TP); W-13 published but unmatched (FP); W-12 labeled but unmatched (FN).
    assert (identifier.precision, identifier.coverage, identifier.n) == (0.5, 0.5, 3)
    # The unmatched label row's url is labeled absent: TN, not FN.
    assert metrics(r.by_field_type["list.url"]).abstain_rate == 1.0
    assert r.row_matching == RowMetrics(row_precision=0.5, row_recall=0.5, engine_rows=2, n=2)


def test_rows_that_disagree_on_a_key_do_not_match() -> None:
    r = report(case("p1", [label_row("W-11", url=f"{PAGE_URL}?v=1")], [engine_row("W-11", url=f"{PAGE_URL}?v=2")]))

    assert r.row_matching == RowMetrics(row_precision=0.0, row_recall=0.0, engine_rows=1, n=1)


@pytest.mark.parametrize(
    ("rows", "engine"),
    [
        # One engine row shares a key with two label rows.
        ([label_row("W-11"), label_row(None, url=PAGE_URL)], [engine_row("W-11", url=PAGE_URL)]),
        # Two engine rows share a key with one label row.
        ([label_row("W-11")], [engine_row("W-11"), engine_row("W-11", "12.00")]),
    ],
)
def test_an_ambiguous_match_counts_as_unmatched(
    rows: list[dict[str, Any]], engine: list[dict[str, FieldOutput]]
) -> None:
    r = report(case("p1", rows, engine))

    matching = r.row_matching
    assert isinstance(matching, RowMetrics)
    assert (matching.row_precision, matching.row_recall) == (0.0, 0.0)


def test_an_engine_row_with_a_distractor_key_is_a_wrong_product() -> None:
    distractor = {"field": "sku", "value": sku("X-7")}

    r = report(case("p1", [label_row("W-11")], [engine_row("W-11"), engine_row("X-7")], distractor_keys=[distractor]))

    assert metrics(r.by_field_type["list.identifier"]).wrong_product == 1
    assert metrics(r.by_field_type[LIST_MONEY]).wrong_product == 0


def test_rows_published_where_the_label_says_absent_are_fp() -> None:
    r = report(case("p1", [], [engine_row("W-11")]))

    assert metrics(r.by_field_type["list.identifier"]).precision == 0.0
    assert r.row_matching == RowMetrics(row_precision=0.0, row_recall=None, engine_rows=1, n=0)


def test_version_1_labels_leave_the_row_field_unscored() -> None:
    r = report(case("p1", None, [engine_row("W-11")], label_version=1))

    assert (list(r.by_field_type), r.row_matching) == (["text"], None)


def test_row_fields_do_not_change_zero_touch() -> None:
    # Zero-touch is about required fields (SPEC-03 §4.6); `variants` is optional, so an extra row leaves it be.
    r = report(case("p1", [label_row("W-11")], [engine_row("W-11"), engine_row("W-13")]))

    assert r.by_category["custom_store"] == ZeroTouch(zero_touch=1.0, n=1)


def test_dev_reports_row_matching_per_field() -> None:
    r = export_aggregate(report(case("p1", [label_row("W-11")], [engine_row("W-11")])))

    assert r.row_matching_by_field == {"commerce_detail|variants": Suppressed(n=1)}


def test_a_hidden_aggregate_suppresses_the_new_cells() -> None:
    # INV-25: cells under MIN_CELL labeled fields are reduced to their n; per-field cells stay in the job.
    small = [case(f"p{i}", [label_row("W-11")], [engine_row("W-11")]) for i in range(MIN_CELL - 1)]
    large = [case(f"q{i}", [label_row("W-11")], [engine_row("W-11")]) for i in range(MIN_CELL)]

    hidden = export_aggregate(report(*small, split="hidden"))
    shown = export_aggregate(report(*large, split="hidden"))

    assert hidden.by_field_type["list.identifier"] == Suppressed(n=MIN_CELL - 1)
    assert hidden.row_matching == Suppressed(n=MIN_CELL - 1)
    assert hidden.row_matching_by_field == {}
    assert isinstance(shown.by_field_type["list.identifier"], FieldMetrics)
    assert shown.row_matching == RowMetrics(row_precision=1.0, row_recall=1.0, engine_rows=MIN_CELL, n=MIN_CELL)
    assert shown.row_matching_by_field == {}
