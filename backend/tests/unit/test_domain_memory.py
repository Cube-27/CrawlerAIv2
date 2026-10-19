"""What a fetch teaches the acquisition contract (`acquire.memory.lesson`, acquisition spec "Acquisition contract and
block history"), over every combination of the HTTP evidence, the challenge it named, whether the browser's cookies went
on to HTTP, and whether the render still lacks what the caller reads. The rows themselves are grounded at runtime.
"""

from datetime import UTC, datetime
from itertools import product
from typing import Literal

from crawlerai.acquire.memory import lesson, refused
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/item/1"
BODY = b"<html><body><h1>Item</h1></body></html>"
HTTP_OUTCOMES: tuple[tuple[BlockClass, int], ...] = (
    ("ok", 200),
    ("shell", 200),
    ("blocked", 403),
    ("blocked", 429),
    ("blocked", 503),
    ("error", 500),
)
HINTS: tuple[Literal["auto", "http", "browser"], ...] = ("auto", "http", "browser")


def _fetched(policy: FetchPolicy, kept: AttemptRecord, attempts: tuple[AttemptRecord, ...]) -> FetchResult:
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=URL,
        final_url=URL,
        fetched_at=datetime.now(UTC),
        method=kept.method,
        status_code=kept.status or 0,
        block_class=kept.block_class,
        headers=Headers(request=(), response=()),
        timings_ms={"total": 1},
        html_sha256=sha256_hex(BODY),
        network_bodies=(),
        fetch_policy=policy.model_dump(mode="json"),
        engine_version="test",
    )
    return FetchResult(bundle=CaptureBundle(manifest=manifest, body=BODY, network=()), duration_ms=2, attempts=attempts)


def test_a_contract_is_taught_only_by_an_auto_fetch_that_tried_http_and_a_handoff_only_by_a_passed_block() -> None:
    for (http_class, status), challenge, carried, lacks, hint in product(
        HTTP_OUTCOMES, (None, "vendor"), (False, True), (None, False, True), HINTS
    ):
        http = AttemptRecord(method="http", status=status, block_class=http_class, duration_ms=1, challenge=challenge)
        browser = AttemptRecord(method="browser", status=200, block_class="ok", duration_ms=1, site_session=carried)
        rendered = _fetched(FetchPolicy(method_hint=hint), browser, (http, browser))
        learned = lesson(rendered, lacks)
        if hint != "auto":
            assert learned is None
            continue
        assert learned is not None
        # A render the caller forced while HTTP held the page's core teaches nothing (its pages keep HTTP).
        assert lesson(rendered, lacks, forced=True) is None
        passed_block = refused(http)
        assert passed_block == (
            (http_class == "blocked" and status not in (429, 503)) or (http_class == "shell" and challenge is not None)
        )
        assert learned.handoff == (passed_block and carried)  # no data calls or steps: the network is empty
        assert learned.method == ("http" if learned.handoff else "browser")
        assert learned.needs_render == (not passed_block and http_class in ("ok", "shell"))
        assert learned.settle_on == {None: None, False: "content", True: None}[lacks]
        # A kept HTTP `ok` teaches the defaults; a fetch that never tried HTTP teaches nothing.
        assert lesson(_fetched(FetchPolicy(), http, (http,)), lacks) == (
            None if http_class != "ok" else type(learned)("http")
        )
        assert lesson(_fetched(FetchPolicy(), browser, (browser,)), lacks) is None
