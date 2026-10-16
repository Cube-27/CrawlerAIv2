"""Failure classes of extraction replayed through `extract_page` on synthetic captures (SPEC-05 §4.5 to §4.8): each
test builds the class's page shape on `example.test` names (C3, C9) and checks what the commerce preset publishes."""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


def _extract(head: str, body: str = "") -> ExtractionResult:
    raw = f"<html><head>{head}</head><body>{body}</body></html>".encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=PAGE_URL,
        final_url=PAGE_URL,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return asyncio.run(
        extract_page(CaptureBundle(manifest=manifest, body=raw, network=()), SCHEMA, None, None, data=DATA)
    )


def _jsonld(*nodes: Mapping[str, Any]) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(node)}</script>' for node in nodes)


def _outcomes(result: ExtractionResult, *names: str) -> dict[str, tuple[str, str | None, JsonValue]]:
    assert result.entity is not None
    return {name: (result.entity[name].status, result.entity[name].reason, result.entity[name].value) for name in names}


def test_state_admission_stays_linear_in_values_and_anchors() -> None:
    # 2,000 gallery images give the image field 2,000 anchors, and 10,000 distinct state strings are tried against
    # them: 20 million url equalities pairwise, one key lookup per value with an equality-key index.
    images = [f"https://cdn.example.test/img/{i}.jpg" for i in range(2_000)]
    product = {"@context": "https://schema.org", "@type": "Product", "name": "Synthetic Widget", "image": images}
    state = [f"https://cdn.example.test/img/{i % 4_000}.jpg?w={i}" for i in range(10_000)]
    head = _jsonld(product) + f"<script>window.__STATE__ = {json.dumps(state)};</script>"

    started = time.perf_counter()
    result = _extract(head)
    elapsed = time.perf_counter() - started

    assert _outcomes(result, "title") == {"title": ("published", None, "Synthetic Widget")}
    assert elapsed < 20
