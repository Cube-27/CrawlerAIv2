"""Acquisition result types (SPEC-02 §4.2)."""

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.storage.capture_bundle import BlockClass, CaptureBundle, CaptureManifest, CaptureMethod, Headers


def _bundle(method: CaptureMethod = "http", block_class: BlockClass = "shell") -> CaptureBundle:
    body = b"<html></html>"
    return CaptureBundle(
        manifest=CaptureManifest(
            capture_id=uuid.UUID("0192f0c8-7b1e-7000-8000-000000000002"),
            url="https://www.example.com/p",
            final_url="https://www.example.com/p",
            fetched_at=datetime(2026, 10, 13, tzinfo=UTC),
            method=method,
            status_code=200,
            block_class=block_class,
            headers=Headers(request=(), response=()),
            timings_ms={"total": 120},
            html_sha256=hashlib.sha256(body).hexdigest(),
            network_bodies=(),
            fetch_policy=FetchPolicy().model_dump(mode="json"),
            engine_version="test",
        ),
        body=body,
        network=(),
    )


def test_result_reads_method_and_block_class_from_its_bundle() -> None:
    attempt = AttemptRecord(method="http", status=200, block_class="shell", duration_ms=120)
    result = FetchResult(bundle=_bundle("http", "shell"), duration_ms=120, attempts=(attempt,))
    assert (result.method, result.block_class) == ("http", "shell")


def test_result_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValidationError, match="attempts"):
        FetchResult(bundle=_bundle(), duration_ms=0, attempts=())


def test_attempt_records_a_failure_without_a_status() -> None:
    attempt = AttemptRecord(method="http", status=None, block_class="error", duration_ms=5, error="ssrf_rejected")
    assert AttemptRecord.model_validate_json(attempt.model_dump_json()) == attempt


def test_policy_round_trips_through_the_manifest_json() -> None:
    policy = FetchPolicy(method_hint="browser", timeout_s=5.0, locale_hint="de-CH")
    assert FetchPolicy.model_validate(policy.model_dump(mode="json")) == policy


@pytest.mark.parametrize("field", ["timeout_s", "browser_timeout_s", "max_body_bytes", "max_decompressed_bytes"])
def test_policy_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        FetchPolicy.model_validate({field: 0})
