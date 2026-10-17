"""The release check (SPEC-08 §4.12, ARCHITECTURE §12.3, INV-20): the release executor runs an exported config on the
held-out pages, and a field it does not reproduce on every page with an engine value while there are fewer than 10,
and on at least 95% from 10 on, is marked `manual`."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.release_check import ReleaseField, ReleaseReport, release_check
from crawlerai.config_ir.validation import Facts, HeldOutPage
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldType, SchemaDef

BASE = "https://shop.example.test/c/1"
CTX = Context(captured_at=datetime(2026, 10, 2, tzinfo=UTC), base_url=BASE, page_url=BASE)
NAME = {"xpath": "normalize-space(//h1)"}
ROWS = {
    "row": {"xpath": "//ol/li"},
    "fields": {"name": {"steps": [{"xpath": "string(b)"}], "status": "corroborated"}},
    "next": {"xpath": "//link[@rel='next']/@href", "post": [{"absolutize_url": {}}]},
}


def _schema(page_kind: str, **fields: FieldType) -> SchemaDef:
    specs = {name: {"type": type_, "description": "d"} for name, type_ in fields.items()}
    return SchemaDef.model_validate(
        {
            "id": SchemaId(uuid7()),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "page_kind": page_kind,
            "fields": specs,
        }
    )


DETAIL = _schema("detail", name=FieldType.TEXT)
LISTING = _schema("listing", name=FieldType.TEXT, next_page_url=FieldType.URL)


def _config(fields: dict[str, dict[str, Any]], listing: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": "listing" if listing else "detail",
            "fetch": {"method": "http"},
            "fields": fields,
            "listing": listing,
            "provenance": {
                "origin": "llm_synth",
                "validated_on": [],
                "learned_at": "2026-10-02T00:00:00Z",
                "engine_version": "test",
            },
        }
    )


def _named(status: str = "uncorroborated", step: dict[str, Any] = NAME) -> ExtractionConfigIR:
    return _config({"name": {"steps": [step], "status": status}})


def _page(body: str, published: dict[str, Any] | None = None, rows: list[str] | None = None) -> HeldOutPage:
    return HeldOutPage(
        capture_id=CaptureId(uuid7()),
        page=ParsedPage(f"<html><head></head><body>{body}</body></html>"),
        ctx=CTX,
        facts=Facts(published=published or {}),
        rows=[Facts(published={"name": name}) for name in rows or []],
    )


def _pages(total: int, differing: int) -> list[HeldOutPage]:
    """`total` pages with an engine value, of which the config reads a different value on `differing`."""
    return [_page(f"<h1>Item {n}</h1>", {"name": f"Item {n}" if n >= differing else "Other"}) for n in range(total)]


def _triple(field: ReleaseField | None) -> tuple[int, int, bool] | None:
    return None if field is None else (field.published, field.reproduced, field.manual)


def _field(report: ReleaseReport, name: str = "name") -> tuple[int, int, bool] | None:
    return _triple(report.fields[name])


def test_a_field_reproduced_on_every_held_out_page_is_released() -> None:
    pages = _pages(3, 0)
    report = release_check(_named(), DETAIL, pages)
    assert _field(report) == (3, 3, False)
    assert report.held_out == [page.capture_id for page in pages]


@pytest.mark.parametrize(
    ("total", "differing", "manual"),
    [
        (9, 1, True),  # fewer than 10 pages: every one must reproduce
        (10, 1, True),  # 90% < 95%
        (19, 1, True),  # 94.7% < 95%
        (20, 1, False),  # 95%
    ],
)
def test_the_small_n_rule(total: int, differing: int, manual: bool) -> None:
    assert _field(release_check(_named(), DETAIL, _pages(total, differing))) == (total, total - differing, manual)


def test_pages_without_an_engine_value_do_not_count() -> None:
    pages = [*_pages(3, 0), _page("<h1>Extra</h1>"), _page("<p>none</p>")]
    assert _field(release_check(_named(), DETAIL, pages)) == (3, 3, False)


def test_a_field_with_no_engine_value_on_any_held_out_page_is_manual() -> None:
    assert _field(release_check(_named(), DETAIL, [_page("<h1>Item</h1>")] * 3)) == (0, 0, True)
    assert _field(release_check(_named(), DETAIL, [])) == (0, 0, True)


def test_a_suspended_field_is_manual() -> None:
    # The release executor does not run a suspended field (§8.3), so it reproduces nothing.
    assert _field(release_check(_named("suspended"), DETAIL, _pages(3, 0))) == (3, 0, True)


def test_a_field_the_schema_lacks_is_manual() -> None:
    config = _config(
        {"name": {"steps": [NAME], "status": "uncorroborated"}, "other": {"steps": [NAME], "status": "operator"}}
    )
    report = release_check(config, DETAIL, _pages(3, 0))
    assert (_field(report), _field(report, "other")) == ((3, 3, False), (0, 0, True))


def test_values_are_compared_after_normalization() -> None:
    # The release executor's raw string is normalized as the engine normalizes it before comparing (SPEC-04 `equal`).
    pages = [_page(f"<h1>  Item\n {n} </h1>", {"name": f"Item {n}"}) for n in range(3)]
    assert _field(release_check(_named(step={"xpath": "//h1"}), DETAIL, pages)) == (3, 3, False)


def test_a_value_only_the_engine_reads_is_manual() -> None:
    # The release executor matches `when_type` without subtypes (D-0528); the engine read the subtype as a Product.
    def page(n: int) -> HeldOutPage:
        node = json.dumps({"@context": "https://schema.org", "@type": "IndividualProduct", "name": f"Item {n}"})
        return _page(f"<script type='application/ld+json'>{node}</script>", {"name": f"Item {n}"})

    config = _named(step={"jsonld": "$['name']", "when_type": "Product"})
    assert _field(release_check(config, DETAIL, [page(n) for n in range(3)])) == (3, 0, True)


def _listing(names: list[str], published: list[str] | None = None, next_href: str = "/c/2") -> HeldOutPage:
    items = "".join(f"<li><b>{name}</b></li>" for name in names)
    return HeldOutPage(
        capture_id=CaptureId(uuid7()),
        page=ParsedPage(f"<html><head><link rel='next' href='{next_href}'></head><body><ol>{items}</ol></body></html>"),
        ctx=CTX,
        facts=Facts(published={"next_page_url": "https://shop.example.test/c/2"}),
        rows=[Facts(published={"name": name}) for name in (names if published is None else published)],
    )


def test_listing_rows_and_next_are_checked_against_the_engine() -> None:
    pages = [_listing(["A", "B", "C"]) for _ in range(3)]
    report = release_check(_config({}, ROWS), LISTING, pages)
    assert report.listing is not None
    assert report.fields == {}
    assert (_triple(report.listing.fields["name"]), _triple(report.listing.next)) == ((3, 3, False), (3, 3, False))


@pytest.mark.parametrize(
    "third",
    [
        _listing(["A", "B", "C"], published=["B", "A", "C"]),  # rows are compared in document order
        _listing(["A", "B", "C", "D"], published=["A", "B", "C"]),  # a row the engine did not publish
    ],
)
def test_a_row_field_not_reproduced_on_one_page_is_manual(third: HeldOutPage) -> None:
    report = release_check(_config({}, ROWS), LISTING, [_listing(["A", "B", "C"]), _listing(["A", "B", "C"]), third])
    assert report.listing is not None
    assert _triple(report.listing.fields["name"]) == (3, 2, True)


def test_a_next_step_not_reproduced_is_manual_and_the_rows_stay_released() -> None:
    pages = [_listing(["A", "B", "C"]), _listing(["A", "B", "C"]), _listing(["A", "B", "C"], next_href="/c/9")]
    report = release_check(_config({}, ROWS), LISTING, pages)
    assert report.listing is not None
    assert (_triple(report.listing.next), _triple(report.listing.fields["name"])) == ((3, 2, True), (3, 3, False))


def test_a_listing_without_next_reports_none() -> None:
    report = release_check(_config({}, {**ROWS, "next": None}), LISTING, [_listing(["A", "B", "C"])] * 3)
    assert report.listing is not None
    assert (report.listing.next, _triple(report.listing.fields["name"])) == (None, (3, 3, False))
