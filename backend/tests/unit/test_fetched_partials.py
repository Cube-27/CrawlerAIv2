"""HTML fragments a page fetched: the
browser keeps a same-site fetch's or XMLHttpRequest's HTML answer, and a partial whose text the page does not show is
appended to the page, so its values and rows are read as the page's.

Captures are synthetic, on `.test` hosts; the browser's responses are stand-ins with the attributes the capture reads.
"""

from types import SimpleNamespace
from typing import Any

from snowcrawl.acquire import browser_capture
from snowcrawl.collect.xhr import network_documents
from snowcrawl.content.fragments import is_partial
from snowcrawl.content.page import ParsedPage, prepassed
from tests.support.captures import calls, capture

URL = "https://shop.example.test/c/1"
_PAGE = "<html><body><h1>Tables</h1><p>Shown already</p><template><p>Kept aside</p></template></body></html>"


def _response(url: str, content_type: str, resource_type: str = "fetch", status: int = 200) -> Any:
    request = SimpleNamespace(url=url, resource_type=resource_type, frame=None, is_navigation_request=lambda: False)
    return SimpleNamespace(url=url, status=status, request=request, headers={"content-type": content_type})


def test_the_browser_keeps_same_site_html_answers_of_fetch_and_xhr_calls() -> None:
    calls = browser_capture.DataCalls()
    frame: Any = SimpleNamespace(url=URL)
    kept = _response("https://shop.example.test/f/1", "text/html; charset=utf-8")
    other_site = _response("https://ads.example.org/f/1", "text/html")
    iframe = _response("https://shop.example.test/embed", "text/html", resource_type="document")
    failed = _response("https://shop.example.test/f/2", "text/html", status=500)
    flight = _response("https://cdn.example.org/rsc", "text/x-component")

    for response in (kept, other_site, iframe, failed, flight):
        calls.on_response(response, frame)

    assert [response for response, _ in calls.responses] == [kept, flight]


def _page(answers: list[tuple[str, str]]) -> ParsedPage:
    network = calls(
        ((url, markup.encode()) for url, markup in answers),
        content_type="text/html",
        method="GET",
        resource_type="fetch",
    )
    return ParsedPage.of(
        capture(_PAGE.encode(), url=URL, method="browser", headers=(("content-type", "text/html"),), network=network)
    )


def test_a_partial_the_page_does_not_show_is_read_as_part_of_the_page() -> None:
    cards = "".join(f"<li class='card'><a href='/p/{i}'>Table {i}</a> <b>{i}9.00</b></li>" for i in range(4))
    page = _page(
        [
            (f"{URL}/more", f"<ul class='grid'>{cards}</ul>"),
            (f"{URL}/shown", "<p>Shown already</p>"),
            (f"{URL}/hidden", "<p hidden>Kept aside</p>"),
            (f"{URL}/aside", "<p>Kept aside</p>"),
            (f"{URL}/visit", "<!-- visit --><!doctype html><html><body><p>Another page</p></body></html>"),
        ]
    )

    rows = [f"Table {i} {i}9.00" for i in range(4)]
    assert page.cleaned_text.text.split("\n") == ["Tables", "Shown already", *rows, "Kept aside"]
    (group, *_) = page.item_groups
    assert [item.text_content() for item in group] == rows
    diagnostics: list[str] = []
    assert network_documents(page, diagnostics) == []
    assert diagnostics == []


def test_a_frames_answer_is_read_in_its_frame_only() -> None:
    framed = "<html><body><turbo-frame id='x' src='/f'></turbo-frame></body></html>"
    answer = "<turbo-frame id='x'><p>Price 9.50</p></turbo-frame><p>Footer</p>"

    html = prepassed(
        framed, URL, {("https://shop.example.test/f", "x"): answer}, [("https://shop.example.test/f", answer)]
    )

    assert "Price 9.50" in html
    assert "Footer" not in html


def test_a_partial_is_known_by_how_it_starts() -> None:
    assert is_partial("<div><script>document.write('<html>')</script></div>")
    assert not is_partial("\ufeff <!-- a --> <HTML lang='en'><body></body></HTML>")
