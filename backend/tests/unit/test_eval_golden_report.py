"""The golden-set report's phase 0 rules (evaluation spec, "Row matching", "Label re-keying", "Presence, disagreement
kinds and cost"): rows matched by URL without the page's session parameters, then by path and text, then by text;
stale label rows counted apart; the capture's showing a value splits misses and extra rows; tokens and USD per correct
field. Every value is synthetic (RFC 2606 hosts, C3, C9)."""

from collections.abc import Collection
from typing import Any

from crawlerai.eval.labels import Labels
from crawlerai.eval.metrics import (
    CostMetrics,
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


def test_each_source_kind_offering_the_url_with_the_session_parameter_is_scored_as_the_published_value() -> None:
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1?sid=abc"}])
    url = FieldOutput(
        status="published", value=f"{SHOP}/p/1", evidence="structured", offered={"jsonld": (f"{SHOP}/p/1?sid=abc",)}
    )
    row = {**_row("Item 1", None), "url": url}
    output = PageOutput(block_class="ok", mode="adhoc", rows=(row,), session_params={"url": ("sid",)})

    report = _report(labels, output)

    assert report.by_source["url|jsonld"].precision == 1.0


def test_only_the_fields_the_engine_keyed_drop_the_session_parameters() -> None:
    schema = LISTING.model_copy(update={"fields": {**LISTING.fields, "seller": FieldSpec(type=FieldType.URL)}})
    seller = f"{SHOP}/s/1?sid=abc"
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1?sid=abc", "seller": seller}])
    row = {
        **_row("Item 1", f"{SHOP}/p/1"),
        "seller": FieldOutput(status="published", value=seller, evidence="structured"),
    }
    output = PageOutput(block_class="ok", mode="adhoc", rows=(row,), session_params={"url": ("sid",)})
    case = EvalCase(page_id="p1", category="custom_store", schema_def=schema, labels=labels, output=output)

    report = build_report([case], "dev", "e1", "abc", frozenset({"draft"}))

    assert report.by_field["synthetic_listing|seller"].precision == 1.0
    assert report.by_field["synthetic_listing|url"].precision == 1.0


def test_a_row_left_unmatched_by_url_matches_by_path_and_text() -> None:
    # The label's query differs (a parameter the engine kept), but path and title agree: one item, its url field FP.
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1?ref=x"}])
    output = PageOutput(block_class="ok", mode="adhoc", rows=(_row("Item 1", f"{SHOP}/p/1?ref=y"),))

    report = _report(labels, output)

    assert _cell(report, "text").coverage == 1.0
    assert report.disagreements == {"synthetic_listing|url": {"FP|wrong_value": 1}}


def test_a_label_row_without_a_url_matches_by_its_text() -> None:
    labels = _labels([{"title": "Item 2"}])
    output = PageOutput(block_class="ok", mode="adhoc", rows=(_row("Item 1", f"{SHOP}/p/1"), _row("Item 2", None)))

    report = _report(labels, output)

    assert _cell(report, "text").coverage == 1.0
    assert report.disagreements == {
        "synthetic_listing|title": {"FP|extra_row": 1},
        "synthetic_listing|url": {"FP|extra_row": 1},
    }


def test_an_unmatched_stale_label_row_is_counted_apart_and_never_missed() -> None:
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1"}, {"title": "Gone", "url": f"{SHOP}/p/9"}], {1})
    output = PageOutput(block_class="ok", mode="adhoc", rows=(_row("Item 1", f"{SHOP}/p/1"),))

    report = _report(labels, output)

    assert report.label_stale == {"synthetic_listing": 1}
    assert (_cell(report, "text").coverage, _cell(report, "url").coverage) == (1.0, 1.0)


def test_a_stale_label_row_the_engine_matches_is_judged() -> None:
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1"}], {0})
    output = PageOutput(block_class="ok", mode="adhoc", rows=(_row("Item 1", f"{SHOP}/p/1"),))

    report = _report(labels, output)

    assert report.label_stale == {}
    assert _cell(report, "url").n == 1


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


def test_tokens_and_usd_per_correct_field() -> None:
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1"}])
    rows = (_row("Item 1", f"{SHOP}/p/1"),)
    output = PageOutput(
        block_class="ok", mode="adhoc", rows=rows, llm_calls=1, tokens_in=300, tokens_out=100, llm_usd=0.0002
    )

    cost = _report(labels, output).cost

    assert cost == CostMetrics(
        llm_calls=1, tokens_in=300, tokens_out=100, usd=0.0002, tp=2, tokens_per_tp=200.0, usd_per_tp=0.0001
    )


def test_an_unpriced_call_leaves_the_usd_unknown() -> None:
    labels = _labels([{"title": "Item 1", "url": f"{SHOP}/p/1"}])
    output = PageOutput(block_class="ok", mode="adhoc", rows=(_row("Item 1", f"{SHOP}/p/1"),), llm_usd=None)

    cost = _report(labels, output).cost

    assert cost is not None
    assert (cost.usd, cost.usd_per_tp) == (None, None)
