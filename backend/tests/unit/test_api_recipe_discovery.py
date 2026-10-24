"""API discovery: from browser captures with network bodies, find the endpoint whose JSON carries the
page's published values on every sample page, with one JSONPath per field.

Captures are built in memory with synthetic `.test` hosts; the browser-marked end-to-end test is in
`test_api_recipe_discovery_browser.py`.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import JsonValue

from snowcrawl.config_ir.api_recipe.binding import CapturedRequest
from snowcrawl.config_ir.api_recipe.discovery import DiscoverySample, EndpointCandidate, discover
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import SchemaId
from snowcrawl.normalize.base import Context
from snowcrawl.schemas.types import FieldSpec, FieldType, SchemaDef
from snowcrawl.storage.capture_bundle import CaptureBundle
from tests.support.captures import call, capture

SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
        "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
        "description": FieldSpec(type=FieldType.LONG_TEXT, description="d"),
    },
)
SITE = "https://shop.example.test"
API = "https://api.example.test"


@dataclass(frozen=True)
class Body:
    """A captured JSON response and the request behind it."""

    url: str
    content: JsonValue | bytes
    method: str | None = "GET"
    status: int = 200
    request_body: str | None = None
    request_headers: tuple[tuple[str, str], ...] | None = None

    @property
    def data(self) -> bytes:
        return self.content if isinstance(self.content, bytes) else json.dumps(self.content).encode()


def _bundle(page_url: str, html: str, bodies: Sequence[Body]) -> CaptureBundle:
    network = tuple(
        call(
            i,
            b.url,
            b.data,
            status=b.status,
            method=b.method,
            request_body=b.request_body,
            request_headers=b.request_headers,
        )
        for i, b in enumerate(bodies)
    )
    return capture(html.encode(), url=page_url, method="browser", headers=(), network=network, capture_id=UUID(int=1))


def _sample(slug: str, values: Mapping[str, JsonValue], bodies: Sequence[Body], text: str = "") -> DiscoverySample:
    page_url = f"{SITE}/p/{slug}"
    ctx = Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url=page_url, page_url=page_url)
    html = f"<html><body><h1>{values.get('title', '')}</h1><p>{text}</p></body></html>"
    return DiscoverySample(bundle=_bundle(page_url, html, bodies), values=values, ctx=ctx)


def _values(title: str, amount: str) -> dict[str, JsonValue]:
    return {"title": title, "price": {"amount": amount, "currency": "EUR"}}


def _product(slug: str, title: str, amount: str) -> Body:
    data: JsonValue = {"data": {"id": slug, "name": title, "price": float(amount), "currency": "EUR"}}
    return Body(f"{API}/products/{slug}", data)


def _config() -> Body:
    return Body(f"{API}/config?lang=en", {"menu": ["Home", "Lamps"], "build": "7"})


LAMP = _sample("lamp-1", _values("Desk Lamp", "19.5"), [_config(), _product("lamp-1", "Desk Lamp", "19.5")])
CHAIR = _sample("chair-2", _values("Oak Chair", "120.0"), [_product("chair-2", "Oak Chair", "120.0"), _config()])


def test_the_endpoint_carrying_the_published_values_on_every_page_is_found_with_its_paths() -> None:
    assert discover([LAMP, CHAIR], SCHEMA) == [
        EndpointCandidate(
            requests=(
                CapturedRequest("GET", f"{API}/products/lamp-1"),
                CapturedRequest("GET", f"{API}/products/chair-2"),
            ),
            map={"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
            score=4,
        )
    ]


def test_endpoints_rank_by_score_and_visible_values_of_unpublished_fields_count() -> None:
    blurb = "Solid oak, hand finished"

    def page(slug: str, title: str) -> DiscoverySample:
        brief = Body(f"{API}/brief/{slug}", {"name": title})
        full = Body(f"{API}/full/{slug}/v2", {"name": title, "text": blurb})
        return _sample(slug, {"title": title}, [brief, full], text=blurb)

    found = discover([page("lamp-1", "Desk Lamp"), page("chair-2", "Oak Chair")], SCHEMA)

    assert [(c.requests[0].url, c.map, c.score) for c in found] == [
        (f"{API}/full/lamp-1/v2", {"title": "$['name']"}, 4),
        (f"{API}/brief/lamp-1", {"title": "$['name']"}, 2),
    ]
