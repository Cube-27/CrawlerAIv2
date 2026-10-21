"""Held-out validation and corroboration (learning-configs spec): a field is kept only if both executors reproduce the
engine's published value on every held-out page and every match is valid; kept fields are `corroborated` by the §8.3
step 4 thresholds; listings need 3 rows on every page."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.model import ExtractionConfigIR, XPathStep
from crawlerai.config_ir.validation import (
    Facts,
    HeldOutPage,
    Validated,
    validate,
)
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")

TEXT = FieldSpec(type=FieldType.TEXT, description="d")
URL = FieldSpec(type=FieldType.URL, description="d")
TITLE = {"xpath": "normalize-space(//h1[@id='t'])"}


def _schema(page_kind: str = "detail", **fields: FieldSpec) -> SchemaDef:
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic"}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields or {"title": TEXT}})


def _ir(
    fields: dict[str, Any], *, status: str = "uncorroborated", listing: dict[str, Any] | None = None
) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": "detail" if listing is None else "listing",
            "fetch": {"method": "http"},
            "fields": {name: {"steps": [step], "status": status} for name, step in fields.items()},
            "listing": listing,
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )


def _detail(body: str, published: dict[str, Any] | None = None, **references: list[Any]) -> HeldOutPage:
    return HeldOutPage(
        capture_id=CaptureId(uuid7()),
        page=ParsedPage(f"<html><body>{body}</body></html>"),
        ctx=CTX,
        facts=Facts(published=published or {}, references=references),
    )


def _titled(n: int, *, reference: str | None = None) -> HeldOutPage:
    title = f"Item {n}"
    return _detail(f"<h1 id='t'> {title} </h1>", {"title": title}, **({"title": [reference]} if reference else {}))


def _validate(ir: ExtractionConfigIR, pages: list[HeldOutPage], schema: SchemaDef | None = None) -> Validated:
    return validate(ir, schema or _schema(), pages, VOCABULARY)


def _report(result: Validated, name: str = "title") -> dict[str, Any]:
    report: dict[str, Any] = result.report.model_dump(mode="json")["fields"][name]
    return report


def test_a_field_reproduced_on_every_held_out_page_is_kept_with_its_yield_and_validity() -> None:
    pages = [_titled(n) for n in range(3)]
    result = _validate(_ir({"title": TITLE}), pages)
    assert result.ir is not None
    assert result.ir.fields["title"].status == "uncorroborated"
    assert (result.ir.fields["title"].yield_, result.ir.fields["title"].validity) == (1.0, 1.0)
    assert result.ir.provenance.validated_on == [page.capture_id for page in pages]
    assert _report(result) == {
        "pages": 3,
        "matched": 3,
        "valid": 3,
        "published": 3,
        "reproduced": 3,
        "comparable": 0,
        "corroborated_on": 0,
        "status": "uncorroborated",
        "yield": 1.0,
        "validity": 1.0,
        "dropped": None,
    }
    assert result.report.refused is None


# --- listings -------------------------------------------------------------------------------------------------------

LISTING_SCHEMA = {"title": TEXT, "next_page_url": URL}
LISTING = {
    "row": {"css": "ul > li"},
    "fields": {"title": {"steps": [{"xpath": "normalize-space(em)"}], "status": "uncorroborated"}},
    "next": {"xpath": "//a[@rel='next']/@href", "post": [{"absolutize_url": {}}]},
}


def _listing(titles: list[str], *, next_href: str | None = "/p/2", published: list[str] | None = None) -> HeldOutPage:
    rows = "".join(f"<li><em>{title}</em></li>" for title in titles)
    link = "" if next_href is None else f"<a rel='next' href='{next_href}'>n</a>"
    facts = Facts(published={"next_page_url": "https://shop.example.test/p/2"} if next_href else {})
    return HeldOutPage(
        capture_id=CaptureId(uuid7()),
        page=ParsedPage(f"<html><body><ul>{rows}</ul>{link}</body></html>"),
        ctx=CTX,
        facts=facts,
        rows=[Facts(published={"title": title}) for title in (titles if published is None else published)],
    )


def _validate_listing(pages: list[HeldOutPage]) -> Validated:
    return validate(_ir({}, listing=LISTING), _schema("listing", **LISTING_SCHEMA), pages, VOCABULARY)


def test_a_listing_with_three_rows_on_every_page_keeps_its_row_fields_and_next() -> None:
    result = _validate_listing([_listing(["A", "B", "C"]) for _ in range(3)])
    assert result.ir is not None
    assert result.ir.listing is not None
    assert result.ir.listing.fields["title"].status == "uncorroborated"
    assert result.ir.listing.next == XPathStep.model_validate(LISTING["next"])
    listing = result.report.model_dump(mode="json")["listing"]
    assert (listing["rows_ok"], listing["fields"]["title"]["reproduced"], listing["next"]["reproduced"]) == (3, 3, 3)


def test_a_next_step_that_is_not_reproduced_is_dropped_and_the_rows_stay() -> None:
    pages = [_listing(["A", "B", "C"]), _listing(["A", "B", "C"]), _listing(["A", "B", "C"], next_href="/p/9")]
    result = _validate_listing(pages)
    assert result.ir is not None
    assert result.ir.listing is not None
    assert result.ir.listing.next is None
    assert list(result.ir.listing.fields) == ["title"]


# --- fields learning gave no steps ---
