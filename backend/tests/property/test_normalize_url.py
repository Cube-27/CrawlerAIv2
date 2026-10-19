"""The url and image_url normalizer (normalization spec): WHATWG-style parsing, absolutization against
the document base, RFC 3986 canonicalization, and declines on empty, relative-without-base and non-http(s) input."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.normalize import url
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
URL = FieldSpec(type=FieldType.URL)
IMAGE = FieldSpec(type=FieldType.IMAGE_URL)

_label = st.from_regex(r"[A-Za-z0-9]([A-Za-z0-9-]{0,8}[A-Za-z0-9])?", fullmatch=True)
_host = st.lists(_label, min_size=1, max_size=3).map(lambda labels: ".".join([*labels, "test"]))
_segment = st.text(max_size=8).filter(lambda s: "/" not in s and "?" not in s and "#" not in s)
_urls = st.builds(
    lambda scheme, host, port, segments, query, fragment: (
        f"{scheme}://{host}{port}/{'/'.join(segments)}{query}{fragment}"
    ),
    st.sampled_from(["http", "https", "HTTP", "Https"]),
    _host,
    st.sampled_from(["", ":80", ":443", ":8080"]),
    st.lists(_segment, max_size=4),
    st.sampled_from(["", "?", "?a=1&b=%7e", "?q=café x"]),
    st.sampled_from(["", "#", "#top", "#a?b"]),
)


@given(st.sampled_from([URL, IMAGE]), _urls)
def test_output_is_absolute_http_without_a_fragment_and_normalizes_to_itself(spec: FieldSpec, raw: str) -> None:
    result = url.normalize(raw, spec, CTX)

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert result.value.startswith(("http://", "https://"))
    assert "#" not in result.value
    assert url.normalize(result.value, spec, CTX) == result


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (" \x1f\t\n", "empty"),
        ("http://a.test/\ud800", "surrogate"),
        ("javascript:alert(1)", "not_http"),
        ("data:image/png;base64,iVBORw0KGgo=", "not_http"),
        ("ftp://a.test/p", "not_http"),
        ("http:///path", "no_host"),
        ("https:////cdn.example.test/i.png", "no_host"),  # D-1022: an empty authority is declined, not repaired (C7)
        ("http://example.test:99999/", "unparsable"),
        ("http://a%FFb.example.test/", "unparsable"),
        ("http://a%20b.example.test/", "forbidden_host_code_point"),
        ("http://a<b.example.test/", "forbidden_host_code_point"),
    ],
)
def test_input_that_is_no_http_url_is_invalid(raw: str, reason: str) -> None:
    ctx = Context(captured_at=AT, base_url="https://base.test/")

    assert url.normalize(raw, URL, ctx) == Invalid(reason)
    assert url.normalize(raw, IMAGE, ctx) == Invalid(reason)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Shop.EXAMPLE.test:443/a", "https://shop.example.test/a"),
        ("http://example.test:8080/", "http://example.test:8080/"),
        ("http://example.test/%7euser/%2fkept?q=%e2%82%ac#frag", "http://example.test/~user/%2Fkept?q=%E2%82%AC"),
        ("http://example.test/a/./b/../c/%2E%2E/d", "http://example.test/a/d"),
        ("http://example.test/a b/é?x=é y", "http://example.test/a%20b/%C3%A9?x=%C3%A9%20y"),
        ("  http://exam\tple.test/a\nb\r  ", "http://example.test/ab"),
        ("http://EX%41MPLE.test/", "http://example.test/"),
    ],
)
def test_absolute_urls_are_canonicalized(raw: str, expected: str) -> None:
    assert url.normalize(raw, URL, CTX) == Ok(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../c?x=1#f", "https://example.test/c?x=1"),
        ("/root", "https://example.test/root"),
        ("//cdn.example.test/i.png", "https://cdn.example.test/i.png"),
        ("?page=2", "https://example.test/a/b?page=2"),
    ],
)
def test_relative_urls_resolve_against_the_document_base_and_need_one(raw: str, expected: str) -> None:
    ctx = Context(captured_at=AT, base_url="https://example.test/a/b", page_url="https://example.test/other")

    assert url.normalize(raw, URL, ctx) == Ok(expected)
    assert url.normalize(raw, URL, CTX) == Invalid("relative_without_base")


def test_an_image_url_that_is_the_page_url_is_invalid() -> None:
    ctx = Context(captured_at=AT, page_url="https://example.test/p?id=1#reviews")

    assert url.normalize("HTTPS://example.test:443/p?id=1", IMAGE, ctx) == Invalid("page_url")
    assert url.normalize("HTTPS://example.test:443/p?id=1", URL, ctx) == Ok("https://example.test/p?id=1")
    assert url.normalize("https://example.test/p.png", IMAGE, ctx) == Ok("https://example.test/p.png")


@pytest.mark.parametrize("path", ["/player/index.html?videoId=1", "/v/clip.mp4", "/app.js"])
def test_an_image_url_naming_a_file_of_another_media_type_is_invalid(path: str) -> None:
    raw = f"https://cdn.example.test{path}"

    assert url.normalize(raw, IMAGE, CTX) == Invalid("not_an_image")
    assert isinstance(url.normalize(raw, URL, CTX), Ok)
    # A path with no registered extension, or an image's, says nothing against it.
    assert isinstance(url.normalize("https://cdn.example.test/i/123/format:webp", IMAGE, CTX), Ok)


def test_the_resource_key_ignores_only_the_scheme_the_query_and_a_stated_size() -> None:
    key = url.resource_key("https://cdn.example.test/i/a-300x200.jpg?w=1")

    assert key is not None
    assert key == url.resource_key("http://cdn.example.test/i/a_64x64.jpg#zoom")
    assert key != url.resource_key("https://cdn.example.test/i/b-300x200.jpg")
    assert key != url.resource_key("https://img.example.test/i/a-300x200.jpg")
    assert url.resource_key("/i/a.jpg") is None


def test_a_proxy_url_names_the_file_its_url_parameter_names() -> None:
    key = url.resource_key("https://cdn.example.test/i/a.jpg?w=940")
    proxy = "https://www.example.test/_img?url="

    assert key == url.resource_key(f"{proxy}https%3A%2F%2Fcdn.example.test%2Fi%2Fa.jpg&w=640")
    assert url.resource_key(f"{proxy}%2Fi%2Fa.jpg") == url.resource_key("https://www.example.test/i/a.jpg")
    assert url.resource_key(f"{proxy}%2Fi%2Fa.jpg") != url.resource_key(f"{proxy}%2Fi%2Fb.jpg")
    # Another parameter holding a URL (a fallback, a referrer) is no file the URL serves.
    other = "https://img.example.test/i/a.jpg?fallback=https%3A%2F%2Fcdn.example.test%2Fi%2Fz.jpg"
    assert url.resource_key(other) == ("resource", "img.example.test", "/i/a.jpg")
