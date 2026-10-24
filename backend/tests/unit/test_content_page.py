"""`ParsedPage`: one decode and at most one parse per parser per
capture; the script blocks; the lazy lxml tree."""

import pytest

from snowcrawl.content.page import ParsedPage
from snowcrawl.core.capture import CaptureMethod
from tests.support.captures import calls, capture


# The `parses` fixture (tests/unit/conftest.py): parser constructions by name, each with `calls` and `inputs`.
@pytest.mark.parametrize(
    ("body", "headers", "expected"),
    [
        ("<p>café €</p>".encode(), (("Content-Type", "text/html"),), "café €"),
        ("<p>café</p>".encode("latin-1"), (("content-type", "text/html; charset=ISO-8859-1"),), "café"),
        ("<p>café</p>".encode(), (), "café"),
        (b"<p>caf\xe9</p>", (("Content-Type", "text/html; charset=x-unknown"),), "caf�"),
    ],
)
def test_the_body_decodes_in_the_content_type_charset_else_utf8(
    body: bytes, headers: tuple[tuple[str, str], ...], expected: str
) -> None:
    page = ParsedPage.of(capture(body, headers=headers))

    assert page.cleaned_text.text == expected
    assert page.lxml_tree.text_content() == expected


@pytest.mark.parametrize(
    ("method", "content_type"),
    [
        ("api", "application/json; charset=iso-8859-1"),
        ("api", "text/plain; charset=windows-1252"),
        ("api", ""),
        ("http", "application/problem+json; charset=windows-1252"),
        ("http", "text/json; charset=iso-8859-1"),
    ],
)
def test_a_json_body_decodes_as_utf8_whatever_charset_it_is_labelled_with(
    method: CaptureMethod, content_type: str
) -> None:
    # RFC 8259 §8.1, §11: JSON text is exchanged as UTF-8 and its media type has no charset parameter; an API
    # capture's body is a JSON document (`body.json`)
    # unless it is labelled HTML.
    headers = (("content-type", content_type),) if content_type else ()
    text = capture('{"name": "café \u2013 b"}'.encode(), method=method, headers=headers).text

    assert text == '{"name": "café \u2013 b"}'


def test_the_page_keeps_the_captured_network_bodies_in_request_order() -> None:
    network = calls((f"https://shop.example.test/api/{i}", data) for i, data in enumerate((b'{"a": 1}', b"[2]")))

    page = ParsedPage.of(capture(b"<p>x</p>", method="browser", headers=(), network=network))

    assert page.network == (b'{"a": 1}', b"[2]")
