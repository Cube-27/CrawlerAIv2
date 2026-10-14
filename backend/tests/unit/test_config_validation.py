"""Held-out validation and corroboration (SPEC-08 §4.7): a field is kept only if both executors reproduce the engine's
published value on every held-out page and every match is valid; kept fields are `corroborated` by the §8.3 step 4
thresholds; listings need 3 rows on every page."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.model import ExtractionConfigIR, XPathStep
from crawlerai.config_ir.validation import Facts, HeldOutPage, Validated, corroboration, validate
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
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic", "version": 1}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields or {"title": TEXT}})


def _ir(
    fields: dict[str, Any], *, status: str = "uncorroborated", listing: dict[str, Any] | None = None
) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "version": 1},
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


def test_fewer_than_three_held_out_pages_activate_nothing() -> None:
    result = _validate(_ir({"title": TITLE}), [_titled(0), _titled(1)])
    assert result.ir is None
    assert (result.report.refused, result.report.fields) == ("too_few_held_out", {})


@pytest.mark.parametrize(
    ("third", "dropped"),
    [
        # §4.3: a single-valued field that matches twice is invalid, so it fails "exactly one match".
        ("<h1 id='t'>Item 2</h1><h1 id='t'>Item 2</h1>", "invalid"),
        ("<h2>Item 2</h2>", "no_match"),
        ("<h1 id='t'>Other</h1>", "not_reproduced"),
    ],
)
def test_a_field_failing_a_check_on_one_page_is_dropped(third: str, dropped: str) -> None:
    pages = [_titled(0), _titled(1), _detail(third, {"title": "Item 2"})]
    result = _validate(_ir({"title": {"xpath": "//h1[@id='t']"}}), pages)
    assert result.ir is None
    assert result.report.refused == "no_field_kept"
    assert _report(result)["status"] is None
    assert _report(result)["dropped"] == dropped


def test_an_invalid_match_where_nothing_was_published_still_drops_the_field() -> None:
    pages = [_titled(0), _titled(1), _detail("<h1 id='t'>A</h1><h1 id='t'>B</h1>")]
    result = _validate(_ir({"title": {"xpath": "//h1[@id='t']"}}), pages)
    assert _report(result)["dropped"] == "invalid"


def test_a_match_where_nothing_was_published_counts_toward_yield_only() -> None:
    pages = [_titled(0), _titled(1), _detail("<h1 id='t'>Extra</h1>"), _detail("<p>none</p>")]
    report = _report(_validate(_ir({"title": TITLE}), pages))
    assert (report["matched"], report["published"], report["yield"], report["status"]) == (3, 2, 0.75, "uncorroborated")


def test_a_field_published_on_no_held_out_page_is_dropped() -> None:
    pages = [_detail("<h1 id='t'>Item</h1>") for _ in range(3)]
    assert _report(_validate(_ir({"title": TITLE}), pages))["dropped"] == "never_published"


def test_a_value_only_the_engine_executor_reads_is_not_reproduced() -> None:
    # The release executor matches `when_type` without subtypes (D-0528); the engine reads the subtype as a Product.
    def page(n: int) -> HeldOutPage:
        node = json.dumps({"@context": "https://schema.org", "@type": "IndividualProduct", "name": f"Item {n}"})
        return _detail(f"<script type='application/ld+json'>{node}</script>", {"title": f"Item {n}"})

    result = _validate(_ir({"title": {"jsonld": "$['name']", "when_type": "Product"}}), [page(n) for n in range(3)])
    assert _report(result)["dropped"] == "not_reproduced"


def test_only_kept_fields_remain_in_the_validated_config() -> None:
    schema = _schema(title=TEXT, link=URL)
    pages = [_detail(f"<h1 id='t'>Item {n}</h1><a href='/p/{n}'>x</a>", {"title": f"Item {n}"}) for n in range(3)]
    result = _validate(_ir({"title": TITLE, "link": {"xpath": "//a/@href"}}), pages, schema)
    assert result.ir is not None
    assert list(result.ir.fields) == ["title"]
    assert _report(result, "link")["dropped"] == "never_published"


@pytest.mark.parametrize(
    ("references", "status", "corroborated_on"),
    [
        (["Item 0", "Item 1"], "uncorroborated", 2),  # 2 comparable pages: below the floor of 3
        (["Item 0", "Item 1", "Item 2"], "corroborated", 3),
        (["Item 0", "Item 1", "Other"], "uncorroborated", 2),  # fewer than 10: every comparable page must agree
    ],
)
def test_corroboration_compares_the_config_with_structured_values(
    references: list[str], status: str, corroborated_on: int
) -> None:
    pages = [_titled(n, reference=reference) for n, reference in enumerate(references)] + [_titled(9)]
    report = _report(_validate(_ir({"title": TITLE}), pages))
    assert (report["status"], report["comparable"], report["corroborated_on"]) == (
        status,
        len(references),
        corroborated_on,
    )


@pytest.mark.parametrize(
    ("comparable", "agreeing", "status"),
    [
        (2, 2, "uncorroborated"),
        (3, 3, "corroborated"),
        (9, 9, "corroborated"),
        (9, 8, "uncorroborated"),
        (10, 9, "corroborated"),
        (10, 8, "uncorroborated"),
        (100, 90, "corroborated"),
        (100, 89, "uncorroborated"),
    ],
)
def test_corroboration_thresholds(comparable: int, agreeing: int, status: str) -> None:
    assert corroboration(comparable, agreeing) == status


def test_an_operator_field_keeps_its_status() -> None:
    pages = [_titled(n, reference=f"Item {n}") for n in range(3)]
    result = _validate(_ir({"title": TITLE}, status="operator"), pages)
    assert result.ir is not None
    assert result.ir.fields["title"].status == "operator"


def test_a_field_the_schema_lacks_is_dropped() -> None:
    result = _validate(_ir({"title": TITLE, "gone": TITLE}), [_titled(n) for n in range(3)])
    assert _report(result, "gone")["dropped"] == "not_in_schema"
    assert result.ir is not None
    assert list(result.ir.fields) == ["title"]


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
    assert result.ir.listing.next is not None
    listing = result.report.model_dump(mode="json")["listing"]
    assert (listing["rows_ok"], listing["fields"]["title"]["reproduced"], listing["next"]["reproduced"]) == (3, 3, 3)


def test_a_page_with_fewer_than_three_rows_drops_the_listing() -> None:
    result = _validate_listing([_listing(["A", "B", "C"]), _listing(["A", "B", "C"]), _listing(["A", "B"])])
    assert result.ir is None
    listing = result.report.model_dump(mode="json")["listing"]
    assert (listing["rows_ok"], listing["dropped"]) == (2, "too_few_rows")
    assert (listing["fields"]["title"]["status"], listing["fields"]["title"]["dropped"]) == (None, "too_few_rows")


def test_row_values_are_compared_with_the_engine_rows_in_order() -> None:
    swapped = _listing(["A", "B", "C"], published=["B", "A", "C"])
    result = _validate_listing([_listing(["A", "B", "C"]), _listing(["A", "B", "C"]), swapped])
    listing = result.report.model_dump(mode="json")["listing"]
    assert (listing["fields"]["title"]["reproduced"], listing["fields"]["title"]["dropped"]) == (2, "not_reproduced")


def test_rows_are_not_reproduced_when_the_config_finds_a_row_the_engine_did_not() -> None:
    extra = _listing(["A", "B", "C", "D"], published=["A", "B", "C"])
    result = _validate_listing([_listing(["A", "B", "C"]), _listing(["A", "B", "C"]), extra])
    listing = result.report.model_dump(mode="json")["listing"]
    assert (listing["fields"]["title"]["reproduced"], listing["fields"]["title"]["dropped"]) == (2, "not_reproduced")


def test_a_next_step_that_is_not_reproduced_is_dropped_and_the_rows_stay() -> None:
    pages = [_listing(["A", "B", "C"]), _listing(["A", "B", "C"]), _listing(["A", "B", "C"], next_href="/p/9")]
    result = _validate_listing(pages)
    assert result.ir is not None
    assert result.ir.listing is not None
    assert result.ir.listing.next is None
    assert list(result.ir.listing.fields) == ["title"]


def test_the_validated_config_is_a_valid_ir_document() -> None:
    result = _validate(_ir({"title": TITLE}), [_titled(n) for n in range(3)])
    assert result.ir is not None
    document = result.ir.model_dump(mode="json", by_alias=True)
    assert ExtractionConfigIR.model_validate(document) == result.ir
    assert document["fields"]["title"]["steps"] == [XPathStep.model_validate(TITLE).model_dump(mode="json")]
