"""The dev report over draft labels (D-1461) and its triage cells: drafts scored only when asked and only on dev,
their unlabeled fields unscored, long_text scored by similarity (D-1462), the engine's reasons and LLM calls without a
reply carried to the report (D-1464), per page kind cells and the disagreement counts."""

from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import (
    EvalCase,
    FieldMetrics,
    FieldOutput,
    PageOutput,
    Report,
    SchemaFields,
    build_report,
)
from crawlerai.eval.scoring import LONG_TEXT_MIN_SIMILARITY
from crawlerai.schemas.types import FieldSpec, FieldType

EUR_19: JsonValue = {"amount": "19.90", "currency": "EUR"}
EUR_24: JsonValue = {"amount": "24.90", "currency": "EUR"}
DESCRIPTION = " ".join(f"word{chr(97 + i % 26)}{chr(97 + i // 26)}" for i in range(100))

DETAIL = SchemaFields(
    name="synthetic_detail",
    page_kind="detail",
    fields={
        "price": FieldSpec(type=FieldType.MONEY),
        "brand": FieldSpec(type=FieldType.TEXT),
        "description": FieldSpec(type=FieldType.LONG_TEXT),
    },
    required=frozenset({"price"}),
)
LISTING = SchemaFields(
    name="synthetic_listing",
    page_kind="listing",
    fields={"title": FieldSpec(type=FieldType.TEXT), "url": FieldSpec(type=FieldType.URL)},
)


def value(v: JsonValue) -> dict[str, Any]:
    return {"value": v, "absent": False}


