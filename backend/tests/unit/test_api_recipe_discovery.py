"""API discovery (SPEC-09 §4.3): from browser captures with network bodies, find the endpoint whose JSON carries the
page's published values on every sample page, with one JSONPath per field.

Captures are built in memory with synthetic `.test` hosts; the browser-marked end-to-end test is in
`test_api_recipe_discovery_browser.py`.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from pydantic import JsonValue

from crawlerai.config_ir.api_recipe.binding import CapturedRequest
from crawlerai.config_ir.api_recipe.discovery import DiscoverySample, EndpointCandidate, discover
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, sha256_hex

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
    body = html.encode()
    return CaptureBundle(
        manifest=CaptureManifest(
            capture_id=UUID(int=1),
            url=page_url,
            final_url=page_url,
            fetched_at=datetime(2026, 10, 14, tzinfo=UTC),
            method="browser",
            status_code=200,
            block_class="ok",
            headers=Headers(request=(), response=()),
            timings_ms={},
            html_sha256=sha256_hex(body),
            network_bodies=tuple(
                NetworkBody(
                    url=b.url,
                    status=b.status,
                    content_type="application/json",
                    sha256=sha256_hex(b.data),
                    file=f"network/{i + 1:04d}.json",
                    method=b.method,
                    request_body=b.request_body,
                    request_headers=b.request_headers,
                )
                for i, b in enumerate(bodies)
            ),
            fetch_policy={},
            engine_version="test",
        ),
        body=body,
        network=tuple(b.data for b in bodies),
    )


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


def test_an_endpoint_that_carries_no_required_value_on_one_sample_page_is_not_a_candidate() -> None:
    other = Body(f"{API}/products/table-3", {"data": {"name": "Something else", "price": 1, "currency": "EUR"}})
    table = _sample("table-3", _values("Pine Table", "80.0"), [other])

    assert [c.requests[0].url for c in discover([LAMP, CHAIR], SCHEMA)] == [f"{API}/products/lamp-1"]
    assert discover([LAMP, CHAIR, table], SCHEMA) == []


def test_a_field_found_at_different_paths_on_different_pages_is_left_out_of_the_map() -> None:
    lamp = _sample("lamp-1", _values("Desk Lamp", "19.5"), [Body(f"{API}/item/1", {"a": "Desk Lamp", "p": "EUR 19.5"})])
    chair = _sample(
        "chair-2", _values("Oak Chair", "120.0"), [Body(f"{API}/item/2", {"b": "Oak Chair", "p": "EUR 120"})]
    )

    (candidate,) = discover([lamp, chair], SCHEMA)

    assert candidate.map == {"price": "$['p']"}


def test_a_path_shared_by_every_page_wins_over_an_earlier_one_that_is_not() -> None:
    lamp = _sample("lamp-1", _values("Desk Lamp", "19.5"), [Body(f"{API}/i/1", {"a": "Desk Lamp", "b": "Desk Lamp"})])
    chair = _sample("chair-2", _values("Oak Chair", "120.0"), [Body(f"{API}/i/2", {"a": "Other", "b": "Oak Chair"})])

    (candidate,) = discover([lamp, chair], SCHEMA)

    assert candidate.map == {"title": "$['b']"}


def test_a_large_object_of_text_members_next_to_the_money_pair_is_searched_in_bounded_time() -> None:
    def page(slug: str, title: str, amount: float) -> DiscoverySample:
        data: JsonValue = {
            **{f"label_{i}": "Menu entry" for i in range(3_000)},
            "name": title,
            "price": amount,
            "currency": "EUR",
        }
        return _sample(slug, _values(title, str(amount)), [Body(f"{API}/products/{slug}", data)])

    (candidate,) = discover([page("lamp-1", "Desk Lamp", 19.5), page("chair-2", "Oak Chair", 120.0)], SCHEMA)

    assert candidate.map == {"title": "$['name']", "price": "$['price']+$['currency']"}


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


def test_requests_with_a_different_body_shape_are_different_endpoints() -> None:
    def page(slug: str, title: str) -> DiscoverySample:
        product = Body(
            f"{API}/graphql",
            {"product": {"name": title}},
            method="POST",
            request_body=json.dumps({"query": "q1", "variables": {"slug": slug}}),
        )
        menu = Body(f"{API}/graphql", {"menu": [title]}, method="POST", request_body=json.dumps({"query": "q2"}))
        return _sample(slug, {"title": title}, [product, menu])

    found = discover([page("lamp-1", "Desk Lamp"), page("chair-2", "Oak Chair")], SCHEMA)

    assert [(c.requests, c.map) for c in found] == [
        (
            (
                CapturedRequest("POST", f"{API}/graphql", '{"query": "q1", "variables": {"slug": "lamp-1"}}'),
                CapturedRequest("POST", f"{API}/graphql", '{"query": "q1", "variables": {"slug": "chair-2"}}'),
            ),
            {"title": "$['product']['name']"},
        ),
        (
            (
                CapturedRequest("POST", f"{API}/graphql", '{"query": "q2"}'),
                CapturedRequest("POST", f"{API}/graphql", '{"query": "q2"}'),
            ),
            {"title": "$['menu'][0]"},
        ),
    ]


def test_bodies_without_a_recorded_method_or_a_success_status_are_not_read() -> None:
    def page(slug: str, title: str) -> DiscoverySample:
        data: JsonValue = {"name": title}
        old = Body(f"{API}/old/{slug}", data, method=None)
        gone = Body(f"{API}/gone/{slug}", data, status=404)
        return _sample(slug, {"title": title}, [old, gone, Body(f"{API}/ok/{slug}", data)])

    found = discover([page("lamp-1", "Desk Lamp"), page("chair-2", "Oak Chair")], SCHEMA)

    assert [c.requests[0].url for c in found] == [f"{API}/ok/lamp-1"]


def test_bodies_that_are_not_json_are_skipped() -> None:
    broken = Body(f"{API}/products/lamp-1", b"not json")
    lamp = _sample("lamp-1", _values("Desk Lamp", "19.5"), [broken, _product("lamp-1", "Desk Lamp", "19.5")])

    (found,) = discover([lamp, CHAIR], SCHEMA)

    assert found.requests == (
        CapturedRequest("GET", f"{API}/products/lamp-1"),
        CapturedRequest("GET", f"{API}/products/chair-2"),
    )


def test_a_candidate_request_carries_the_headers_the_browser_sent() -> None:
    sent = (("Referer", f"{SITE}/p/lamp-1"), ("X-Requested-With", "XMLHttpRequest"))
    lamp = _sample(
        "lamp-1", _values("Desk Lamp", "19.5"), [replace(_product("lamp-1", "Desk Lamp", "19.5"), request_headers=sent)]
    )

    (best,) = discover([lamp, CHAIR], SCHEMA)

    assert [request.headers for request in best.requests] == [sent, ()]


def test_a_body_behind_a_guard_prefix_is_read_as_the_json_after_it() -> None:
    def guarded(slug: str, title: str, amount: str) -> Body:
        return Body(f"{API}/products/{slug}", b")]}'\n" + _product(slug, title, amount).data)

    lamp = _sample("lamp-1", _values("Desk Lamp", "19.5"), [guarded("lamp-1", "Desk Lamp", "19.5")])
    chair = _sample("chair-2", _values("Oak Chair", "120.0"), [guarded("chair-2", "Oak Chair", "120.0")])

    (candidate,) = discover([lamp, chair], SCHEMA)

    assert candidate.map == {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"}
