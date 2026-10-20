"""HTML fragments a page fetched (acquisition spec, "Network body capture"; extraction spec, "Source documents"): the
browser keeps a same-site fetch's or XMLHttpRequest's HTML answer, and a partial whose text the page does not show is
appended to the page, so its values and rows are read as the page's.

Captures are synthetic, on `.test` hosts; the browser's responses are stand-ins with the attributes the capture reads.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from crawlerai.acquire import browser
from crawlerai.collect.xhr import network_documents
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, sha256_hex

URL = "https://shop.example.test/c/1"
_PAGE = "<html><body><h1>Tables</h1><p>Shown already</p></body></html>"


def _response(url: str, content_type: str, resource_type: str = "fetch") -> Any:
    request = SimpleNamespace(url=url, resource_type=resource_type, frame=None, is_navigation_request=lambda: False)
    return SimpleNamespace(url=url, request=request, headers={"content-type": content_type})


def test_the_browser_keeps_same_site_html_answers_of_fetch_and_xhr_calls() -> None:
    calls = browser.DataCalls()
    frame: Any = SimpleNamespace(url=URL)
    kept = _response("https://shop.example.test/f/1", "text/html; charset=utf-8")
    other_site = _response("https://ads.example.org/f/1", "text/html")
    iframe = _response("https://shop.example.test/embed", "text/html", resource_type="document")
    flight = _response("https://cdn.example.org/rsc", "text/x-component")

    for response in (kept, other_site, iframe, flight):
        calls.on_response(response, frame)

    assert [response for response, _ in calls.responses] == [kept, flight]


def _page(answers: list[tuple[str, str]]) -> ParsedPage:
    body = _PAGE.encode()
    data = [markup.encode() for _, markup in answers]
    entries = tuple(
        NetworkBody(
            url=url,
            status=200,
            content_type="text/html",
            sha256=sha256_hex(answer),
            file=f"network/{i + 1:04d}.json",
            method="GET",
            resource_type="fetch",
        )
        for i, ((url, _), answer) in enumerate(zip(answers, data, strict=True))
    )
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=URL,
        final_url=URL,
        fetched_at=datetime(2026, 10, 20, tzinfo=UTC),
        method="browser",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("content-type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(body),
        network_bodies=entries,
        fetch_policy={},
        engine_version="test",
    )
    return ParsedPage.of(CaptureBundle(manifest=manifest, body=body, network=tuple(data)))


def test_a_partial_the_page_does_not_show_is_read_as_part_of_the_page() -> None:
    cards = "".join(f"<li class='card'><a href='/p/{i}'>Table {i}</a> <b>{i}9.00</b></li>" for i in range(4))
    page = _page(
        [
            (f"{URL}/more", f"<ul class='grid'>{cards}</ul>"),
            (f"{URL}/shown", "<p>Shown already</p>"),
            (f"{URL}/visit", "<!doctype html><html><body><p>Another page</p></body></html>"),
        ]
    )

    assert page.cleaned_text.text.split("\n") == ["Tables", "Shown already", *(f"Table {i} {i}9.00" for i in range(4))]
    (group, *_) = page.item_groups
    assert [item.text_content() for item in group] == [f"Table {i} {i}9.00" for i in range(4)]
    diagnostics: list[str] = []
    assert network_documents(page, diagnostics) == []
    assert diagnostics == []
