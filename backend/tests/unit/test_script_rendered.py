"""A detail page whose HTTP document carries its data for its script to render (`content.state.holds_state`): a field
missing from it that no render was run for is `interaction_required` (resolution spec).

Pages are synthetic (`example.test`); the rungs are stubs (C3, C9).
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.content.state import STATE_MIN_VALUES, holds_state
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/p/1"


def _schema() -> SchemaDef:
    fields = {
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
    }
    return SchemaDef(id=SchemaId(uuid7()), origin="user", status="active", name="s", page_kind="detail", fields=fields)


def _page(head: str = "", body: str = "<h1>Widget One</h1><p>Made of wood.</p>") -> str:
    return f"<html lang='en'><head>{head}</head><body>{body}</body></html>"


def _state(values: int) -> str:
    blob = {"page": {"items": [{"id": n, "label": f"v{n}"} for n in range(values // 2)]}}
    return f"<script>window.__STATE__ = {json.dumps(blob)};</script>"


def test_a_state_blob_says_the_page_renders_by_script() -> None:
    assert holds_state(ParsedPage(_page(_state(STATE_MIN_VALUES))))
    assert not holds_state(ParsedPage(_page()))


@dataclass
class Rung:
    method: CaptureMethod
    body: str
    calls: list[str] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append(url)
        raw = self.body.encode()
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=url,
            final_url=url,
            fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
            method=self.method,
            status_code=200,
            block_class="ok",
            headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
            timings_ms={"total": 1},
            html_sha256=sha256_hex(raw),
            network_bodies=(),
            fetch_policy=policy.model_dump(mode="json"),
            engine_version="test",
        )
        attempt = AttemptRecord(method=self.method, status=200, block_class="ok", duration_ms=1)
        return FetchResult(
            bundle=CaptureBundle(manifest=manifest, body=raw, network=()), duration_ms=1, attempts=(attempt,)
        )


VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
DATA = EngineData(
    vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ("jsonld", "microdata", "og")), calibration=None
)


@pytest.mark.parametrize(
    ("method", "head", "status"),
    [
        pytest.param("http", _state(STATE_MIN_VALUES), "interaction_required", id="http-script-rendered"),
        pytest.param("http", "", "missing", id="http-static"),
        pytest.param("browser", _state(STATE_MIN_VALUES), "missing", id="rendered"),
    ],
)
def test_a_field_missing_from_a_script_rendered_http_page_needs_interaction(
    method: CaptureMethod, head: str, status: str
) -> None:
    page = asyncio.run(Rung(method, _page(head))(URL, FetchPolicy()))
    result = asyncio.run(extract_page(page.bundle, _schema(), None, None, data=DATA))
    assert result.entity is not None
    assert result.entity["price"].status == status
