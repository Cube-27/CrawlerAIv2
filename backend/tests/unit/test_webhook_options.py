"""A queued job's webhook options (`services.webhook_options`, SPEC-10 §4.2), as each queued request kind takes
them."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.services.batch import BatchScrapeRequest
from crawlerai.services.crawl import CrawlRequest
from crawlerai.services.extract import ExtractRequest

URL = "https://shop.example.test/kettles/blue"
HOOK = "https://hooks.example.test/in"
BODIES: dict[type[Any], dict[str, Any]] = {
    BatchScrapeRequest: {"urls": [URL], "formats": ["markdown"]},
    CrawlRequest: {"url": URL, "formats": ["markdown"]},
    ExtractRequest: {"urls": [URL], "page_kind": "detail", "schema": {"fields": ["title"]}},
}
KINDS = list(BODIES)


@pytest.mark.parametrize("kind", KINDS)
def test_a_webhook_without_events_is_sent_the_jobs_end(kind: type[BatchScrapeRequest]) -> None:
    request = kind.model_validate({**BODIES[kind], "webhook_url": HOOK})

    assert request.webhook_events == ["job_completed", "job_failed", "job_cancelled"]
    assert request.webhook_batch is None


@pytest.mark.parametrize(
    ("options", "field"),
    [
        ({"webhook_url": HOOK, "webhook_events": []}, "webhook_events"),
        ({"webhook_url": HOOK, "webhook_events": ["task_fetched"]}, "webhook_events"),
        ({"webhook_batch": {"max_events": 10, "max_seconds": 5}}, ""),
        ({"webhook_url": HOOK, "webhook_batch": {"max_events": 0, "max_seconds": 5}}, "webhook_batch"),
        ({"webhook_url": HOOK, "webhook_batch": {"max_events": 10, "max_seconds": 0}}, "webhook_batch"),
        ({"webhook_url": "ftp://hooks.example.test/in"}, "webhook_url"),
    ],
)
def test_invalid_webhook_options_are_refused(options: dict[str, Any], field: str) -> None:
    body = {**BODIES[BatchScrapeRequest], **options}

    with pytest.raises(ValidationError) as invalid:
        BatchScrapeRequest.model_validate(body)

    assert {str(error["loc"][0]) if error["loc"] else "" for error in invalid.value.errors()} == {field}
