"""What a fetch is asked to do and what it returns."""

from datetime import timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    computed_field,
    field_serializer,
)

from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.context_digest import context_digest
from crawlerai.core.redaction import REDACTED
from crawlerai.db.models import PageKind
from crawlerai.storage.capture_bundle import CaptureBundle

__all__ = [
    "ActionsReport",
    "AttemptRecord",
    "BlockClass",
    "BrowserActions",
    "CallEndpoint",
    "FetchPolicy",
    "FetchResult",
    "PageStep",
    "PagedFetch",
    "PagingHint",
    "PolicyFields",
    "RequestContext",
    "StepOutcome",
    "StopReason",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# A caller's header or cookie: its name and secret value.
SecretPair = tuple[str, SecretStr]


class RequestContext(_Frozen):
    """The caller's own request context: headers the HTTP and JSON rungs send to the fetched URL's host, and
    cookies seeded as host-only cookies of that host. The values are secrets: every serialization
    shows them redacted, so neither a capture's manifest nor a log line holds one, beside their keyed digest
    (`core.context_digest`), so that a stored capture stands only for a fetch with the same values."""

    headers: tuple[SecretPair, ...] = ()
    cookies: tuple[SecretPair, ...] = ()

    # Serialized as the names alone, in one canonical form, so that a stored capture's context compares equal to a
    # request's whatever order the caller gave them in (`services.stored_captures`): sorted, and header names lowercased
    # (RFC 9110 §5.1: field names are case-insensitive; cookie names are not, RFC 6265 §4.1.1).
    @field_serializer("headers")
    def _redacted_headers(self, pairs: tuple[SecretPair, ...]) -> list[tuple[str, str]]:
        return [(name, REDACTED) for name in sorted(name.lower() for name, _ in pairs)]

    @field_serializer("cookies")
    def _redacted_cookies(self, pairs: tuple[SecretPair, ...]) -> list[tuple[str, str]]:
        return [(name, REDACTED) for name in sorted(name for name, _ in pairs)]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def digest(self) -> str:
        """The keyed digest of the names and values (`core.context_digest`)."""
        values = [(name, value.get_secret_value()) for name, value in self.headers]
        return context_digest(values, [(name, value.get_secret_value()) for name, value in self.cookies])

    def header_names(self) -> frozenset[str]:
        return frozenset(name.lower() for name, _ in self.headers)


# What a page step does: wait (milliseconds, an element, or no data call in flight), click (an element or
# visible text), scroll (to the end, by pixels, or until the document stops growing), press a key, or type text.
StepAction = Literal["wait", "click", "scroll", "press", "type"]
ScrollMode = Literal["end", "by", "stable"]


class PageStep(_Frozen):
    """One browser step as the browser rung runs it (`run_steps`), translated from the caller's vocabulary
    (`page_actions` in `config_ir`): an element is named by an XPath 1.0 expression, or by its visible `text` for a
    click. Each step ends within `timeout_ms`."""

    action: StepAction
    timeout_ms: PositiveInt
    xpath: str | None = None
    text: str | None = None
    ms: PositiveInt | None = None
    network_idle: bool = False
    scroll: ScrollMode | None = None
    px: int | None = None
    key: str | None = None


# How a step ended: done; its element never appeared, or never became actionable, within its timeout; refused (a
# credential field); the browser failed it; or not run, after an earlier step that did not complete.
StepResult = Literal["done", "not_found", "timeout", "refused", "error", "skipped"]


class StepOutcome(_Frozen):
    action: StepAction
    outcome: StepResult


class CallEndpoint(_Frozen):
    """A data call endpoint a located `call` field source names: its
    request method, origin and path segments, None for a segment its recipe fills from the page. The browser's ready
    wait ends once each named endpoint has answered."""

    method: str
    origin: str
    segments: tuple[str | None, ...]

    def matches(self, method: str, url: str) -> bool:
        """Whether a request of `method` to `url` is a call of this endpoint (the query is the recipe's to fill)."""
        parts = urlsplit(url)
        segments = parts.path[1:].split("/") if parts.path else []
        return (
            method.upper() == self.method
            and f"{parts.scheme}://{parts.netloc}" == self.origin
            and len(segments) == len(self.segments)
            and all(want is None or want == got for want, got in zip(self.segments, segments, strict=True))
        )


class PolicyFields[Context: BaseModel](_Frozen):
    """What a fetch is asked to do, with its caller's request context as `Context`: the `RequestContext` itself for a
    fetch to make (`FetchPolicy`), or its serialized form for one a capture keeps (`stored_fetch.StoredFetch`)."""

    method_hint: Literal["auto", "http", "browser"] = "auto"
    proxy_pool: str | None = None
    # Obey robots.txt: off unless the request switches it on, and then no
    # robots.txt request is sent.
    respect_robots: bool = False
    timeout_s: PositiveFloat = 10.0
    browser_timeout_s: PositiveFloat = 45.0
    max_body_bytes: PositiveInt = 10_000_000
    max_decompressed_bytes: PositiveInt = 50_000_000
    # The request's locale (BCP 47), for the normalizers' context and the browser context's `locale` and `timezone_id`.
    locale_hint: str | None = None
    page_kind: PageKind | None = None  # the kind the task fetches the page as, which `classify` reads
    # The schema.org types the task reads the page for (`target_types` of `schemas.paths`) and their subtypes in the
    # pinned vocabulary, which a referring adapter weighs and
    # `classify` reads a document's structured data for; empty when no schema reads the page.
    target_types: tuple[str, ...] = ()
    # The task reads the page for content formats only (`markdown`, `markdown_fit`, `chunks`) and no records: the
    # page's rendered text is what it reads, so `classify` judges a shell by it.
    content_only: bool = False
    # A soft row target for a list an adapter's API serves in pages: its walk ends once it has at least this many rows
    # (whole pages are kept); None asks for every page, up to the adapters' hard cap (`adapters.paging.MAX_ROWS`).
    max_rows: PositiveInt | None = None
    # The caller's headers and cookies, and the page steps the browser runs before it reads the page.
    context: Context | None = None
    steps: tuple[PageStep, ...] = ()
    # Browser only: the data call endpoints the site's located `call` field sources name; the page is ready once each
    # has answered, else once no data call is in flight.
    ready_calls: tuple[CallEndpoint, ...] = ()
    # Files the browser makes of the rendered page, stored beside the capture (`storage.artifacts`): a PNG of the
    # viewport or of the whole page, and a PDF print. Either needs the browser rung (`method_hint` `browser`).
    screenshot: Literal["viewport", "full_page"] | None = None
    pdf: bool = False

    @property
    def captures_page(self) -> bool:
        """Whether the fetch must end on the rendered page itself, for a file the browser makes of it."""
        return self.screenshot is not None or self.pdf


class FetchPolicy(PolicyFields[RequestContext]):
    """What a fetch is asked to do, with the caller's own request context."""


class AttemptRecord(_Frozen):
    """One rung tried. `status` is None when no response arrived (network error, timeout, SSRF rejection)."""

    method: CaptureMethod
    status: int | None
    block_class: BlockClass
    duration_ms: int
    error: str | None = None
    # The anti-bot challenge its response presents, when the fetch did not keep it as `ok`: a vendor named by
    # the adapter package's signatures, or `structural` (`acquire.challenge`). Recorded only.
    challenge: str | None = None
    # The pause its response's `Retry-After` asked for (RFC 9110 §10.2.3), from when the fetch began: an HTTP-date is
    # measured from `fetched_at`, so the pause is never shorter than asked. Read by the politeness step whichever
    # attempt's outcome is kept; not stored, as the response's other headers are not.
    retry_after: timedelta | None = Field(default=None, exclude=True)
    # This browser `ok` opened a site session with its cookies (`acquire.session`): when it was needed only to
    # pass a block, the site's contract keeps its pages on HTTP (`acquire.memory`, handoff). In memory only, like
    # `retry_after`.
    site_session: bool = Field(default=False, exclude=True)
    # The bytes the attempt moved both ways (`outcome.Traffic`), which `proxy_bytes` usage counts for a fetch through a
    # pool. Not stored, as the attempt's other wire details are not.
    transferred: int = Field(default=0, ge=0, exclude=True)
    # How each of the policy's page steps ended, in order, on the browser attempt that ran them.
    steps: tuple[StepOutcome, ...] = ()
    # An `api` attempt that was a detail page's data call (`acquire.identity`): the platform whose documented product
    # JSON it requested. Stored only on such an attempt.
    data_call: str | None = None


class FetchResult(_Frozen):
    bundle: CaptureBundle  # its manifest holds the method and block class of the kept outcome
    duration_ms: int
    attempts: Annotated[tuple[AttemptRecord, ...], Field(min_length=1)]
    # The files the browser made of the page, by artifact name (`storage.artifacts`); in memory until the capture is
    # stored, never part of the bundle.
    artifacts: dict[str, bytes] = Field(default_factory=dict, exclude=True)

    @property
    def method(self) -> CaptureMethod:
        return self.bundle.manifest.method

    @property
    def block_class(self) -> BlockClass:
        return self.bundle.manifest.block_class


# Owner #52: the paging mechanisms a caller may name for a listing scrape's browser actions.
PagingHint = Literal["load_more", "show_more", "pagination", "next", "scroll"]
# Why a listing's browser actions stopped (`crawl.paging`): the row target was reached, the list ended, the page showed
# no item group, no mechanism grew it, a cap was reached, an overlay took a click, the next page was not admitted
# (robots.txt, or another host), or a document state could not be kept.
StopReason = Literal[
    "records", "end", "no_items", "no_mechanism", "action_cap", "time_cap", "click_intercepted", "not_admitted", "error"
]


class BrowserActions(_Frozen):
    """A single-URL listing scrape's browser actions. `records` is a soft target: the run stops once it
    has seen at least that many rows, so it may pass it by one page or batch. Without a `hint` the mechanism is
    detected."""

    records: PositiveInt = 100
    hint: PagingHint | None = None


class ActionsReport(_Frozen):
    """What a listing's browser actions did: the mechanism that grew the list (None when none did), why they stopped,
    the actions taken, the document states kept and the distinct items seen."""

    mechanism: PagingHint | None
    stop: StopReason
    actions: int
    pages: int
    items: int


class PagedFetch(_Frozen):
    """A listing fetched with browser actions: each kept document state as a fetch result of its own, in order (the
    first holds the navigation's attempt), and the report; None when the page was not reached, so nothing was done."""

    pages: Annotated[tuple[FetchResult, ...], Field(min_length=1)]
    report: ActionsReport | None
