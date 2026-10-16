"""The adapter collector (SPEC-05 §4.5, SPEC-15 §4.4): a platform API's JSON read as the schema.org nodes the adapter's
shapes describe, each node an entity, each value a field's path reaches an `adapter` candidate located by its
normalized path.

The platforms come from the adapter modules and the recorded API responses under `tests/fixtures/` are synthetic, so
no hostname or tenant is written here (C3, C9).
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, Adapter, AdapterMatch, Members, Shape
from crawlerai.adapters.greenhouse import Greenhouse
from crawlerai.adapters.lever import Lever
from crawlerai.collect.adapter import AdapterCollector
from crawlerai.collect.base import CollectResult, Entity
from crawlerai.collect.json_doc import select
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

FIXTURES = Path(__file__).parents[1] / "fixtures"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
VOCABULARY = Vocabulary.read(FIXTURES / "synthetic" / "schemaorg_vocabulary.jsonld")
GREENHOUSE, LEVER = Greenhouse(), Lever()


def _preset(name: str) -> SchemaDef:
    (document,) = (d for d in load_presets() if d.name == name)
    return SchemaDef(id=SchemaId(uuid7()), origin="preset", status="active", **document.model_dump())


def _schema(page_kind: PageKind, **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields=fields,
    )


def _text(path: str, scope: str = "row") -> FieldSpec:
    return FieldSpec.model_validate({"type": "text", "description": "d", "scope": scope, "schema_org": path})


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _collect(adapter: Adapter, page_kind: PageKind, body: str, schema: SchemaDef) -> CollectResult:
    return AdapterCollector(adapter, page_kind, VOCABULARY).collect(ParsedPage(body), schema, CTX)


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
        Entity(
            id="adapter:greenhouse:$['company_name']",
            kind="Organization",
            urls=(),
            parent=entity,
            via="hiringOrganization",
        ),
    )
    assert _values(result) == {
        (entity, "title"): ("Synthetic Platform Engineer", "adapter:greenhouse:$['title']"),
        (entity, "company"): ("Example Tenant", "adapter:greenhouse:$['company_name']"),
        (entity, "locations"): (["Remote"], "adapter:greenhouse:$['location']['name']"),
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


def test_a_lever_detail_response_reads_each_documented_member() -> None:
    result = _collect(LEVER, "detail", _fixture("lever/posting.json"), _preset("job_detail"))

    assert {field: locator for (_, field), (_, locator) in _values(result).items()} == {
        "title": "adapter:lever:$['text']",
        "locations": "adapter:lever:$['categories']['location']",
        "description": "adapter:lever:$['description']",
        "apply_url": "adapter:lever:$['hostedUrl']",
    }


def test_a_listing_response_is_a_list_of_postings_each_owning_its_values() -> None:
    result = _collect(LEVER, "listing", _fixture("lever/postings.json"), _preset("job_listing"))

    rows = ("adapter:lever:$[0]", "adapter:lever:$[1]")
    assert [(e.id, e.kind, e.parent, e.via) for e in result.entities] == [
        ("adapter:lever:$", "ItemList", None, None),
        *((row, "JobPosting", "adapter:lever:$", "itemListElement") for row in rows),
    ]
    assert result.entities[2].urls == ("https://jobs.example.com/example-tenant/00000000-0000-4000-8000-000000000002",)
    values = _values(result)
    assert values[(rows[0], "title")] == ("Synthetic Platform Engineer", "adapter:lever:$[0]['text']")
    assert values[(rows[1], "title")] == ("Synthetic Data Analyst", "adapter:lever:$[1]['text']")
    assert values[(rows[1], "location")] == ("Example City", "adapter:lever:$[1]['categories']['location']")
    assert {field for _, field in values} == {"title", "url", "location"}


def test_the_listing_root_of_an_object_response_addresses_its_rows() -> None:
    result = _collect(GREENHOUSE, "listing", _fixture("greenhouse/jobs.json"), _preset("job_listing"))

    assert [e.id for e in result.entities] == [
        "adapter:greenhouse:$",
        "adapter:greenhouse:$['jobs'][0]",
        "adapter:greenhouse:$['jobs'][1]",
    ]
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
        # A list field's candidate holds every value its property reaches and is located at the first.
        (raw,) = candidate.raw if isinstance(candidate.raw, list) else [candidate.raw]
        assert select(path, document) == [(path, raw)]
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


def test_a_property_the_shapes_do_not_document_yields_no_candidate() -> None:
    schema = _schema("detail", title=_text("JobPosting.title"), salary=_text("JobPosting.baseSalary"))

    result = _collect(GREENHOUSE, "detail", _fixture("greenhouse/job.json"), schema)

    assert [(c.field, c.raw) for c in result.candidates] == [("title", "Synthetic Platform Engineer")]


def test_a_body_that_is_not_json_is_skipped_with_a_diagnostic() -> None:
    result = _collect(GREENHOUSE, "detail", "<html><body>not json</body></html>", _preset("job_detail"))

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

    assert [e.id for e in result.entities] == ["adapter:lever:$", *(f"adapter:lever:$[{i}]" for i in range(len(names)))]
    assert [(c.entity_id, c.raw) for c in result.candidates] == [
        (f"adapter:lever:$[{i}]", name) for i, name in enumerate(names)
    ]


class _StandIn:
    """An adapter whose shapes are given."""

    name = "stand-in"

    def __init__(self, *shapes: Shape) -> None:
        self._shapes = shapes

    def detect(self, url: str) -> AdapterMatch | None:
        return None

    def serves(self, endpoint: str) -> bool:
        return False

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        raise AssertionError("collecting fetches nothing")

    def shapes(self, page_kind: PageKind) -> tuple[Shape, ...]:
        return self._shapes


_JOB = Shape(
    type="JobPosting",
    properties={"title": ("title",), "url": ("url",), "jobLocation": ("offices", ALL, "name")},
)
_OFFICES = FieldSpec.model_validate(
    {
        "type": "list",
        "description": "d",
        "item": {"type": "text"},
        "scope": "row",
        "schema_org": "JobPosting.jobLocation",
    }
)


def _job(n: int) -> dict[str, JsonValue]:
    return {
        "title": f"Role {n}",
        "url": f"https://jobs.example.test/{n}",
        "offices": [{"name": "North"}, {"name": "South"}],
    }


def test_a_list_field_holds_every_value_its_property_reaches_located_at_the_first() -> None:
    schema = _schema("detail", title=_text("JobPosting.title"), offices=_OFFICES)

    result = _collect(_StandIn(_JOB), "detail", json.dumps(_job(1)), schema)

    assert [e.id for e in result.entities] == ["adapter:stand-in:$"]
    assert _values(result)[("adapter:stand-in:$", "offices")] == (
        ["North", "South"],
        "adapter:stand-in:$['offices'][0]['name']",
    )


def test_each_listing_row_holds_its_own_list_field_items() -> None:
    schema = _schema("listing", title=_text("JobPosting.title"), offices=_OFFICES)
    rows_shape = Shape(type="JobPosting", at=("jobs", ALL), properties=_JOB.properties)

    result = _collect(_StandIn(rows_shape), "listing", json.dumps({"jobs": [_job(1), _job(2)]}), schema)

    rows = [f"adapter:stand-in:$['jobs'][{i}]" for i in (0, 1)]
    assert [e.id for e in result.entities] == rows
    assert [(c.entity_id, c.field, c.raw) for c in result.candidates if c.field == "offices"] == [
        (row, "offices", ["North", "South"]) for row in rows
    ]


def test_fields_of_several_types_are_read_from_nested_nodes_each_owned_by_its_node() -> None:
    offer = Shape(type="Offer", at=("offer",), properties={"price": ("amount",), "priceCurrency": ("currency",)})
    product = Shape(type="Product", properties={"name": ("title",)}, nodes={"offers": (offer,)})
    body = json.dumps({"title": "Widget", "offer": {"amount": "9.50", "currency": "EUR"}})

    preset = _preset("commerce_detail")
    schema = _schema("detail", title=preset.fields["title"], price=preset.fields["price"])

    result = _collect(_StandIn(product), "detail", body, schema)

    assert [(e.id, e.kind, e.parent, e.via) for e in result.entities] == [
        ("adapter:stand-in:$", "Product", None, None),
        ("adapter:stand-in:$['offer']", "Offer", "adapter:stand-in:$", "offers"),
    ]
    assert _values(result) == {
        ("adapter:stand-in:$", "title"): ("Widget", "adapter:stand-in:$['title']"),
        ("adapter:stand-in:$['offer']", "price"): (
            {"price": "9.50", "priceCurrency": "EUR"},
            "adapter:stand-in:$['offer']['amount']",
        ),
    }


def _in_stock(data: Mapping[str, JsonValue]) -> tuple[JsonValue, Members] | None:
    return ("https://schema.org/InStock", ("available",)) if data.get("available") is True else None


def test_an_anchored_node_is_an_entity_of_its_own_on_its_enclosing_object() -> None:
    offer = Shape(
        type="Offer", properties={"price": ("amount",)}, stated={"availability": _in_stock}, anchor=("amount",)
    )
    product = Shape(type="Product", properties={"name": ("title",)}, nodes={"offers": (offer,)})
    body = json.dumps({"title": "Widget", "amount": "9.50", "available": True})

    result = _collect(_StandIn(product), "detail", body, _preset("commerce_detail"))

    assert [(e.id, e.parent) for e in result.entities] == [
        ("adapter:stand-in:$", None),
        ("adapter:stand-in:$['amount']", "adapter:stand-in:$"),
    ]
    assert _values(result)[("adapter:stand-in:$['amount']", "availability")] == (
        "https://schema.org/InStock",
        "adapter:stand-in:$['available']",
    )