def draft(fields: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> Labels:
    # As an import stores it: no labeler, fields the file did not give left out.
    return Labels.model_validate(
        {
            "label_version": 1,
            "status": "draft",
            "prefill_source": "none",
            "fields": fields,
            "rows": [{"fields": r} for r in rows or []],
        }
    )


def published(v: JsonValue) -> FieldOutput:
    return FieldOutput(status="published", value=v, evidence="structured")


def case(
    page_id: str, labels: Labels, fields: dict[str, FieldOutput], schema: SchemaFields = DETAIL, **output: Any
) -> EvalCase:
    return EvalCase(
        page_id=page_id,
        category="custom_store",
        schema_def=schema,
        labels=labels,
        output=PageOutput.model_validate({"block_class": "ok", "mode": "adhoc", "fields": fields, **output}),
    )


def dev_report(*cases: EvalCase, statuses: frozenset[Any] = frozenset({"draft", "checked"})) -> Report:
    return build_report(cases, "dev", engine_version="e1", git_sha="abc", statuses=statuses)


def cell(table: dict[str, Any], key: str) -> FieldMetrics:
    found = table[key]
    assert isinstance(found, FieldMetrics)
    return found


def test_drafts_are_not_scored_by_default() -> None:
    r = build_report([case("p1", draft({"price": value(EUR_19)}), {"price": published(EUR_19)})], "dev", "e1", "abc")
    assert (r.n_pages, r.by_field_type, r.label_statuses) == (0, {}, ["checked"])


def test_drafts_are_scored_when_asked_and_the_report_says_so() -> None:
    r = dev_report(case("p1", draft({"price": value(EUR_19)}), {"price": published(EUR_19)}))
    assert r.n_pages == 1
    assert r.label_statuses == ["checked", "draft"]
    assert cell(r.by_field_type, "money").precision == 1.0
    assert r.pages is not None
    assert r.pages[0].label_status == "draft"


def test_a_field_a_draft_does_not_label_is_not_scored() -> None:
    # The brand is published but unlabeled: a draft claims nothing about it, so it is neither FP nor TN.
    r = dev_report(case("p1", draft({"price": value(EUR_19)}), {"price": published(EUR_19), "brand": published("B")}))
    assert "text" not in r.by_field_type
    assert r.pages is not None
    assert [j.field for j in r.pages[0].judgments] == ["price"]


def reworded(fraction_changed: float) -> str:
    words = DESCRIPTION.split()
    changed = round(len(words) * fraction_changed)
    return "\n".join(["other"] * changed + words[changed:])


@pytest.mark.parametrize(("changed", "cell_"), [(0.0, "TP"), (0.05, "TP"), (0.2, "FP")])
def test_long_text_scores_by_word_overlap(changed: float, cell_: str) -> None:
    # Replacing a fraction f of the words leaves a Dice overlap of 1 - f: 0.95 passes the 0.9 threshold, 0.8 fails.
    assert LONG_TEXT_MIN_SIMILARITY == 0.9
    labels = draft({"description": value(DESCRIPTION)})
    r = dev_report(case("p1", labels, {"description": published(reworded(changed))}))
    assert r.pages is not None
    assert [j.cell for j in r.pages[0].judgments] == [cell_]


def test_text_still_compares_exactly() -> None:
    labels = draft({"brand": value("Brand Name")})
    r = dev_report(case("p1", labels, {"brand": published("brand name")}))
    assert cell(r.by_field_type, "text").precision == 0.0


def test_the_engine_reason_and_unanswered_calls_reach_the_page_detail() -> None:
    missing = FieldOutput(status="missing", reason="llm_unavailable")
    r = dev_report(case("p1", draft({"price": value(EUR_19)}), {"price": missing}, llm_unanswered=1))
    assert r.pages is not None
    [page] = r.pages
    assert page.llm_unanswered == 1
    assert [(j.cell, j.reason) for j in page.judgments] == [("FN", "llm_unavailable")]
    assert r.disagreements == {"synthetic_detail|price": {"FN|declined:llm_unavailable": 1}}


def test_disagreements_count_each_kind_per_field() -> None:
    cases = [
        case("p1", draft({"price": value(EUR_19)}), {"price": published(EUR_24)}),
        case("p2", draft({"price": value(EUR_19)}), {}),
        case("p3", draft({"price": {"value": None, "absent": True}}), {"price": published(EUR_24)}),
        case("p4", draft({"price": value(EUR_19)}), {"price": published(EUR_19)}),
        case(
            "p5",
            draft({}, rows=[{"url": value("https://shop.example.com/a")}]),
            {},
            schema=LISTING,
            rows=[{"url": published("https://shop.example.com/b")}],
        ),
    ]
    assert dev_report(*cases).disagreements == {
        "synthetic_detail|price": {"FN|not_output": 1, "FP|on_absent": 1, "FP|wrong_value": 1},
        "synthetic_listing|url": {"FN|not_output": 1, "FP|extra_row": 1},
    }


def test_cells_per_page_kind_split_each_field_type() -> None:
    cases = [
        case("p1", draft({"brand": value("A")}), {"brand": published("A")}),
        case(
            "p2",
            draft({}, rows=[{"title": value("T"), "url": value("https://shop.example.com/a")}]),
            {},
            schema=LISTING,
            rows=[{"title": published("T"), "url": published("https://shop.example.com/a")}],
        ),
    ]
    r = dev_report(*cases)
    assert sorted(r.by_page_kind) == ["detail|text", "listing|text", "listing|url"]
    assert cell(r.by_page_kind, "detail|text").n == 1
    assert cell(r.by_page_kind, "listing|text").n == 1


def test_the_report_counts_page_kind_cells_and_disagreements() -> None:
    labels = Labels.model_validate(
        {
            "label_version": 1,
            "status": "checked",
            "labeler": "a",
            "checker": "b",
            "fields": {
                "price": value(EUR_19),
                "brand": {"value": None, "absent": True},
                "description": {"value": None, "absent": True},
            },
        }
    )
    dev = build_report([case(f"p{n}", labels, {}) for n in range(12)], "dev", "e1", "abc")
    assert dev.disagreements == {"synthetic_detail|price": {"FN|not_output": 12}}
    assert sorted(dev.by_page_kind) == ["detail|long_text", "detail|money", "detail|text"]
