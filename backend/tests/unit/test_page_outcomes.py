"""One outcome model for a page (resolution spec, "Render-bound fields" and "Out of stock without a price"; acquisition
spec, "Error outcomes and reasons"): a fetch that got no answer in time is `timeout`, a price missing from a page that
states its item is not for sale is `out_of_stock`, and `interaction_required` is left to a field whose source in the
site's config is the browser, on a page no render ran for. Pages are synthetic (`example.test`, C3, C9).
"""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.collect.config import Executed
from crawlerai.collect.network_match import LearnedCalls
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import FieldStatus, SchemaId
from crawlerai.normalize.base import Context
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.services.scrape_steps import FetchFailure, fetch_failure
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/p/1"
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
DATA = EngineData(
    vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ("jsonld", "microdata", "og")), calibration=None
)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="s",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(
            type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"
        ),
        "availability": FieldSpec(
            type=FieldType.ENUM, description="d", vocab="schema:ItemAvailability", schema_org="Offer.availability"
        ),
        "size": FieldSpec(type=FieldType.TEXT, description="d"),
    },
)


def _fetched(
    method: CaptureMethod,
    body: str = "<html></html>",
    *,
    block_class: BlockClass = "ok",
    attempts: tuple[AttemptRecord, ...] | None = None,
) -> FetchResult:
    raw = body.encode()
    made = attempts or (AttemptRecord(method=method, status=200, block_class=block_class, duration_ms=1),)
    policy = {**FetchPolicy().model_dump(mode="json"), "attempts": [a.model_dump(mode="json") for a in made]}
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=URL,
        final_url=URL,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method=method,
        status_code=200,
        block_class=block_class,
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={"total": 1},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy=policy,
        engine_version="test",
    )
    return FetchResult(bundle=CaptureBundle(manifest=manifest, body=raw, network=()), duration_ms=1, attempts=made)


@pytest.mark.parametrize(
    ("block_class", "error", "failure"),
    [
        pytest.param("error", "timeout", "timeout", id="no-answer-in-time"),
        pytest.param("error", "network_error", "failed", id="other-error"),
        pytest.param("blocked", None, None, id="a-block-is-an-answer"),
        pytest.param("ok", None, None, id="ok"),
    ],
)
def test_a_fetch_failure_is_a_timeout_only_when_no_answer_came_in_time(
    block_class: BlockClass, error: str | None, failure: FetchFailure | None
) -> None:
    attempt = AttemptRecord(method="http", status=None, block_class=block_class, duration_ms=1, error=error)
    assert fetch_failure(_fetched("http", block_class=block_class, attempts=(attempt,))) == failure


def _product(availability: str | None, *, price: str | None = None) -> str:
    offer: dict[str, object] = {"@type": "Offer"}
    if availability is not None:
        offer["availability"] = f"https://schema.org/{availability}"
    if price is not None:
        offer |= {"price": price, "priceCurrency": "EUR"}
    node = {"@context": "https://schema.org", "@type": "Product", "name": "Widget", "offers": offer}
    return (
        f'<html lang="en"><head><script type="application/ld+json">{json.dumps(node)}</script></head>'
        "<body><h1>Widget</h1></body></html>"
    )


@dataclass(frozen=True)
class BrowserConfig:
    """A site's config that reads `browser_fields` from rendered pages and proposes nothing on this one."""

    browser_fields: frozenset[str]
    learned_calls: LearnedCalls | None = None

    @property
    def field_status(self) -> Mapping[str, FieldStatus]:
        return dict.fromkeys(self.browser_fields, "corroborated")

    def execute(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> Executed:
        return Executed(rows=(), candidates=())


def _statuses(result: FetchResult, config: BrowserConfig | None = None) -> dict[str, tuple[str, str | None]]:
    extracted = asyncio.run(extract_page(result.bundle, SCHEMA, config, None, data=DATA))
    assert extracted.entity is not None
    return {name: (field.status, field.reason) for name, field in extracted.entity.items()}


@pytest.mark.parametrize(
    ("availability", "price", "expected"),
    [
        pytest.param("OutOfStock", None, ("missing", "out_of_stock"), id="out-of-stock"),
        pytest.param("SoldOut", None, ("missing", "out_of_stock"), id="sold-out"),
        pytest.param("InStock", None, ("missing", "no_candidates"), id="in-stock-without-price"),
        pytest.param(None, None, ("missing", "no_candidates"), id="no-availability"),
        pytest.param("OutOfStock", "19.90", ("published", None), id="out-of-stock-with-price"),
    ],
)
def test_a_price_missing_from_a_page_whose_item_is_not_for_sale_says_so(
    availability: str | None, price: str | None, expected: tuple[str, str | None]
) -> None:
    statuses = _statuses(_fetched("http", _product(availability, price=price)))
    assert statuses["price"] == expected
    assert statuses["size"] == ("missing", "no_candidates")


SIZE_IN_BROWSER = BrowserConfig(frozenset({"size"}))


@pytest.mark.parametrize(
    ("method", "attempts", "config", "size"),
    [
        pytest.param("http", None, SIZE_IN_BROWSER, ("interaction_required", "render_bound"), id="not-rendered"),
        pytest.param("http", None, None, ("missing", "no_candidates"), id="no-config"),
        pytest.param("http", None, BrowserConfig(frozenset()), ("missing", "no_candidates"), id="http-sources"),
        pytest.param("browser", None, SIZE_IN_BROWSER, ("missing", "no_candidates"), id="rendered"),
        pytest.param(
            "http",
            (
                AttemptRecord(method="browser", status=200, block_class="shell", duration_ms=1),
                AttemptRecord(method="http", status=200, block_class="ok", duration_ms=1),
            ),
            SIZE_IN_BROWSER,
            ("missing", "no_candidates"),
            id="rendered-and-the-http-page-kept",
        ),
    ],
)
def test_interaction_is_required_only_for_a_browser_field_where_no_render_ran(
    method: CaptureMethod,
    attempts: tuple[AttemptRecord, ...] | None,
    config: BrowserConfig | None,
    size: tuple[str, str],
) -> None:
    statuses = _statuses(_fetched(method, _product("InStock", price="19.90"), attempts=attempts), config)
    assert statuses["size"] == size
    assert statuses["price"] == ("published", None)


def test_a_field_the_outcome_explains_is_not_left_to_a_render() -> None:
    config = BrowserConfig(frozenset({"price", "size"}))
    statuses = _statuses(_fetched("http", _product("OutOfStock")), config)
    assert statuses["price"] == ("missing", "out_of_stock")
    assert statuses["size"] == ("interaction_required", "render_bound")
