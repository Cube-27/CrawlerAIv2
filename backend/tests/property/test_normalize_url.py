"""The url and image_url normalizer (SPEC-04 §4.4, ARCHITECTURE §9): WHATWG-style parsing, absolutization against
the document base, RFC 3986 canonicalization, and declines on empty, relative-without-base and non-http(s) input."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

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
# Unicode White_Space, plus every C0 control and space: what the WHATWG URL parser trims from the ends.
_whitespace = st.text(
    alphabet=st.characters(max_codepoint=0x20) | st.characters(categories=["Zs", "Cc"]).filter(str.isspace),
    max_size=8,
)


@given(st.sampled_from([URL, IMAGE]), _urls)
def test_output_is_absolute_http_without_a_fragment(spec: FieldSpec, raw: str) -> None:
    result = url.normalize(raw, spec, CTX)

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert result.value.startswith(("http://", "https://"))
    assert "#" not in result.value


@given(st.sampled_from([URL, IMAGE]), _urls)
def test_an_ok_value_normalizes_to_itself(spec: FieldSpec, raw: str) -> None:
    result = url.normalize(raw, spec, CTX)

    assert isinstance(result, Ok)
    assert url.normalize(result.value, spec, CTX) == result


@given(st.sampled_from([URL, IMAGE]), _whitespace)
def test_empty_or_whitespace_input_is_invalid_even_with_a_base(spec: FieldSpec, raw: str) -> None:
    ctx = Context(captured_at=AT, base_url="https://example.test/a")

    assert url.normalize(raw, spec, CTX) == Invalid("empty")
    assert url.normalize(raw, spec, ctx) == Invalid("empty")


@pytest.mark.parametrize("raw", ["\x00", "\x01\x02", " \x1f\t\n", "\x0b\x0c"])
def test_input_of_c0_controls_only_is_invalid_even_with_a_base(raw: str) -> None:
    ctx = Context(captured_at=AT, base_url="https://example.test/x")

    assert url.normalize(raw, URL, ctx) == Invalid("empty")


# Unicode general category Cs: a lone surrogate is not a Unicode scalar value, so no UTF-8 string holds it. JSON text
# may still carry one as an escape (RFC 8259 §8.2), and `json.loads` keeps it.
_surrogate = st.characters(categories=["Cs"])


@given(st.sampled_from([URL, IMAGE]), _urls, st.integers(min_value=0), _surrogate)
def test_input_with_a_lone_surrogate_is_invalid(spec: FieldSpec, raw: str, at: int, surrogate: str) -> None:
    at %= len(raw) + 1
    ctx = Context(captured_at=AT, base_url="https://example.test/a/")

    assert url.normalize(raw[:at] + surrogate + raw[at:], spec, ctx) == Invalid("surrogate")


@given(_surrogate)
def test_a_base_with_a_lone_surrogate_declines_only_the_references_it_resolves(surrogate: str) -> None:
    ctx = Context(captured_at=AT, base_url=f"https://example.test/{surrogate}/")

    assert url.normalize("p.png", URL, ctx) == Invalid("surrogate")
    assert url.normalize("https://example.test/p.png", URL, ctx) == Ok("https://example.test/p.png")


@given(
    st.from_regex(r"[a-z][a-z0-9+.-]{0,8}", fullmatch=True).filter(lambda s: s not in ("http", "https")),
    st.sampled_from(["//a.test/p", "a.test/p", "alert(1)", "image/png;base64,AAAA"]),
)
def test_a_scheme_other_than_http_or_https_is_invalid(scheme: str, rest: str) -> None:
    ctx = Context(captured_at=AT, base_url="https://base.test/")

    assert url.normalize(f"{scheme}:{rest}", URL, ctx) == Invalid("not_http")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Shop.EXAMPLE.test:443/a", "https://shop.example.test/a"),
        ("http://example.test:80", "http://example.test/"),
        ("http://example.test:8080/", "http://example.test:8080/"),
        ("https://example.test:80/", "https://example.test:80/"),
        ("http://example.test/%7euser/%2fkept?q=%e2%82%ac#frag", "http://example.test/~user/%2Fkept?q=%E2%82%AC"),
        ("http://example.test/a/./b/../c/%2E%2E/d", "http://example.test/a/d"),
        ("http://example.test/../..", "http://example.test/"),
        ("http://example.test/a b/é?x=é y", "http://example.test/a%20b/%C3%A9?x=%C3%A9%20y"),
        ("  http://exam\tple.test/a\nb\r  ", "http://example.test/ab"),
        ("http://user:pw@Example.test/", "http://user:pw@example.test/"),
        ("http://[::1]:8000/x", "http://[::1]:8000/x"),
        ("http://example.test/100%", "http://example.test/100%"),
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
        ("d", "https://example.test/a/d"),
    ],
)
def test_relative_urls_resolve_against_the_document_base(raw: str, expected: str) -> None:
    ctx = Context(captured_at=AT, base_url="https://example.test/a/b", page_url="https://example.test/other")

    assert url.normalize(raw, URL, ctx) == Ok(expected)


@pytest.mark.parametrize("raw", ["../c", "/root", "//cdn.example.test/i.png", "page.html"])
def test_a_relative_url_without_a_base_is_invalid(raw: str) -> None:
    assert url.normalize(raw, URL, CTX) == Invalid("relative_without_base")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("http:///path", "no_host"),
        ("http://example.test:99999/", "unparsable"),
        ("http://example.test:port/", "unparsable"),
        ("http://[::1/", "unparsable"),
    ],
)
def test_unparsable_urls_are_invalid(raw: str, reason: str) -> None:
    assert url.normalize(raw, URL, CTX) == Invalid(reason)


def test_an_image_url_that_is_the_page_url_is_invalid() -> None:
    ctx = Context(captured_at=AT, page_url="https://example.test/p?id=1#reviews")

    assert url.normalize("HTTPS://example.test:443/p?id=1", IMAGE, ctx) == Invalid("page_url")
    assert url.normalize("HTTPS://example.test:443/p?id=1", URL, ctx) == Ok("https://example.test/p?id=1")
    assert url.normalize("https://example.test/p.png", IMAGE, ctx) == Ok("https://example.test/p.png")


def test_a_data_url_is_invalid_for_both_types() -> None:
    raw = "data:image/png;base64,iVBORw0KGgo="

    assert url.normalize(raw, IMAGE, CTX) == Invalid("not_http")
    assert url.normalize(raw, URL, CTX) == Invalid("not_http")


@pytest.mark.parametrize("raw", [None, 3, True, ["http://example.test/"], {"@id": "http://example.test/"}])
def test_a_non_string_is_invalid(raw: JsonValue) -> None:
    assert url.normalize(raw, URL, CTX) == Invalid("not_a_string")


@pytest.mark.parametrize("type_", [FieldType.TEXT, FieldType.MONEY])
def test_a_spec_of_another_type_is_a_programming_error(type_: FieldType) -> None:
    spec = FieldSpec(type=type_)

    with pytest.raises(TypeError):
        url.normalize("http://example.test/", spec, CTX)


@given(st.sampled_from([URL, IMAGE]), st.text(max_size=40) | _urls)
def test_the_result_depends_only_on_the_arguments(spec: FieldSpec, raw: str) -> None:
    ctx = Context(captured_at=AT, base_url="https://example.test/a/", page_url="https://example.test/a/")

    first = url.normalize(raw, spec, ctx)

    assert url.normalize(raw, spec, ctx) == first
