"""What a fetch is asked to do and what it returns (SPEC-02 §4.2)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from crawlerai.storage.capture_bundle import BlockClass, CaptureBundle, CaptureMethod

__all__ = ["AttemptRecord", "BlockClass", "FetchPolicy", "FetchResult"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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


class AttemptRecord(_Frozen):
    """One rung tried. `status` is None when no response arrived (network error, timeout, SSRF rejection)."""

    method: CaptureMethod
    status: int | None
    block_class: BlockClass
    duration_ms: int
    error: str | None = None


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
