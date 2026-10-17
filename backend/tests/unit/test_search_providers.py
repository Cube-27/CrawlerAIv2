"""Reading a search provider's answer, and asking SearXNG and a URL template (D-1442, D-1443). Hosts are RFC 2606."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from crawlerai.search.providers import SearchFailed, SearxngProvider, TemplateProvider, configured, http_get
from crawlerai.search.results import Hit, parse

pytestmark = pytest.mark.anyio

HERE = "https://search.example.test/find"


def _json(document: object) -> bytes:
    return json.dumps(document).encode()


def test_a_json_answer_gives_its_largest_array_of_objects_with_urls() -> None:
    body = _json(
        {
            "meta": [{"url": "https://meta.example.test/x", "name": "not a result list"}],
            "data": {
                "items": [
                    {"id": 1, "link": "https://a.example.test/one#top", "name": "One", "text": "The first result text"},
                    {"id": 2, "link": "https://b.example.test/two", "name": "Two"},
                    {"id": 3, "name": "No link here"},
                    {"id": 4, "link": "https://a.example.test/one", "name": "One again"},
                ]
            },
        }
    )

    assert parse(body, None, HERE) == [
        Hit("https://a.example.test/one", "One", "The first result text"),
        Hit("https://b.example.test/two", "Two", ""),
    ]


def test_named_members_override_the_reading_of_a_result_by_its_shape() -> None:
    body = _json(
        {
            "hits": [
                {"author": "someone", "id": "42", "headline": "How retries", "link": "https://a.example.test/x"},
                {"author": "other", "headline": "Second one", "link": "https://b.example.test/y"},
            ]
        }
    )

    assert [hit.title for hit in parse(body, None, HERE)] == ["someone", "other"]
    named = {"url": "link", "title": "headline", "snippet": "id"}
    assert [(hit.title, hit.snippet) for hit in parse(body, None, HERE, named)] == [
        ("How retries", "42"),
        ("Second one", ""),
    ]


def test_an_html_answer_gives_its_outbound_anchors_in_order() -> None:
    page = (
        b'<a href="/next">More</a><a href="https://search.example.test/about">About us</a>'
        b'<a href="https://x.example.test/p?b=2&a=1">  First \n hit </a><a href="mailto:a@example.test">Mail</a>'
        b'<a href="https://y.example.test/">Second</a>'
    )

    assert parse(page, "utf-8", HERE) == [
        Hit("https://x.example.test/p?a=1&b=2", "First hit", ""),
        Hit("https://y.example.test/", "Second", ""),
    ]


def test_an_anchor_that_redirects_through_the_answering_host_is_its_target() -> None:
    page = (
        b'<a href="//search.example.test/l/?u=https%3A%2F%2Fa.example.test%2Fp%3Fx%3D1&amp;token=t">  Wrapped </a>'
        b'<a href="/l/?u=https%3A%2F%2Fa.example.test%2Fp%3Fx%3D1">Same again</a>'
        b'<a href="/next?page=2">Next</a><a href="/about?home=https%3A%2F%2Fsearch.example.test%2F">Own</a>'
        b'<a href="//b.example.test/q">Protocol relative</a>'
    )

    assert [(hit.url, hit.title) for hit in parse(page, None, HERE)] == [
        ("https://a.example.test/p?x=1", "Wrapped"),
        ("https://b.example.test/q", "Protocol relative"),
    ]


@pytest.mark.parametrize("body", [b"", b"[]", b'{"results": []}', b"<p>nothing</p>"])
def test_an_answer_without_results_gives_none(body: bytes) -> None:
    assert parse(body, None, HERE) == []


async def test_searxng_is_asked_for_json_and_reads_further_pages_until_the_limit() -> None:
    asked: list[dict[str, list[str]]] = []
    pages = {
        "1": [{"url": f"https://r{n}.example.test/", "title": f"R{n}", "content": "snippet"} for n in range(3)],
        "2": [{"url": f"https://r{n}.example.test/", "title": f"R{n}", "content": "snippet"} for n in range(2, 6)],
    }

    async def get(url: str) -> tuple[bytes, str | None]:
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        asked.append(query)
        assert parts.path == "/search"
        return _json({"results": pages.get(query["pageno"][0], [])}), "utf-8"

    hits = await SearxngProvider("https://searx.example.test/", get).search("kettles & tea", 5)

    assert [hit.url for hit in hits] == [f"https://r{n}.example.test/" for n in range(5)]
    assert [(q["q"], q["format"], q["pageno"]) for q in asked] == [
        (["kettles & tea"], ["json"], [page]) for page in ("1", "2")
    ]


async def test_a_template_is_filled_with_the_encoded_query_and_the_limit() -> None:
    seen: list[str] = []

    async def get(url: str) -> tuple[bytes, str | None]:
        seen.append(url)
        return _json([{"href": f"https://r{n}.example.test/", "t": "x"} for n in range(5)]), None

    hits = await TemplateProvider("https://api.example.test/s?q={query}&n={limit}", get).search("a b/c", 3)

    assert seen == ["https://api.example.test/s?q=a%20b%2Fc&n=3"]
    assert len(hits) == 3


def test_the_settings_choose_the_provider_and_refuse_a_malformed_one() -> None:
    assert configured(None, None, 5) is None
    assert isinstance(configured("https://searx.example.test", None, 5), SearxngProvider)
    assert isinstance(configured(None, "https://api.example.test/?q={query}", 5), TemplateProvider)
    with pytest.raises(ValueError, match="query"):
        configured(None, "https://api.example.test/", 5)
    with pytest.raises(ValueError, match="absolute"):
        configured("ftp://searx.example.test", None, 5)


async def test_an_unreachable_provider_is_a_failure_with_no_internals() -> None:
    with pytest.raises(SearchFailed, match="did not answer"):
        await http_get(1)("http://127.0.0.1:1/never")
