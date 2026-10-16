"""What a fetch is asked to do and what it returns (SPEC-02 §4.2)."""

from datetime import timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PositiveFloat, PositiveInt, model_validator

from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import PageKind
from crawlerai.storage.capture_bundle import CaptureBundle

__all__ = [
    "AttemptRecord",
    "BlockClass",
    "FetchPolicy",
    "FetchResult",
    "Validators",
    "check_robots_override",
    "policy_with_attempts",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def check_robots_override(respect_robots: bool, reason: str | None) -> None:
    """Ignoring robots.txt is an operator's decision, recorded with its reason (ARCHITECTURE §7.1)."""
    if not respect_robots and not (reason or "").strip():
        raise ValueError("respect_robots=false needs a robots_override_reason")


class FetchPolicy(_Frozen):
    method_hint: Literal["auto", "http", "browser"] = "auto"
    proxy_pool: str | None = None
    respect_robots: bool = True  # false only via an operator override, recorded on job.request
    robots_override_reason: str | None = None
    timeout_s: PositiveFloat = 30.0
    browser_timeout_s: PositiveFloat = 45.0
    max_body_bytes: PositiveInt = 10_000_000
    max_decompressed_bytes: PositiveInt = 50_000_000
    capture_network_json: bool = True  # browser only
    locale_hint: str | None = None  # request locale, for the normalizers' context
    page_kind: PageKind | None = None  # the kind the task fetches the page as, which `classify` reads

    @model_validator(mode="after")
    def _override_has_a_reason(self) -> "FetchPolicy":
        check_robots_override(self.respect_robots, self.robots_override_reason)
        return self


class Validators(_Frozen):
    """What a page last answered with, sent back so that an unchanged page answers 304 with no body (RFC 9110 §13.1).
    Each value is kept as received: an entity tag is opaque, and If-Modified-Since repeats the date exactly."""

    etag: str | None
    last_modified: str | None


class AttemptRecord(_Frozen):
    """One rung tried. `status` is None when no response arrived (network error, timeout, SSRF rejection)."""

    method: CaptureMethod
    status: int | None
    block_class: BlockClass
    duration_ms: int
    error: str | None = None
    # The pause its response's `Retry-After` asked for (RFC 9110 §10.2.3), from when the fetch began: an HTTP-date is
    # measured from `fetched_at`, so the pause is never shorter than asked. Read by the politeness step whichever
    # attempt's outcome is kept; not stored, as the response's other headers are not.
    retry_after: timedelta | None = Field(default=None, exclude=True)


class FetchResult(_Frozen):
    bundle: CaptureBundle  # its manifest holds the method and block class of the kept outcome
    duration_ms: int
    attempts: Annotated[tuple[AttemptRecord, ...], Field(min_length=1)]

    @property
    def method(self) -> CaptureMethod:
        return self.bundle.manifest.method

    @property
    def block_class(self) -> BlockClass:
        return self.bundle.manifest.block_class


def policy_with_attempts(
    fetch_policy: dict[str, JsonValue], attempts: tuple[AttemptRecord, ...]
) -> dict[str, JsonValue]:
    """`fetch_policy` with every rung tried as `attempts`, as the bundle manifest and the `capture` row keep it
    (SPEC-02 §4.4)."""
    return {**fetch_policy, "attempts": [attempt.model_dump(mode="json") for attempt in attempts]}


def fetched_as(fetch_policy: dict[str, JsonValue]) -> PageKind | None:
    """The page kind a capture was fetched as (the `page_kind` of its `FetchPolicy`, which its manifest keeps); None
    for one fetched without a page kind, or before the manifest kept it."""
    match fetch_policy.get("page_kind"):
        case "detail":
            return "detail"
        case "listing":
            return "listing"
    return None
