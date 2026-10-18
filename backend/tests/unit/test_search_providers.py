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


def test_the_settings_choose_the_provider_and_refuse_a_malformed_one() -> None:
    assert configured(None, None, 5) is None
    assert isinstance(configured("https://searx.example.test", None, 5), SearxngProvider)
    assert isinstance(configured(None, "https://api.example.test/?q={query}", 5), TemplateProvider)
    with pytest.raises(ValueError, match="query"):
        configured(None, "https://api.example.test/", 5)
    with pytest.raises(ValueError, match="absolute"):
        configured("ftp://searx.example.test", None, 5)


async def test_an_unreachable_provider_is_a_failure_with_no_internals() -> None:
    get = http_get(1)

    with pytest.raises(SearchFailed, match="did not answer"):
        await get("http://127.0.0.1:1/never")
