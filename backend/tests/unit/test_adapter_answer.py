"""An adapter's answer recorded as JSON (acquisition spec, "Structural outcome classification (INV-24)"): the recorded
body is UTF-8 JSON text, so it decodes as that, whatever charset the platform's own answer declared."""

import time
from datetime import UTC, datetime

from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.answer import recorded


def _answer(content_type: str) -> FetchResult:
    return fetch_result(
        url="https://jobs.example.test/feed",
        method="api",
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=Exchange(
            url="https://jobs.example.test/feed",
            status=200,
            request_headers=(),
            response_headers=(("Content-Type", content_type), ("ETag", '"v1"')),
        ),
        content=Content(body="<feed><city>Zürich</city></feed>".encode("iso-8859-1")),
        block_class="ok",
        error=None,
    )


def test_a_recorded_answer_decodes_as_utf8_json_whatever_charset_the_feed_declared() -> None:
    result = recorded(_answer("text/xml; charset=ISO-8859-1"), {"city": "Zürich"})

    assert "Zürich" in result.bundle.text
    assert ("ETag", '"v1"') in result.bundle.manifest.headers.response  # the other headers stay as answered
