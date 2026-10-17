"""One browser render for a listing whose HTTP capture gives no rows (owner #54): the render check runs the page's own
extraction, renders an `auto` HTTP `ok` listing that gives none, and keeps the render only when its extraction gives
rows. Each extraction it ran is kept for the capture, so role C is asked at most once per capture.

The rungs are stubs answering synthetic pages on RFC 2606 hosts; role C is a stub that reads no rows (C3, C9).
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest

from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.resolve import pipeline
from crawlerai.resolve.pipeline import EngineData, GapReply, GapRequest, ListingGapReply, ListingGapRequest
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.services import scrape_steps
from crawlerai.services.scrape_steps import ContentCheck
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
DATA = EngineData(
    vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ("jsonld", "microdata", "og")), calibration=None
)
ORIGIN = "https://shop.example.test"
URL = f"{ORIGIN}/c/kettles"
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="listing",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "url": FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
    },
)


def _links(*paths: str) -> str:
    return "".join(f'<li><a href="{ORIGIN}{path}">{path}</a></li>' for path in paths)


# A client-rendered listing as HTTP serves it: an empty grid its scripts fill, beside repeated linked blocks that are
# not its items (related posts, filters).
TEMPLATE = (
    "<!doctype html><html lang='en'><head><title>Kettles</title></head><body><main><h1>Kettles</h1>"
    "<div id='grid'></div>"
    f"<aside><h2>Related posts</h2><ul>{_links('/blog/one', '/blog/two', '/blog/three')}</ul></aside>"
    f"<nav><ul>{_links('/c/kettles?colour=blue', '/c/kettles?colour=red', '/c/kettles?colour=grey')}</ul></nav>"
    "</main></body></html>"
)


def _listing(*names: str) -> str:
    """A listing whose rows are the items of a schema.org ItemList."""
    items = [
        {"@type": "ListItem", "position": n, "item": {"@type": "Product", "name": name, "url": f"{ORIGIN}/p/{n}"}}
        for n, name in enumerate(names, start=1)
    ]
    node = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items}
    script = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    return TEMPLATE.replace("</head>", f"{script}</head>")


ROWS = _listing("Blue kettle", "Red kettle", "Grey kettle")


@dataclass
class Rung:
    """Answers every URL `ok` with `body`, and records the calls it got."""

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


@dataclass
class RoleC:
    """Role C that reads no rows, recording the page text of each listing it was asked about."""

    asked: list[str] = field(default_factory=list)

    async def detail(self, request: GapRequest) -> GapReply:
        raise AssertionError("a listing asks no detail gaps")

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        self.asked.append(request.page.html)
        return ListingGapReply(candidates=(), llm_calls=())


def _fetch(
    http: str, browser: str, hint: Literal["auto", "http"] = "auto"
) -> tuple[FetchResult, ContentCheck, RoleC, Rung]:
    role_c = RoleC()
    check = ContentCheck(SCHEMA, DATA, role_c=role_c)
    render = Rung("browser", browser)
    rungs = Rungs(http=Rung("http", http), browser=render)
    result = asyncio.run(acquire(URL, FetchPolicy(method_hint=hint), "http", rungs, needs_render=check))
    return result, check, role_c, render


def _titles(check: ContentCheck, result: FetchResult) -> list[object]:
    extraction = check.extraction(result.bundle)
    assert extraction is not None
    return [row["title"].value for row in extraction.rows]


def test_a_client_template_listing_with_other_repeated_links_is_rendered_and_keeps_the_renders_rows() -> None:
    result, check, role_c, render = _fetch(TEMPLATE, ROWS)

    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("browser", "ok")]
    assert result.method == "browser"
    assert render.calls == [URL]
    assert _titles(check, result) == ["Blue kettle", "Red kettle", "Grey kettle"]
    # Role C read the HTTP page, which had no structured rows; the render's ItemList needed no role C.
    assert role_c.asked == [TEMPLATE]


def test_a_listing_with_rows_at_http_is_not_rendered() -> None:
    result, check, role_c, render = _fetch(ROWS, ROWS)

    assert [a.method for a in result.attempts] == ["http"]
    assert render.calls == []
    assert _titles(check, result) == ["Blue kettle", "Red kettle", "Grey kettle"]
    assert role_c.asked == []


def test_method_http_never_renders() -> None:
    result, _check, role_c, render = _fetch(TEMPLATE, ROWS, hint="http")

    assert [a.method for a in result.attempts] == ["http"]
    assert render.calls == []
    assert role_c.asked == []


def test_a_render_with_no_more_rows_than_http_is_not_kept() -> None:
    result, check, role_c, render = _fetch(TEMPLATE, TEMPLATE)

    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("browser", "ok")]
    assert result.method == "http"
    assert render.calls == [URL]
    assert _titles(check, result) == []
    # One role C call per capture: the HTTP page's and the render's, never a second on either.
    assert role_c.asked == [TEMPLATE, TEMPLATE]


def test_the_check_keeps_the_extraction_and_parse_of_each_capture_it_read() -> None:
    # INV-26 and one role C call per capture: whichever capture is kept is extracted from the check's results.
    result, check, _role_c, _render = _fetch(TEMPLATE, ROWS)

    extraction = check.extraction(result.bundle)
    assert extraction is not None
    assert extraction is check.extraction(result.bundle)
    assert check.parse(result.bundle).html == ROWS


def test_a_render_whose_extraction_fails_is_not_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    # D-1248: a failed extraction gives no rows, so the render is not kept over the HTTP page.
    real = pipeline.extract_page

    async def failing_render(bundle: CaptureBundle, *args: Any, **kwargs: Any) -> ExtractionResult:
        if bundle.manifest.method == "browser":
            return ExtractionResult(
                outcome="error", entity=None, rows=(), candidates=(), llm_calls=(), mode="adhoc", record_confidence=None
            )
        return await real(bundle, *args, **kwargs)

    monkeypatch.setattr(scrape_steps, "extract_page", failing_render)

    result, check, _role_c, render = _fetch(TEMPLATE, ROWS)

    assert render.calls == [URL]
    assert result.method == "http"
    extraction = check.extraction(result.bundle)
    assert extraction is not None
    assert extraction.outcome != "error"
