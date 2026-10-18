"""What a page states about itself and links to (SPEC-15 §4.2): its final URL, canonical link and `og:url`, and the
absolute targets of its links, read from the document by the HTML rules (base URL, link relations)."""

import time
from datetime import UTC, datetime

from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.page_refs import MAX_LINKS, canonical_link, page_refs
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import PageRefs

FINAL = "https://careers.example.test/en/jobs"


def _page(html: str, final: str = FINAL) -> FetchResult:
    return fetch_result(
        url="https://careers.example.test/",
        method="http",
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=Exchange(url=final, status=200, request_headers=(), response_headers=(("Content-Type", "text/html"),)),
        content=Content(body=html.encode()),
        block_class="ok",
        error=None,
    )


def test_the_urls_that_name_the_page_are_its_final_url_canonical_and_og_url_in_that_order() -> None:
    html = (
        '<html><head><meta property="OG:URL" content="https://www.example.test/jobs">'
        '<link rel="Alternate Canonical" href="/canonical"></head><body></body></html>'
    )

    assert page_refs(_page(html)) == PageRefs(
        own=(FINAL, "https://careers.example.test/canonical", "https://www.example.test/jobs"), links=()
    )


def test_references_resolve_against_the_documents_base_url() -> None:
    html = (
        '<html><head><base href="https://static.example.test/base/">'
        '<link rel="canonical" href="page"><meta property="og:url" content="og"></head>'
        '<body><a href="job/1">a</a></body></html>'
    )

    assert page_refs(_page(html)) == PageRefs(
        own=(FINAL, "https://static.example.test/base/page", "https://static.example.test/base/og"),
        links=("https://static.example.test/base/job/1",),
    )
    assert canonical_link(_page(html)) == "https://static.example.test/base/page"


def test_links_are_the_http_targets_in_document_order_each_once() -> None:
    html = (
        "<body>"
        '<a href="https://a.example.test/x">1</a><a href="/local">2</a><a href="mailto:x@example.test">3</a>'
        '<a href="javascript:void(0)">4</a><a href="https://a.example.test/x">5</a><a href="#top">6</a><a>7</a>'
        "</body>"
    )

    assert page_refs(_page(html)).links == (
        "https://a.example.test/x",
        "https://careers.example.test/local",
        f"{FINAL}#top",
    )


def test_a_page_with_more_links_than_the_cap_keeps_none_so_no_site_is_judged_by_a_part_of_them() -> None:
    html = "<body>" + "".join(f'<a href="/{i}">x</a>' for i in range(MAX_LINKS + 1)) + "</body>"

    assert page_refs(_page(html)).links == ()


def test_a_page_with_as_many_links_as_the_cap_keeps_them_all() -> None:
    html = "<body>" + "".join(f'<a href="/{i}">x</a>' for i in range(MAX_LINKS)) + "</body>"

    links = page_refs(_page(html)).links

    assert len(links) == MAX_LINKS
    assert links[0] == "https://careers.example.test/0"


def test_a_page_without_a_canonical_link_has_none() -> None:
    assert canonical_link(_page("<html><body>x</body></html>")) is None


def test_a_reference_no_url_parser_reads_is_skipped_and_the_rest_are_kept() -> None:
    # RFC 3986 §3.2.2: an unmatched bracket in an authority is no URL.
    html = (
        '<html><head><base href="http://[bad"><link rel="canonical" href="http://[x">'
        '<meta property="og:url" content="http://[y"></head>'
        '<body><a href="http://[z">1</a><a href="/ok">2</a></body></html>'
    )

    refs = page_refs(_page(html))

    assert refs == PageRefs(own=(FINAL,), links=("https://careers.example.test/ok",))
    assert canonical_link(_page(html)) is None
