"""Config exports (SPEC-08 §4.11, ARCHITECTURE §12.2): `json` is the IR as stored; `platform_draft` carries each field's
steps in order as XPath, regex or JSONPath, marked `draft`, with the fields the release check fails marked `manual`."""

from datetime import UTC, datetime
from typing import Any

from crawlerai.config_ir.exporters.configs import export_config
from crawlerai.config_ir.model import CssStep, ExtractionConfigIR
from crawlerai.config_ir.release_executor import ReleasePage, release_run
from crawlerai.config_ir.release_rules import release_rules
from crawlerai.config_ir.validation import Facts, HeldOutPage
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

URL = "https://catalog.example.test/list"
CTX = Context(captured_at=datetime(2026, 10, 3, tzinfo=UTC), base_url=URL, page_url=URL)
SCHEMA = SchemaDef.model_validate(
    {
        "id": SchemaId(uuid7()),
        "origin": "user",
        "status": "active",
        "name": "synthetic",
        "page_kind": "listing",
        "fields": {
            "heading": {"type": "text", "description": "d", "scope": "page"},
            "next_page_url": {"type": "url", "description": "d", "scope": "page"},
            "sku": {"type": "text", "description": "d"},
            "link": {"type": "url", "description": "d"},
        },
    }
)
TRIM: list[dict[str, Any]] = [{"trim": {}}]
IR = ExtractionConfigIR.model_validate(
    {
        "ir_version": "1",
        "site": "catalog.example.test",
        "schema": {"name": "synthetic", "digest": "0" * 64},
        "page_kind": "listing",
        "fetch": {"method": "browser"},
        "fields": {
            "heading": {
                "steps": [{"jsonld": "$['name']", "when_type": "WebPage"}, {"css": "h1", "post": TRIM}],
                "status": "corroborated",
            },
        },
        "listing": {
            "row": {"css": "div.row"},
            "fields": {
                "sku": {"steps": [{"attr": "data-sku"}], "status": "operator"},
                "link": {
                    "steps": [{"xpath": "string(a/@href)", "post": [{"absolutize_url": {}}]}],
                    "status": "uncorroborated",
                },
            },
            "next": {"regex": r"next=([a-z0-9/]+)", "post": [{"absolutize_url": {}}]},
        },
        "provenance": {
            "origin": "operator",
            "validated_on": [],
            "learned_at": "2026-10-03T00:00:00Z",
            "engine_version": "test",
        },
    }
)


def _page(n: int, *, link: str = "/i/1") -> HeldOutPage:
    rows = "".join(f"<div class='row' data-sku='S{n}{k}'><a href='{link}'>x</a></div>" for k in range(3))
    body = f"<h1> Page {n} </h1>{rows}<!-- next=/list/2 -->"
    published = {"heading": f"Page {n}", "next_page_url": "https://catalog.example.test/list/2"}
    return HeldOutPage(
        capture_id=CaptureId(uuid7()),
        page=ParsedPage(f"<html><body>{body}</body></html>"),
        ctx=CTX,
        facts=Facts(published=published),
        rows=[Facts(published={"sku": f"S{n}{k}", "link": "https://catalog.example.test/i/1"}) for k in range(3)],
    )


def test_json_exports_the_ir_as_stored() -> None:
    exported = export_config("json", IR, SCHEMA, [_page(n) for n in range(3)])
    assert exported.model_dump(mode="json")["export"] == IR.model_dump(mode="json", by_alias=True)
    assert exported.release.listing is not None
    assert exported.release.listing.fields["sku"].manual is False


