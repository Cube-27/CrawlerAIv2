"""Absent fields: learning lists the required fields of a detail schema that no page of its run stated and
that role C was asked for on every page; a config never lists a field it has steps for."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from snowcrawl.config_ir.absent import absent_fields
from snowcrawl.config_ir.held_out import StoredPage
from snowcrawl.config_ir.induction import SamplePage
from snowcrawl.config_ir.model import ExtractionConfigIR
from snowcrawl.config_ir.validation import Facts, HeldOutPage
from snowcrawl.content.page import ParsedPage
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import CaptureId, PageKind, SchemaId
from snowcrawl.normalize.base import Context
from snowcrawl.schemas.types import FieldSpec, FieldType, SchemaDef
from snowcrawl.storage.capture_bundle import CaptureBundle

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
TEXT = FieldSpec(type=FieldType.TEXT, description="d", required=True)


def _schema(page_kind: PageKind = "detail", groups: list[list[str]] | None = None) -> SchemaDef:
    optional = FieldSpec(type=FieldType.TEXT, description="d")
    offer = FieldSpec(type=FieldType.OBJECT, description="d", required=True, fields={"name": optional})
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields={"title": TEXT, "sku": TEXT, "brand": optional, "gtin": optional, "offer": offer},
        required_groups=groups or [],
    )


def _page(
    published: dict[str, Any] | None = None, stated: frozenset[str] = frozenset(), *, asked: bool = True
) -> StoredPage:
    page = ParsedPage("<html><body></body></html>")
    held_out = HeldOutPage(CaptureId(uuid7()), page, CTX, Facts(published=published or {}))
    # The capture is not read here; only API discovery reads it.
    return StoredPage(held_out, SamplePage(page, CTX, {}, ()), cast(CaptureBundle, None), stated, asked)


EIGHT = [_page({"title": "A lamp"}, frozenset({"title"})) for _ in range(8)]


@pytest.mark.parametrize(
    "last",
    [
        _page({"sku": "X1"}),  # published once
        _page(stated=frozenset({"sku"})),  # a source stated it, though it did not publish
        _page(asked=False),  # role C was not asked there
    ],
    ids=["published", "stated", "role-c-not-asked"],
)
def test_one_page_that_states_it_or_was_not_asked_keeps_it_not_absent(last: StoredPage) -> None:
    assert absent_fields(_schema(), [*EIGHT[:7], last]) == []


def _ir(**update: Any) -> dict[str, Any]:
    return {
        "ir_version": "1",
        "site": "shop.example.test",
        "schema": {"name": "synthetic", "digest": "0" * 64},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {"title": {"steps": [{"xpath": "//h1"}], "status": "corroborated"}},
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "t",
        },
        **update,
    }


def test_a_config_lists_as_absent_only_fields_without_steps() -> None:
    assert ExtractionConfigIR.model_validate(_ir(absent=["sku"])).absent == ["sku"]
    with_steps = _ir(absent=["title"])
    with pytest.raises(ValidationError, match="an absent field has no steps"):
        ExtractionConfigIR.model_validate(with_steps)
    absent_status = _ir(fields={"title": {"steps": [{"xpath": "//h1"}], "status": "absent"}})
    with pytest.raises(ValidationError, match="a field with steps is not absent"):
        ExtractionConfigIR.model_validate(absent_status)
