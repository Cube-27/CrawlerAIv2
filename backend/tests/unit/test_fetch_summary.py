"""The summary of a page's fetch: the kept attempt's method, status and class, every attempt,
and, for an `api` capture, the platform adapter that reads it. The adapter is a stub on a synthetic host."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch, Shape
from crawlerai.adapters.registry import Registry
from crawlerai.core.capture import CaptureMethod
from crawlerai.services.page_formats import fetch_summary

PAGE = "https://board.example.test/tenant/jobs"
ENDPOINT = "https://board.example.test/api/tenant/jobs"
ATTEMPTS = (
    AttemptRecord(method="http", status=403, block_class="blocked", duration_ms=120, challenge="structural"),
    AttemptRecord(method="browser", status=200, block_class="ok", duration_ms=2400),
)


@dataclass
class _Board:
    name: str = "board"

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="tenant", page_kind="listing") if urlsplit(url).hostname else None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return urlsplit(endpoint).path.startswith(f"/api/{match.tenant}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        raise AssertionError("not fetched")

    def shapes(self, match: AdapterMatch, answer: JsonValue, /) -> tuple[Shape, ...]:
        return ()


def _summary(method: CaptureMethod, final_url: str, adapters: Registry | None) -> dict[str, object]:
    summary = fetch_summary(method, 200, "ok", ATTEMPTS, adapters=adapters, url=PAGE, final_url=final_url)
    return {"method": summary.method, "adapter": summary.adapter, "attempts": len(summary.attempts)}


def test_an_api_capture_names_the_adapter_that_reads_it() -> None:
    registry = Registry([_Board()])

    assert _summary("api", ENDPOINT, registry) == {"method": "api", "adapter": "board", "attempts": 2}


def test_every_attempt_keeps_its_challenge_label() -> None:
    summary = fetch_summary("browser", 200, "ok", ATTEMPTS, adapters=None, url=PAGE, final_url=PAGE)

    assert [(a.method, a.status, a.block_class, a.challenge) for a in summary.attempts] == [
        ("http", 403, "blocked", "structural"),
        ("browser", 200, "ok", None),
    ]