def test_platform_draft_carries_every_step_in_order_as_xpath_regex_or_jsonpath() -> None:
    exported = export_config("platform_draft", IR, SCHEMA, [_page(n) for n in range(3)])
    assert exported.model_dump(mode="json")["export"] == {
        "draft": True,
        "regex_flags": "u",
        "ir_version": "1",
        "site": "catalog.example.test",
        "schema": {"name": "synthetic", "digest": "0" * 64},
        "page_kind": "listing",
        "fetch": {"method": "browser"},
        "fields": {
            "heading": {
                "steps": [
                    {"jsonld": "$['name']", "when_type": "WebPage", "post": []},
                    {"xpath": "descendant-or-self::h1", "post": [{"trim": {}}]},
                ],
                "manual": False,
            },
        },
        "listing": {
            "row_xpath": CssStep.model_validate({"css": "div.row"}).xpath,
            "fields": {
                "sku": {"steps": [{"xpath": "@data-sku", "post": []}], "manual": False},
                "link": {"steps": [{"xpath": "string(a/@href)", "post": [{"absolutize_url": {}}]}], "manual": False},
            },
            "next": {"steps": [{"regex": "next=([a-z0-9/]+)", "post": [{"absolutize_url": {}}]}], "manual": False},
        },
        "api_recipe": None,
        "api_recipe_php": None,
    }


def test_a_field_the_release_check_fails_is_marked_manual() -> None:
    pages = [_page(0), _page(1), _page(2, link="/i/9")]
    exported = export_config("platform_draft", IR, SCHEMA, pages)
    listing = exported.model_dump(mode="json")["export"]["listing"]
    assert (listing["fields"]["link"]["manual"], listing["fields"]["sku"]["manual"]) == (True, False)
    assert exported.release.listing is not None
    assert exported.release.listing.fields["link"].model_dump() == {"published": 3, "reproduced": 2, "manual": True}


def _released(ir: ExtractionConfigIR, page: HeldOutPage) -> Any:
    return release_run(ir, ReleasePage(page.page.html, base_url=URL), release_rules(SCHEMA, CTX))


def _from_draft(draft: dict[str, Any]) -> ExtractionConfigIR:
    """The IR with the draft's steps in place of its own: the release check of the IR stands for the draft's only if
    both read the same values."""
    document = IR.model_dump(mode="json", by_alias=True)

    def steps(fields: dict[str, Any], drafted: dict[str, Any]) -> None:
        for name, field in fields.items():
            field["steps"] = drafted[name]["steps"]

    steps(document["fields"], draft["fields"])
    listing = draft["listing"]
    steps(document["listing"]["fields"], listing["fields"])
    document["listing"]["row"] = {"xpath": listing["row_xpath"]}
    document["listing"]["next"] = listing["next"]["steps"][0]
    return ExtractionConfigIR.model_validate(document)


def test_the_drafted_steps_read_the_same_values_as_the_ir() -> None:
    page = _page(7)
    draft = export_config("platform_draft", IR, SCHEMA, [page]).model_dump(mode="json")["export"]
    original, translated = _released(IR, page), _released(_from_draft(draft), page)
    assert (translated.fields, translated.rows) == (original.fields, original.rows)
    assert translated.rows[0] == {"sku": "S70", "link": "https://catalog.example.test/i/1"}


def test_platform_draft_carries_the_api_recipe_as_stored_and_its_php_hint() -> None:
    recipe = {
        "method": "GET",
        "url": "https://api.example.test/v2/items/{p1}",
        "params_from_url": {"p1": "path:1"},
        "map": {"heading": "$['data']['title']"},
        "proof": {"validated_on": [str(uuid7())], "headers_tried": 1, "bound_by": "deterministic"},
    }
    ir = ExtractionConfigIR.model_validate({**IR.model_dump(mode="json", by_alias=True), "api_recipe": recipe})
    exported = export_config("platform_draft", ir, SCHEMA, [_page(n) for n in range(3)])
    draft = exported.model_dump(mode="json")["export"]
    assert draft["api_recipe"] == ir.model_dump(mode="json")["api_recipe"]
    assert "'url' => strtr('https://api.example.test/v2/items/{p1}', $path)," in draft["api_recipe_php"]
    assert "//   \"heading\": \"$['data']['title']\"" in draft["api_recipe_php"]
