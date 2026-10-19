"""Data calls (acquisition spec, "Data calls"): the call a render made is kept with the page URL's key templated, it is
filled with the next page's key, and an answer that does not state the requested product never joins a page. The
fetch path is grounded at runtime; this covers the identity check on any product key."""

import json
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.replay import NOT_THE_PRODUCT, DataCall, KeyAt, joined, learned_call
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, network_file
from crawlerai.storage.capture_bundle import sha256_hex as sha

HOST = "https://shop.example.test"
KEYS = st.from_regex(r"[a-z][a-z0-9]{2,8}-[a-z0-9]{2,8}", fullmatch=True)


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


def _product(key: str) -> bytes:
    return json.dumps({"product": {"handle": key, "title": "Item", "price": 1}}).encode()


@given(KEYS, KEYS)
def test_a_kept_call_serves_the_next_product_and_never_another(first: str, second: str) -> None:
    page = f"{HOST}/products/{first}"
    rendered = _capture(page, "browser", b"<html></html>", ((f"{HOST}/api/p/{first}.json?x=1", _product(first)),))

    call = learned_call(rendered)

    assert call == DataCall(f"{HOST}/api/p/{{key}}.json?x=1", KeyAt("segment", "-1"))
    next_page = f"{HOST}/products/{second}"
    assert call.for_page(next_page) == (f"{HOST}/api/p/{second}.json?x=1", second)
    http = _capture(next_page, "http", b"<html></html>")
    served, attempt = joined(http, _capture(next_page, "api", _product(second)), second)
    assert served is not None
    assert served.bundle.network == (_product(second),)
    assert attempt.attempts[-1].error is None
    if first != second:
        # An answer for another product (a call that ignores the key) is dropped, and says why.
        refused, attempt = joined(http, _capture(next_page, "api", _product(first)), second)
        assert refused is None
        assert (attempt.block_class, attempt.attempts[-1].error) == ("error", NOT_THE_PRODUCT)


def test_a_call_whose_url_names_no_key_of_the_page_is_not_kept() -> None:
    page = f"{HOST}/products/blue-shirt"
    rendered = _capture(page, "browser", b"<html></html>", ((f"{HOST}/api/featured.json", _product("blue-shirt")),))

    assert learned_call(rendered) is None
