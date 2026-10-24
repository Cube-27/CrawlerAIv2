"""The adapter collector: a platform API's JSON read as the schema.org nodes the
adapter's shapes describe, each node an entity, each value a field's path reaches an `adapter` candidate located by its
normalized path.

The platforms come from the adapter modules and the recorded API responses under `tests/fixtures/` are synthetic, so
no hostname or tenant is written here (C3, C9).
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from snowcrawl.acquire.api import JsonFetcher
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.adapters.base import Adapter, AdapterMatch, Shape
from snowcrawl.adapters.greenhouse import Greenhouse
from snowcrawl.adapters.lever import Lever
from snowcrawl.collect.adapter import AdapterCollector
from snowcrawl.collect.base import CollectResult, Entity
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.content.page import ParsedPage
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import PageKind, SchemaId
from snowcrawl.normalize.base import Context
from snowcrawl.schemas.registry import load_presets
from snowcrawl.schemas.types import FieldSpec, SchemaDef

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


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _collect(adapter: Adapter, page_kind: PageKind, body: str, schema: SchemaDef) -> CollectResult:
    collector = AdapterCollector(adapter, AdapterMatch("tenant", page_kind), VOCABULARY)
    return collector.collect(ParsedPage(body), schema, CTX)


def _values(result: CollectResult) -> dict[tuple[str, str], tuple[JsonValue, str]]:
    """(entity, field) -> (raw, locator) of every candidate."""
    return {(c.entity_id, c.field): (c.raw, c.locator) for c in result.candidates}


def test_a_detail_response_is_one_posting_with_a_candidate_per_documented_field() -> None:
    result = _collect(GREENHOUSE, "detail", _fixture("greenhouse/job.json"), _preset("job_detail"))

    entity = "adapter:greenhouse:$"
    assert result.entities == (
        Entity(
            id=entity,
            types=("JobPosting",),
            urls=("https://jobs.example.com/example-tenant/jobs/4000001",),
            parent=None,
            item_urls=("https://jobs.example.com/example-tenant/jobs/4000001",),
        ),
        Entity(
            id="adapter:greenhouse:$['company_name']",
            types=("Organization",),
            urls=(),
            parent=entity,
            via="hiringOrganization",
            names=("Example Tenant",),
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
        (entity, "date_posted"): ("2026-09-01T09:00:00-04:00", "adapter:greenhouse:$['first_published']"),
    }
    assert {c.source_kind for c in result.candidates} == {"adapter"}
    assert all(c.independent for c in result.candidates)
    assert result.diagnostics == ()


class _StandIn:
    """An adapter whose shapes are given."""

    name = "stand-in"

    def __init__(self, *shapes: Shape) -> None:
        self._shapes = shapes

    def detect(self, url: str) -> AdapterMatch | None:
        return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return False

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        raise AssertionError("collecting fetches nothing")

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return self._shapes


def test_an_anchored_node_is_an_entity_of_its_own_on_its_enclosing_object() -> None:
    offer = Shape(type="Offer", properties={"price": ("amount",), "priceCurrency": ("currency",)}, anchor=("amount",))
    product = Shape(type="Product", properties={"name": ("title",)}, nodes={"offers": (offer,)})
    body = json.dumps({"title": "Widget", "amount": "9.50", "currency": "EUR"})

    result = _collect(_StandIn(product), "detail", body, _preset("commerce_detail"))

    assert [(e.id, e.parent) for e in result.entities] == [
        ("adapter:stand-in:$", None),
        ("adapter:stand-in:$['amount']", "adapter:stand-in:$"),
    ]
    assert _values(result)[("adapter:stand-in:$['amount']", "price")] == (
        {"price": "9.50", "priceCurrency": "EUR"},
        "adapter:stand-in:$['amount']",
    )


def test_a_node_with_mapped_properties_is_read_as_an_object_of_schema_org_names() -> None:
    # A field that reads a whole node reads what a JSON-LD node would state: schema.org names, not the API's members.
    amount = Shape(
        type="MonetaryAmount", at=("pay",), properties={"currency": ("cur",), "minValue": ("lo",), "maxValue": ("hi",)}
    )
    posting = Shape(
        type="JobPosting", nodes={"baseSalary": (amount,), "jobLocation": (Shape(type="Place", at=("place",)),)}
    )
    body = json.dumps({"pay": {"cur": "EUR", "lo": 10, "hi": 20, "extra": "x"}, "place": {"name": "Town"}})
    schema = _schema(
        "detail",
        salary=FieldSpec.model_validate({"type": "text", "description": "d", "schema_org": "JobPosting.baseSalary"}),
        place=FieldSpec.model_validate({"type": "text", "description": "d", "schema_org": "JobPosting.jobLocation"}),
    )

    result = _collect(_StandIn(posting), "detail", body, schema)

    found = _values(result)
    assert found[("adapter:stand-in:$", "salary")][0] == {"currency": "EUR", "minValue": 10, "maxValue": 20}
    assert found[("adapter:stand-in:$", "place")][0] == {"name": "Town"}  # no mapped property: the API's own object
