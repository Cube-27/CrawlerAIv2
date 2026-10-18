"""`ParsedPage` (extraction spec): one decode and at most one parse per parser per
capture (INV-26); the script blocks; the lazy lxml tree."""

from datetime import UTC, datetime

import pytest

from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    Headers,
    NetworkBody,
    decode_body,
    network_file,
    sha256_hex,
)


# The `parses` fixture (tests/unit/conftest.py): parser constructions by name, each with `calls` and `inputs`.
def _bundle(body: bytes, response_headers: tuple[tuple[str, str], ...]) -> CaptureBundle:
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url="https://shop.example.test/p/1",
        final_url="https://shop.example.test/p/1",
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=response_headers),
        timings_ms={},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=body, network=())


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
    page = ParsedPage.of(_bundle(body, headers))

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
def test_a_json_body_decodes_as_utf8_whatever_charset_it_is_labelled_with(method: str, content_type: str) -> None:
    # RFC 8259 §8.1, §11: JSON text is exchanged as UTF-8 and its media type has no charset parameter; an API
    # capture's body is a JSON document (`body.json`; acquisition spec, "Structural outcome classification (INV-24)")
    # unless it is labelled HTML.
    headers = (("content-type", content_type),) if content_type else ()
    plain = _bundle('{"name": "café \u2013 b"}'.encode(), headers)
    manifest = plain.manifest.model_copy(update={"method": method})

    text = decode_body(CaptureBundle(manifest=manifest, body=plain.body, network=()))

    assert text == '{"name": "café \u2013 b"}'


def test_the_page_keeps_the_captured_network_bodies_in_request_order() -> None:
    bodies = (b'{"a": 1}', b"[2]")
    entries = tuple(
        NetworkBody(
            url=f"https://shop.example.test/api/{i}",
            status=200,
            content_type="application/json",
            sha256=sha256_hex(data),
            file=network_file(i),
        )
        for i, data in enumerate(bodies)
    )
    plain = _bundle(b"<p>x</p>", ())
    manifest = plain.manifest.model_copy(update={"method": "browser", "network_bodies": entries})

    page = ParsedPage.of(CaptureBundle(manifest=manifest, body=plain.body, network=bodies))

    assert page.network == (b'{"a": 1}', b"[2]")
