"""Metrics and the aggregate report (evaluation spec): each cell of the §4.6 table from hand-built label/output
pairs, listing rows matched by url, zero-touch, acquisition, usage, and min-cell suppression."""

from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import (
    EvalCase,
    FieldOutput,
    PageOutput,
    Report,
    SchemaFields,
    ZeroTouch,
    build_report,
)
from crawlerai.schemas.types import FieldSpec, FieldType

EUR_19: JsonValue = {"amount": "19.90", "currency": "EUR"}
EUR_24: JsonValue = {"amount": "24.90", "currency": "EUR"}

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


def report(*cases: EvalCase) -> Report:
    return build_report(cases, "dev", engine_version="e1", git_sha="abc")


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


# Per source kind (extraction spec): every kind that offered a kept value is scored, whether or not it won.
