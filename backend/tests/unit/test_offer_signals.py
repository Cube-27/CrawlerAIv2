"""The browser decision for a detail page (owner plan 2026-10-19 P3; acquisition spec, "Browser on evidence"): cheap
signals that the HTTP document carries the offer, no collector pass; the caller's `render_fields`; and no render
started too close to the task's deadline.

Pages are synthetic (`example.test`); the rungs are stubs (C3, C9).
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crawlerai.acquire.rungs import BROWSER_MIN_S, Rungs, acquire
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.content.render_need import STATE_MIN_VALUES, holds_state, offer_shown
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.services.scrape_steps import RenderNeed
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/p/1"


def _schema(*, price_required: bool = True) -> SchemaDef:
    fields = {
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", required=price_required),
    }
    return SchemaDef(id=SchemaId(uuid7()), origin="user", status="active", name="s", page_kind="detail", fields=fields)


def _page(head: str = "", body: str = "<h1>Widget One</h1><p>Made of wood.</p>") -> str:
    return f"<html lang='en'><head>{head}</head><body>{body}</body></html>"


def _json_ld(node: dict[str, object]) -> str:
    return f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **node})}</script>'


def _state(values: int) -> str:
    blob = {"page": {"items": [{"id": n, "label": f"v{n}"} for n in range(values // 2)]}}
    return f"<script>window.__STATE__ = {json.dumps(blob)};</script>"


OFFER = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}


@pytest.mark.parametrize(
    ("html", "shown"),
    [
        pytest.param(_page(), False, id="nothing"),
        pytest.param(_page(_json_ld({"@type": "Product", "name": "W", "offers": OFFER})), True, id="product-offer"),
        pytest.param(_page(_json_ld({"@type": "Product", "name": "W"})), False, id="product-without-offers"),
        pytest.param(_page('<meta property="product:price:amount" content="19.90">'), True, id="ogp-price"),
        pytest.param(_page(_state(STATE_MIN_VALUES)), True, id="state-blob"),
        pytest.param(_page(_state(4)), False, id="settings-object"),
        pytest.param(_page(body="<h1>Widget One</h1><p>19,90 €</p>"), True, id="heading-and-price"),
        pytest.param(_page(body="<p>Widget One</p><p>19,90 €</p>"), False, id="price-without-heading"),
    ],
)
def test_offer_shown_reads_cheap_signals(html: str, shown: bool) -> None:
    assert offer_shown(ParsedPage(html)) is shown


def test_a_state_blob_says_the_page_renders_by_script() -> None:
    assert holds_state(ParsedPage(_page(_state(STATE_MIN_VALUES))))
    assert not holds_state(ParsedPage(_page()))


@dataclass
class Rung:
    method: CaptureMethod
    body: str
    calls: list[str] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append(url)
        raw = self.body.encode()
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=url,
            final_url=url,
            fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
            method=self.method,
            status_code=200,
            block_class="ok",
            headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
            timings_ms={"total": 1},
            html_sha256=sha256_hex(raw),
            network_bodies=(),
            fetch_policy=policy.model_dump(mode="json"),
            engine_version="test",
        )
        attempt = AttemptRecord(method=self.method, status=200, block_class="ok", duration_ms=1)
        return FetchResult(
            bundle=CaptureBundle(manifest=manifest, body=raw, network=()), duration_ms=1, attempts=(attempt,)
        )


RENDERED = _page(body="<h1>Widget One</h1><p>19,90 €</p>")


def _fetch(http: str, check: RenderNeed, deadline: float | None = None) -> tuple[FetchResult, Rung]:
    browser = Rung("browser", RENDERED)
    rungs = Rungs(http=Rung("http", http), browser=browser)
    policy = FetchPolicy(page_kind="detail")
    return asyncio.run(acquire(URL, policy, "http", rungs, needs_render=check, deadline=deadline)), browser


@pytest.mark.parametrize(
    ("http", "check", "method"),
    [
        pytest.param(_page(), RenderNeed(_schema()), "browser", id="no-signal"),
        pytest.param(RENDERED, RenderNeed(_schema()), "http", id="signal"),
        pytest.param(_page(), RenderNeed(_schema(price_required=False)), "http", id="price-not-required"),
        pytest.param(RENDERED, RenderNeed(_schema(), frozenset({"title"})), "browser", id="render-fields"),
    ],
)
def test_the_browser_is_the_exception(http: str, check: RenderNeed, method: CaptureMethod) -> None:
    result, _ = _fetch(http, check)
    assert result.method == method


def test_no_render_starts_too_close_to_the_deadline() -> None:
    result, browser = _fetch(_page(), RenderNeed(_schema()), deadline=time.monotonic() + BROWSER_MIN_S - 1)
    assert result.method == "http"
    assert browser.calls == []


VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
DATA = EngineData(
    vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ("jsonld", "microdata", "og")), calibration=None
)


@pytest.mark.parametrize(
    ("method", "head", "status"),
    [
        pytest.param("http", _state(STATE_MIN_VALUES), "interaction_required", id="http-script-rendered"),
        pytest.param("http", "", "missing", id="http-static"),
        pytest.param("browser", _state(STATE_MIN_VALUES), "missing", id="rendered"),
    ],
)
def test_a_field_missing_from_a_script_rendered_http_page_needs_interaction(
    method: CaptureMethod, head: str, status: str
) -> None:
    page = asyncio.run(Rung(method, _page(head))(URL, FetchPolicy()))
    result = asyncio.run(extract_page(page.bundle, _schema(), None, None, data=DATA))
    assert result.entity is not None
    assert result.entity["price"].status == status
