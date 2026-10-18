"""The golden-set report's phase 0 rules (evaluation spec, "Row matching", "Label re-keying", "Presence, disagreement
kinds and cost"): rows matched by URL without the page's session parameters, then by path and text, then by text;
stale label rows counted apart; the capture's showing a value splits misses and extra rows; tokens and USD per correct
field. Every value is synthetic (RFC 2606 hosts, C3, C9)."""

from collections.abc import Collection
from typing import Any

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import (
    EvalCase,
    FieldMetrics,
    FieldOutput,
    PageOutput,
    PresenceMetrics,
    Report,
    SchemaFields,
    build_report,
)
from crawlerai.schemas.types import FieldSpec, FieldType

LISTING = SchemaFields(
    name="synthetic_listing",
    page_kind="listing",
    fields={"title": FieldSpec(type=FieldType.TEXT), "url": FieldSpec(type=FieldType.URL)},
)
SHOP = "https://shop.example.test"


def _labels(rows: list[dict[str, Any]], stale: Collection[int] = ()) -> Labels:
    return Labels.model_validate(
        {
            "label_version": 1,
            "status": "draft",
            "prefill_source": "none",
            "fields": {},
            "rows": [
                {"fields": {k: {"value": v, "absent": False} for k, v in r.items()}, "stale": i in stale}
                for i, r in enumerate(rows)
            ],
        }
    )


def _row(title: str, url: str | None) -> dict[str, FieldOutput]:
    row = {"title": FieldOutput(status="published", value=title, evidence="structured")}
    if url is not None:
        row["url"] = FieldOutput(status="published", value=url, evidence="structured")
    return row


def _report(labels: Labels, output: PageOutput, document: str | None = None) -> Report:
    case = EvalCase(
        page_id="p1", category="custom_store", schema_def=LISTING, labels=labels, output=output, document=document
    )
    return build_report([case], "dev", "e1", "abc", frozenset({"draft", "checked"}))


def _cell(report: Report, type_: str) -> FieldMetrics:
    return report.by_field_type[type_]


def test_a_label_url_matches_once_the_page_s_session_parameters_are_dropped() -> None:
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1?sid=abc"}])
    output = PageOutput(
        block_class="ok", mode="adhoc", rows=(_row("Item 1", f"{SHOP}/p/1"),), session_params={"url": ("sid",)}
    )

    report = _report(labels, output)

    assert (_cell(report, "url").precision, _cell(report, "url").coverage) == (1.0, 1.0)


def test_rows_match_by_the_schema_s_item_url_field_whatever_its_name() -> None:
    schema = SchemaFields(
        name="synthetic_listing",
        page_kind="listing",
        fields={
            "title": FieldSpec(type=FieldType.TEXT),
            "link": FieldSpec(type=FieldType.URL, schema_org="Product.url"),
        },
    )
    # Two items share a title, so only their links tell them apart; the engine lists them in the other order.
    labels = _labels(
        [{"title": "Item", "link": f"{SHOP}/p/1?sid=abc"}, {"title": "Item", "link": f"{SHOP}/p/2?sid=abc"}]
    )
    rows = tuple(
        {**_row("Item", None), "link": FieldOutput(status="published", value=f"{SHOP}/p/{n}", evidence="structured")}
        for n in (2, 1)
    )
    output = PageOutput(block_class="ok", mode="adhoc", rows=rows, session_params={"link": ("sid",)})
    case = EvalCase(page_id="p1", category="custom_store", schema_def=schema, labels=labels, output=output)

    report = build_report([case], "dev", "e1", "abc", frozenset({"draft"}))

    assert report.by_field["synthetic_listing|link"].precision == 1.0
    assert report.by_field["synthetic_listing|link"].coverage == 1.0


def test_the_capture_splits_misses_and_extra_rows_and_gives_the_ceiling() -> None:
    document = '<ul><li><a href="/p/1">Item 1</a></li><li><a href="/p/3">Item <b>3</b></a></li></ul>'
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1"}, {"title": "Item 2", "url": f"{SHOP}/p/2"}])
    output = PageOutput(block_class="ok", mode="adhoc", rows=(_row("Item 3", f"{SHOP}/p/3"), _row("Ghost", None)))

    report = _report(labels, output, document)

    assert report.disagreements == {
        "synthetic_listing|title": {
            "FN|absent": 1,
            "FN|unread": 1,
            "FP|extra_row:not_on_page": 1,
            "FP|extra_row:on_page": 1,
        },
        "synthetic_listing|url": {"FN|absent": 1, "FN|unread": 1, "FP|extra_row:on_page": 1},
    }
    assert report.presence["text"] == PresenceMetrics(present=1, absent=1, unknown=0, ceiling=0.5)
