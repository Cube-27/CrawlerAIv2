"""A queued job's webhook options (SPEC-10 §4.2), shared by the requests of `batch/scrape`, `crawl` and `extract`:
where to POST, which events, and how to group them (`crawlerai.db.webhook_outbox`)."""

from typing import Self

from pydantic import Field, field_validator, model_validator

from crawlerai.db.models import WebhookEventType
from crawlerai.db.webhook_outbox import ALL_EVENTS, JOB_END_EVENTS, WebhookBatch
from crawlerai.services.scrape_steps import Input, absolute_http_url


class WebhookOptions(Input):
    """`webhook_url` is POSTed the job's `webhook_events` (the job's end when not given), grouped by `webhook_batch`
    (one event a delivery when not given). The events and the batch take a `webhook_url`."""

    webhook_url: str | None = None
    webhook_events: list[WebhookEventType] = Field(default_factory=lambda: list(JOB_END_EVENTS), min_length=1)
    webhook_batch: WebhookBatch | None = None

    @field_validator("webhook_url")
    @classmethod
    def _absolute_webhook_url(cls, url: str | None) -> str | None:
        return None if url is None else absolute_http_url(url)

    @field_validator("webhook_events")
    @classmethod
    def _each_event_once(cls, events: list[WebhookEventType]) -> list[WebhookEventType]:
        # Stored in the order `WebhookEventType` names them, so two requests asking for the same events store one value.
        return [event for event in ALL_EVENTS if event in events]

    @model_validator(mode="after")
    def _batch_needs_a_url(self) -> Self:
        if self.webhook_batch is not None and self.webhook_url is None:
            raise ValueError("`webhook_batch` needs a `webhook_url`")
        return self
