"""The HTML structure pre-passes (extraction spec, "Source documents"): a declarative shadow root's content under its
host, a streamed Suspense segment in the boundary a `$RC` call completed, and an eager Turbo frame's answer in the
frame, fetched by the HTTP rung as a same-site companion call. Pages are synthetic (`example.test`, C3, C9); nothing
goes to the network and no script runs."""

import asyncio
import time
from datetime import UTC, datetime

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.memory import Remembered
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.collect.dom import DomCollector
from crawlerai.collect.locator import parse_locator
from crawlerai.content.fragments import Frame, eager_frames
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=URL, page_url=URL, html_lang="en")
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={"brand": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name")},
)
_HTML = (("content-type", "text/html"),)


def test_a_declarative_shadow_root_is_read_as_its_hosts_content() -> None:
    page = ParsedPage(
        "<html><body><x-card><template shadowrootmode='open'>"
        "<table><tr><th>Brand</th><td>Example Brand</td></tr></table><slot></slot>"
        "</template><span>Light text</span></x-card>"
        # An ordinary template's content is inert: neither text nor a label-value pair.
        "<template><table><tr><th>Brand</th><td>Inert Brand</td></tr></table></template></body></html>"
    )

    assert page.cleaned_text.text.split("\n") == ["Brand Example Brand", "Light text"]
    [candidate] = DomCollector().collect(page, SCHEMA, CTX).candidates
    assert candidate.locator == "dom:/html[1]/body[1]/x-card[1]/table[1]/tbody[1]/tr[1]/td[1]"
    path = parse_locator(candidate.locator).parts[0]
    assert page.lxml_tree.xpath(f"string({path})") == "Example Brand"


_STREAMED = (
    "<html><body><main><!--$?--><template id='B:1'></template><p>Loading</p><!--/$--></main>"
    "<div hidden id='S:1'><p>Price 12.00</p></div><script>{call}</script></body></html>"
)


def test_a_completed_boundary_shows_its_streamed_segment_in_place_of_the_fallback() -> None:
    page = ParsedPage(_STREAMED.format(call='$RC("B:1","S:1")'))

    assert page.cleaned_text.text == "Price 12.00"
    assert page.lxml_tree.xpath("string(/html/body/main/p)") == "Price 12.00"


def test_a_boundary_rendered_on_the_client_keeps_its_fallback() -> None:
    page = ParsedPage(_STREAMED.format(call='$RX("B:1")'))

    # The segment stays hidden (`content.text.hidden`); the fallback is what the page shows.
    assert page.cleaned_text.text == "Loading"


_FRAMED = (
    "<html><body><turbo-frame id='x' src='/f'><p>Placeholder</p></turbo-frame>"
    "<turbo-frame id='y' src='/lazy' loading='lazy'><p>Later</p></turbo-frame>"
    "<turbo-frame id='z' src='https://other.example.org/f'></turbo-frame></body></html>"
)
_ANSWER = b"<html><body><turbo-frame id='x'><p>Price 9.50</p></turbo-frame></body></html>"


def test_eager_frames_are_planned_and_lazy_ones_are_not() -> None:
    assert eager_frames(_FRAMED, URL) == (
        Frame("x", "https://shop.example.test/f"),
        Frame("z", "https://other.example.org/f"),
    )


def _result(url: str, body: bytes, method: str = "http", sent: tuple[tuple[str, str], ...] = ()) -> FetchResult:
    return fetch_result(
        url=url,
        method="api" if method == "api" else "http",
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=Exchange(url=url, status=200, request_headers=sent, response_headers=_HTML),
        content=Content(body=body),
        block_class="ok",
        error=None,
    )


def test_an_eager_frame_is_fetched_on_the_pages_site_and_its_answer_replaces_the_frames_children() -> None:
    sent: list[JsonRequest] = []

    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        return _result(url, _FRAMED.encode())

    async def send(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        sent.append(request)
        return _result(request.url, _ANSWER, "api", request.headers)

    rungs = Rungs(http=http, browser=http, frames=eager_frames)
    result = asyncio.run(acquire(URL, FetchPolicy(), Remembered("http"), rungs, send=send))

    # The cross-site frame is not requested; the frame's request names it, as Turbo's does.
    assert [(r.url, dict(r.headers)["Turbo-Frame"], r.raw) for r in sent] == [
        ("https://shop.example.test/f", "x", True)
    ]
    assert [a.method for a in result.attempts] == ["http", "api"]
    page = ParsedPage.of(result.bundle)
    assert page.cleaned_text.text.split("\n") == ["Price 9.50", "Later"]
