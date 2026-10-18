"""One browser render for a listing whose HTTP capture may show more items once rendered (owner #54, master plan
2026-10-18 §3.1): the structural check (`content.render_need`, no extraction and no LLM call) renders an `auto` HTTP
`ok` listing whose document shows fewer than `MIN_ITEMS` item blocks, keeps more text from rendering than it renders,
or lists fewer structured items than it shows blocks; the render is kept only when the check no longer holds.

The rungs are stubs answering synthetic pages on RFC 2606 hosts (C3, C9).
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.content.render_need import listing_needs_render
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.services.scrape_steps import RenderNeed
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
NAMES = ("Blue kettle", "Red kettle", "Grey kettle", "Green kettle", "Black kettle")


def _cards(names: tuple[str, ...] = NAMES) -> str:
    return "".join(
        f'<li class="card"><a href="{ORIGIN}/p/{n}"><img src="/i/{n}.jpg" alt=""><span>{name}</span></a>'
        f"<span>19.90 EUR</span></li>"
        for n, name in enumerate(names, start=1)
    )


def _page(main: str, head: str = "") -> str:
    return (
        f"<!doctype html><html lang='en'><head><title>Kettles</title>{head}</head><body>"
        f"<main><h1>Kettles</h1>{main}</main><footer><p>{'About us. ' * 3}</p></footer></body></html>"
    )


def _item_list(count: int) -> str:
    items = [{"@type": "ListItem", "position": n, "url": f"{ORIGIN}/p/{n}"} for n in range(1, count + 1)]
    node = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items}
    return f'<script type="application/ld+json">{json.dumps(node)}</script>'


# A client-rendered listing as HTTP serves it: an empty grid its scripts fill.
TEMPLATE = _page("<div id='grid'></div><script>render()</script>")
GRID = _page(f"<ul>{_cards()}</ul>")
# A streamed document: its items arrive in a hidden segment that its script moves into place.
STREAMED = _page(f"<div id='grid'><p>Loading</p></div><div hidden id='S:0'><ul>{_cards()}</ul></div>")
# A structured list that names two of the five items the grid shows.
SHORT_LIST = _page(f"<ul>{_cards()}</ul>", head=_item_list(2))


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


def _fetch(http: str, browser: str, hint: Literal["auto", "http"] = "auto") -> tuple[FetchResult, RenderNeed, Rung]:
    check = RenderNeed(SCHEMA, DATA)
    render = Rung("browser", browser)
    rungs = Rungs(http=Rung("http", http), browser=render)
    result = asyncio.run(acquire(URL, FetchPolicy(method_hint=hint), "http", rungs, needs_render=check))
    return result, check, render


@pytest.mark.parametrize(
    ("page", "needs"),
    [
        pytest.param(TEMPLATE, True, id="no-item-blocks"),
        pytest.param(_page(f"<ul>{_cards(NAMES[:2])}</ul>"), True, id="fewer-blocks-than-a-listing"),
        pytest.param(STREAMED, True, id="hidden-text-outweighs-shown"),
        pytest.param(SHORT_LIST, True, id="structured-list-shorter-than-the-grid"),
        pytest.param(GRID, False, id="grid"),
        pytest.param(_page(f"<ul>{_cards()}</ul>", head=_item_list(5)), False, id="structured-list-of-the-grid"),
        pytest.param(_page(f"<ul>{_cards()}</ul><div hidden><p>Menu</p></div>"), False, id="small-hidden-part"),
        pytest.param(
            _page(f"<div itemscope itemtype='https://schema.org/Organization'><p>Shop</p></div><ul>{_cards()}</ul>"),
            False,
            id="one-microdata-item-is-no-list",
        ),
        pytest.param(_page(f"<ul style='display: none'>{_cards()}</ul><p>x</p>"), True, id="display-none-grid"),
    ],
)
def test_a_listing_needs_a_render_by_its_structure(page: str, needs: bool) -> None:
    assert listing_needs_render(ParsedPage(page)) is needs


def test_script_text_counts_as_neither_shown_nor_hidden() -> None:
    script = f"<script>{'var data = 1; ' * 500}</script>"
    assert listing_needs_render(ParsedPage(_page(f"<ul>{_cards()}</ul>{script}"))) is False


@pytest.mark.parametrize("http", [pytest.param(TEMPLATE, id="client-template"), pytest.param(STREAMED, id="streamed")])
def test_a_listing_needing_a_render_keeps_the_render_that_shows_its_items(http: str) -> None:
    result, _check, render = _fetch(http, GRID)

    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("browser", "ok")]
    assert result.method == "browser"
    assert render.calls == [URL]


def test_a_listing_that_shows_its_items_at_http_is_not_rendered() -> None:
    result, _check, render = _fetch(GRID, GRID)

    assert [a.method for a in result.attempts] == ["http"]
    assert render.calls == []


def test_method_http_never_renders() -> None:
    result, _check, render = _fetch(TEMPLATE, GRID, hint="http")

    assert [a.method for a in result.attempts] == ["http"]
    assert render.calls == []


def test_a_render_that_still_needs_one_is_not_kept() -> None:
    result, _check, render = _fetch(SHORT_LIST, SHORT_LIST)

    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("browser", "ok")]
    assert result.method == "http"
    assert render.calls == [URL]


def test_the_check_keeps_the_parse_of_each_capture_it_read() -> None:
    # INV-26: whichever capture is kept is extracted from the check's parse.
    result, check, _render = _fetch(TEMPLATE, GRID)

    kept = check.parse(result.bundle)
    assert kept is check.parse(result.bundle)
    assert kept.html == GRID


def test_a_render_that_lists_more_items_than_the_http_page_is_kept() -> None:
    # Owner #54: the capture with more rows is kept, here a render whose script wrote a structured list.
    result, _check, render = _fetch(TEMPLATE, _page("<div id='grid'></div>", head=_item_list(3)))

    assert result.method == "browser"
    assert render.calls == [URL]


@pytest.mark.parametrize(("blocked", "lost"), [(True, True), (False, False)])
def test_a_render_with_media_blocked_that_lists_fewer_items_marks_them_lost(blocked: bool, lost: bool) -> None:
    # Master plan 2026-10-18 §3.1: what the render did not load may be what shows the items; the site opts out.
    check = RenderNeed(SCHEMA, DATA)
    render = Rung("browser", TEMPLATE)
    rungs = Rungs(http=Rung("http", STREAMED), browser=render)
    policy = FetchPolicy(block_resources=blocked)

    result = asyncio.run(acquire(URL, policy, "http", rungs, needs_render=check))

    assert (result.method, render.calls) == ("http", [URL])
    assert check.lost_items is lost
