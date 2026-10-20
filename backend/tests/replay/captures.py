"""One synthetic capture of a page, for the replay tests that run `extract_page` over it."""

from datetime import UTC, datetime

from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, sha256_hex

PAGE_URL = "https://shop.example.test/p/1"


def capture(
    raw: bytes,
    *,
    url: str = PAGE_URL,
    final_url: str = PAGE_URL,
    api: bool = False,
    headers: tuple[tuple[str, str], ...] = (),
    calls: tuple[tuple[NetworkBody, bytes], ...] = (),
) -> CaptureBundle:
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=final_url,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="api" if api else "http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=headers or (("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=tuple(entry for entry, _ in calls),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=raw, network=tuple(body for _, body in calls))
