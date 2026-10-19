"""Data calls (acquisition spec, "Data calls"): a platform's documented product JSON joins the page only when it states
the requested product, and is then read as structured evidence with its documented minor unit; another product's
answer is refused, as a detail API recipe's is. The fetch path is grounded at runtime; this covers the identity check
and the unit on any product key and amount."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.identity import NOT_THE_PRODUCT, joined
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.collect.platform_json import PlatformJsonCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.api_recipe.execute import _identified
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, network_file
from crawlerai.storage.capture_bundle import sha256_hex as sha

HOST = "https://shop.example.test"
KEYS = st.from_regex(r"[a-z][a-z0-9]{2,8}-[a-z0-9]{2,8}", fullmatch=True)
CENTS = st.integers(min_value=1, max_value=10**9)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
SCHEMA = next(
    SchemaDef(id=SchemaId(uuid7()), origin="preset", status="active", **d.model_dump())
    for d in load_presets()
    if d.name == "commerce_detail"
)


def _capture(url: str, method: CaptureMethod, body: bytes, calls: tuple[tuple[str, bytes], ...] = ()) -> FetchResult:
    entries = tuple(
        NetworkBody(
            url=u, status=200, content_type="application/json", sha256=sha(b), file=network_file(i), method="GET"
        )
        for i, (u, b) in enumerate(calls)
    )
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
        fetched_at=datetime.now(UTC),
        method=method,
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("content-type", "application/json"),)),
        timings_ms={"total": 1},
        html_sha256=sha(body),
        network_bodies=entries,
        fetch_policy=FetchPolicy().model_dump(mode="json"),
        engine_version="test",
    )
    bundle = CaptureBundle(manifest=manifest, body=body, network=tuple(b for _, b in calls))
    attempt = AttemptRecord(method=method, status=200, block_class="ok", duration_ms=1)
    return FetchResult(bundle=bundle, duration_ms=1, attempts=(attempt,))


def _product(key: str, cents: int = 2900) -> bytes:
    # Shopify Ajax API product (its documentation, "Product"): prices in cents, one price for every variant.
    return json.dumps(
        {"handle": key, "title": "Item", "url": f"/products/{key}", "price": cents, "price_varies": False}
    ).encode()


@given(KEYS, KEYS, CENTS)
def test_a_documented_answer_joins_only_for_its_product_and_reads_in_major_units(
    key: str, other: str, cents: int
) -> None:
    page = f"{HOST}/products/{key}"
    http = _capture(page, "http", b"<html></html>")

    served, attempt = joined(http, _capture(f"{page}.js", "api", _product(key, cents)), key, "shopify")

    assert served is not None
    assert attempt.attempts[-1].error is None
    assert served.bundle.manifest.network_bodies[-1].data_call == "shopify"
    ctx = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC), html_lang="en-US", page_url=page, base_url=page)
    read = PlatformJsonCollector(VOCABULARY).collect(ParsedPage.of(served.bundle), SCHEMA, ctx)
    prices = [c.normalized for c in read.candidates if c.field == "price"]
    assert len(prices) == 1
    assert isinstance(prices[0], Ok)
    money = prices[0].value
    assert isinstance(money, dict)
    assert Decimal(str(money["amount"])) == Decimal(cents).scaleb(-2)
    if other != key:
        # Another product's answer (an endpoint that ignores its key) never joins, and says why.
        refused, attempt = joined(http, _capture(f"{page}.js", "api", _product(other)), key, "shopify")
        assert refused is None
        assert (attempt.block_class, attempt.attempts[-1].error) == ("error", NOT_THE_PRODUCT)
        # A detail API recipe's answer is checked the same way.
        recipe = _identified(_capture(f"{HOST}/api/p", "api", _product(other)), page, (key,))
        assert recipe.attempts[-1].error == NOT_THE_PRODUCT
