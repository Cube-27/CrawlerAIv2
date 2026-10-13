"""The engine executor on generated pages (SPEC-08 §4.3): a single-valued field's step proposes the one node it matches,
declines a multi-match as `multi_match`, proposes nothing without a match, a list field takes every match in document
order, and a listing's row fields read only their own row."""

from datetime import UTC, datetime
from html import escape
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Invalid
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
TEXT = FieldSpec(type=FieldType.TEXT, description="d")
TEXTS = FieldSpec(type=FieldType.LIST, description="d", item=FieldSpec(type=FieldType.TEXT))
VOCABULARY = Vocabulary(supertypes={})  # no step here reads JSON-LD

_value = st.from_regex(r"[A-Za-z0-9&<]([A-Za-z0-9&< ]{0,10}[A-Za-z0-9&<])?", fullmatch=True)
_noise = st.lists(st.sampled_from(["<p>n</p>", "<span class='w'>n</span>", "<div><b>n</b></div>"]), max_size=3)


def _schema(page_kind: str, **fields: FieldSpec) -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": SchemaId(uuid7()),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "version": 1,
            "page_kind": page_kind,
            "fields": fields,
        }
    )


def _executor(page_kind: str, fields: dict[str, Any], listing: dict[str, Any] | None = None) -> EngineExecutor:
    ir = ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "version": 1},
            "page_kind": page_kind,
            "fetch": {"method": "http"},
            "fields": fields,
            "listing": listing,
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )
    return EngineExecutor(ir, VOCABULARY)


def _page(values: list[str], noise: list[str]) -> ParsedPage:
    spans = [f"<span class='v'>{escape(v)}</span>" for v in values]
    return ParsedPage(f"<html><body>{''.join(noise)}{''.join(spans)}{''.join(noise)}</body></html>")


STEPS = {"steps": [{"xpath": "//span[@class='v']"}], "status": "uncorroborated"}


@given(st.lists(_value, max_size=4), _noise)
def test_a_single_valued_step_proposes_its_one_match_or_declines(values: list[str], noise: list[str]) -> None:
    result = _executor("detail", {"title": STEPS}).execute(_page(values, noise), _schema("detail", title=TEXT), CTX)
    if not values:
        assert result.candidates == ()
        return
    (candidate,) = result.candidates
    if len(values) == 1:
        assert (candidate.raw, candidate.normalized) == (values[0], normalize(values[0], TEXT, CTX))
    else:
        assert (candidate.raw, candidate.normalized) == (values, Invalid("multi_match"))
    assert candidate.locator == "config:title:0://span[@class='v']"


@given(st.lists(_value, min_size=1, max_size=4), _noise)
def test_a_list_step_takes_every_match_in_document_order(values: list[str], noise: list[str]) -> None:
    result = _executor("detail", {"tags": STEPS}).execute(_page(values, noise), _schema("detail", tags=TEXTS), CTX)
    (candidate,) = result.candidates
    assert candidate.raw == values


@given(st.lists(st.lists(_value, max_size=2), max_size=4))
def test_row_fields_read_only_their_own_row(rows: list[list[str]]) -> None:
    items = "".join("<li>" + "".join(f"<em>{escape(v)}</em>" for v in row) + "</li>" for row in rows)
    page = ParsedPage(f"<html><body><em>outside</em><ul>{items}</ul></body></html>")
    listing = {
        "row": {"xpath": "//ul/li"},
        "fields": {"title": {"steps": [{"xpath": "em"}], "status": "uncorroborated"}},
    }
    result = _executor("listing", {}, listing).execute(page, _schema("listing", title=TEXT), CTX)
    assert [row.id for row in result.rows] == [f"config:row:{n}" for n in range(len(rows))]
    expected = [(f"config:row:{n}", row[0] if len(row) == 1 else row) for n, row in enumerate(rows) if row]
    assert [(c.entity_id, c.raw) for c in result.candidates] == expected
