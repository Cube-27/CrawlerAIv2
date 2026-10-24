"""The release check: the release executor runs an exported config on the
held-out pages, and a field it does not reproduce on every page with an engine value while there are fewer than 10,
and on at least 95% from 10 on, is marked `manual`."""

from datetime import UTC, datetime
from typing import Any

from snowcrawl.config_ir.model import ExtractionConfigIR
from snowcrawl.config_ir.release_check import ReleaseField, ReleaseReport, release_check
from snowcrawl.config_ir.validation import Facts, HeldOutPage
from snowcrawl.content.page import ParsedPage
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import CaptureId, SchemaId
from snowcrawl.normalize.base import Context
from snowcrawl.schemas.types import FieldType, SchemaDef

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
