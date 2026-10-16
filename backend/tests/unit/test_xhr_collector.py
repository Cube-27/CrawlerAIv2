"""The captured network JSON collector (SPEC-05 §4.5): each captured body is a JSON document, admitted by the same rule
as embedded JSON state, and addressed by its index in the bundle."""

from datetime import UTC, datetime

from crawlerai.collect.admission import Admitted
from crawlerai.collect.base import Candidate
from crawlerai.collect.xhr import XhrCollector
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={"url": FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url")},
)
OG_URL = Candidate(
    field="url",
    entity_id="page",
    source_kind="og",
    raw=PAGE_URL,
    normalized=Ok(PAGE_URL),
    locator="meta:og:url",
    independent=True,
)


def _collect(network: tuple[bytes, ...], *others: Candidate, body: str = "") -> Admitted:
    page = ParsedPage(f"<html><body><p>{body}</p></body></html>", network)
    return XhrCollector().collect(page, SCHEMA, CTX, others)


def test_a_body_value_equal_to_another_kinds_candidate_is_admitted_and_not_independent() -> None:
    # The relative URL resolves against the page's base URL to the same URL (SPEC-04 url equality).
    result = _collect((b'{"x": 1}', b'{"data": {"href": "/p/1"}}'), OG_URL)

    assert result == Admitted(
        candidates=(
            Candidate(
                field="url",
                entity_id="page",
                source_kind="xhr",
                raw="/p/1",
                normalized=Ok(PAGE_URL),
                locator="xhr:1:$['data']['href']",
                independent=False,
            ),
        )
    )


def test_a_visible_body_value_of_a_field_without_candidates_is_independent() -> None:
    result = _collect((b'["https://shop.example.test/p/2"]',), body="see https://shop.example.test/p/2")

    assert [(c.locator, c.entity_id, c.independent) for c in result.candidates] == [("xhr:0:$[0]", "page", True)]


def test_a_body_that_is_not_utf8_json_is_skipped_with_a_diagnostic_and_keeps_its_index() -> None:
    result = _collect((b"<html>", b"\xff[]", b'["/p/1"]'), OG_URL)

    assert [c.locator for c in result.candidates] == ["xhr:2:$[0]"]
    assert [d.split(":", 2)[:2] for d in result.diagnostics] == [["xhr", "0"], ["xhr", "1"]]
