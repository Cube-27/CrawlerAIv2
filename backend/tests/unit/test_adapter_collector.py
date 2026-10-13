"""The adapter collector (SPEC-05 §4.5): a platform API's JSON read through the adapter's documented map, each
posting an entity, each mapped value an `adapter` candidate located by its normalized path.

The platforms come from the adapter modules and the recorded API responses under `tests/fixtures/` are synthetic, so
no hostname or tenant is written here (C3, C9).
"""

import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import Adapter
from crawlerai.adapters.greenhouse import Greenhouse
from crawlerai.adapters.lever import Lever
from crawlerai.collect.adapter import AdapterCollector
from crawlerai.collect.base import CollectResult, Entity
from crawlerai.collect.json_doc import select
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId
from crawlerai.normalize import location
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

FIXTURES = Path(__file__).parents[1] / "fixtures"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))


async def _no_fetch(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("collecting fetches nothing")


GREENHOUSE, LEVER = Greenhouse(_no_fetch), Lever(_no_fetch)


@pytest.fixture(autouse=True, scope="module")
def _no_gazetteer() -> Iterator[None]:
    """Location values are read against an empty gazetteer: the collector passes them to the normalizer as written,
    and the GeoNames snapshot is not needed to check that."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(location, "default_gazetteer", lambda: location.Gazetteer.parse("", "", []))
        yield


def _preset(name: str) -> SchemaDef:
    (document,) = (d for d in load_presets() if d.name == name)
    return SchemaDef(id=SchemaId(uuid7()), origin="preset", status="active", **document.model_dump())


def _schema(page_kind: PageKind, **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        version=1,
        page_kind=page_kind,
        fields=fields,
    )


def _text(path: str, scope: str = "row") -> FieldSpec:
    return FieldSpec.model_validate({"type": "text", "description": "d", "scope": scope, "schema_org": path})


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _collect(adapter: Adapter, page_kind: PageKind, body: str, schema: SchemaDef) -> CollectResult:
    return AdapterCollector(adapter, page_kind).collect(ParsedPage(body), schema, CTX)


def _values(result: CollectResult) -> dict[tuple[str, str], tuple[JsonValue, str]]:
    """(entity, field) -> (raw, locator) of every candidate."""
    return {(c.entity_id, c.field): (c.raw, c.locator) for c in result.candidates}


def test_a_detail_response_is_one_posting_with_a_candidate_per_documented_field() -> None:
    result = _collect(GREENHOUSE, "detail", _fixture("greenhouse/job.json"), _preset("job_detail"))

    entity = "adapter:greenhouse:$"
    assert result.entities == (
        Entity(
            id=entity, kind="JobPosting", urls=("https://jobs.example.com/example-tenant/jobs/4000001",), parent=None
        ),
    )
    assert _values(result) == {
        (entity, "title"): ("Synthetic Platform Engineer", "adapter:greenhouse:$['title']"),
        (entity, "company"): ("Example Tenant", "adapter:greenhouse:$['company_name']"),
        (entity, "locations"): ("Remote", "adapter:greenhouse:$['location']['name']"),
        (entity, "description"): (
            "&lt;p&gt;Build synthetic systems for a test fixture.&lt;/p&gt;",
            "adapter:greenhouse:$['content']",
        ),
        (entity, "apply_url"): (
            "https://jobs.example.com/example-tenant/jobs/4000001",
            "adapter:greenhouse:$['absolute_url']",
        ),
        (entity, "date_posted"): ("2026-09-01T09:00:00-04:00", "adapter:greenhouse:$['first_published']"),
    }
    assert {c.source_kind for c in result.candidates} == {"adapter"}
    assert all(c.independent for c in result.candidates)
    assert result.diagnostics == ()


def test_a_listing_response_is_one_entity_per_posting_owning_its_values() -> None:
    result = _collect(LEVER, "listing", _fixture("lever/postings.json"), _preset("job_listing"))

    rows = ("adapter:lever:$[0]", "adapter:lever:$[1]")
    assert [(e.id, e.kind, e.parent) for e in result.entities] == [(row, "JobPosting", None) for row in rows]
    assert result.entities[1].urls == ("https://jobs.example.com/example-tenant/00000000-0000-4000-8000-000000000002",)
    values = _values(result)
    assert values[(rows[0], "title")] == ("Synthetic Platform Engineer", "adapter:lever:$[0]['text']")
    assert values[(rows[1], "title")] == ("Synthetic Data Analyst", "adapter:lever:$[1]['text']")
    assert values[(rows[1], "location")] == ("Example City", "adapter:lever:$[1]['categories']['location']")
    assert {field for _, field in values} == {"title", "url", "location"}


def test_the_listing_root_of_an_object_response_addresses_its_rows() -> None:
    result = _collect(GREENHOUSE, "listing", _fixture("greenhouse/jobs.json"), _preset("job_listing"))

    assert [e.id for e in result.entities] == ["adapter:greenhouse:$['jobs'][0]", "adapter:greenhouse:$['jobs'][1]"]
    assert _values(result)[("adapter:greenhouse:$['jobs'][1]", "location")] == (
        "Example City",
        "adapter:greenhouse:$['jobs'][1]['location']['name']",
    )


@pytest.mark.parametrize(
    ("adapter", "page_kind", "fixture", "preset"),
    [
        (GREENHOUSE, "detail", "greenhouse/job.json", "job_detail"),
        (GREENHOUSE, "listing", "greenhouse/jobs.json", "job_listing"),
        (LEVER, "detail", "lever/posting.json", "job_detail"),
        (LEVER, "listing", "lever/postings.json", "job_listing"),
    ],
)
def test_every_candidate_is_the_normalized_value_its_locator_selects(
    adapter: Adapter, page_kind: PageKind, fixture: str, preset: str
) -> None:
    body = _fixture(fixture)
    schema = _preset(preset)
    result = _collect(adapter, page_kind, body, schema)

    assert result.candidates
    document = json.loads(body)
    for candidate in result.candidates:
        path = candidate.locator.removeprefix(f"adapter:{adapter.name}:")
        assert select(path, document) == [(path, candidate.raw)]
        assert candidate.normalized == normalize(candidate.raw, schema.fields[candidate.field], CTX)
        assert path.startswith(candidate.entity_id.removeprefix(f"adapter:{adapter.name}:"))


def test_a_page_scoped_field_of_a_listing_is_not_read_from_the_rows() -> None:
    schema = _schema(
        "listing",
        title=_text("JobPosting.title"),
        heading=_text(scope="page", path="JobPosting.title"),
    )

    result = _collect(LEVER, "listing", _fixture("lever/postings.json"), schema)

    assert {c.field for c in result.candidates} == {"title"}


def test_a_null_or_absent_value_is_no_candidate() -> None:
    schema = _schema("detail", title=_text("JobPosting.title"))
    body = json.dumps({"title": None, "absolute_url": "https://jobs.example.com/t/jobs/1"})

    result = _collect(GREENHOUSE, "detail", body, schema)

    assert result.candidates == ()
    assert [e.urls for e in result.entities] == [("https://jobs.example.com/t/jobs/1",)]


def test_a_schema_without_documented_fields_yields_nothing() -> None:
    schema = _schema("detail", salary=_text("JobPosting.baseSalary"))

    assert _collect(GREENHOUSE, "detail", _fixture("greenhouse/job.json"), schema) == CollectResult(
        entities=(), candidates=()
    )


@pytest.mark.parametrize("body", ["<html><body>not json</body></html>", "", "{"])
def test_a_body_that_is_not_json_is_skipped_with_a_diagnostic(body: str) -> None:
    result = _collect(GREENHOUSE, "detail", body, _preset("job_detail"))

    assert (result.entities, result.candidates) == ((), ())
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].startswith("adapter:greenhouse: not JSON")


titles = st.text(min_size=1, max_size=20).filter(
    lambda t: isinstance(normalize(t, FieldSpec(type=FieldType.TEXT), CTX), Ok)
)


@given(names=st.lists(titles, max_size=6))
def test_each_posting_of_a_listing_owns_exactly_its_own_title(names: list[str]) -> None:
    schema = _schema("listing", title=_text("JobPosting.title"))
    body = json.dumps([{"text": name} for name in names])

    result = _collect(LEVER, "listing", body, schema)

    assert [e.id for e in result.entities] == [f"adapter:lever:$[{i}]" for i in range(len(names))]
    assert [(c.entity_id, c.raw) for c in result.candidates] == [
        (f"adapter:lever:$[{i}]", name) for i, name in enumerate(names)
    ]


class _TwoTypes:
    """An adapter whose map documents values of two schema.org types in one response."""

    name = "stand-in"

    def detect(self, url: str) -> None:
        return None

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("collecting fetches nothing")

    def map(self, schema_org: Mapping[str, str], page_kind: PageKind) -> dict[str, str]:
        return {field: "$['name']" for field in schema_org}


def test_a_map_over_several_types_is_skipped_with_a_diagnostic() -> None:
    schema = _schema("detail", title=_text("JobPosting.title"), company=_text("Organization.legalName"))

    result = _collect(_TwoTypes(), "detail", json.dumps({"name": "x"}), schema)

    assert (result.entities, result.candidates) == ((), ())
    assert result.diagnostics == ("adapter:stand-in: maps fields of several types ['JobPosting', 'Organization']",)
