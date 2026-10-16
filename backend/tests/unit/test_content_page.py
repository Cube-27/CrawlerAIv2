"""`ParsedPage` (SPEC-05 §4.1, ARCHITECTURE §8 "Parse once"): one decode and at most one parse per parser per
capture (INV-26); the script blocks; the lazy lxml tree."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from crawlerai.content.html import cleaned_html
from crawlerai.content.links import links
from crawlerai.content.markdown import markdown
from crawlerai.content.metadata import metadata
from crawlerai.content.page import ParsedPage, ScriptBlock
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    Headers,
    NetworkBody,
    network_file,
    sha256_hex,
)

# The `parses` fixture (tests/unit/conftest.py): parser constructions by name, each with `calls` and `inputs`.
Parses = Mapping[str, Any]

DOC = """<!doctype html><html><head>
<script type="application/ld+json; charset=utf-8">{"@type": "Product", "name": "A &amp; B"}</script>
<script src="/app.js"></script>
</head><body><p>Hello <b>world</b></p>
<script>if (a < b) { go(); }</script>
<div><script type="Application/JSON">[1]</script></div>
</body></html>"""


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
    ("body", "headers"),
    [
        # Encoding Standard §4.2: the label `iso-8859-1` is windows-1252, where 0x96 is an en dash.
        (b"<p>a \x96 b</p>", (("content-type", "text/html; charset=iso-8859-1"),)),
        # HTML Standard §13.2.3.2: without a transport charset, the prescan reads a `meta` charset declaration.
        (b'<meta charset="windows-1252"><p>a \x96 b</p>', (("content-type", "text/html"),)),
        (b'<meta http-equiv="Content-Type" content="text/html; charset=latin1"><p>a \x96 b</p>', ()),
        # A byte order mark outranks every declaration (Encoding Standard §6 "decode").
        (b"\xef\xbb\xbf<p>a \xe2\x80\x93 b</p>", (("content-type", "text/html; charset=windows-1252"),)),
        # The transport charset outranks a `meta` declaration.
        (b'<meta charset="windows-1252"><p>a \xe2\x80\x93 b</p>', (("content-type", "text/html; charset=utf-8"),)),
    ],
)
def test_the_body_decodes_as_the_encoding_sniffing_algorithm_says(
    body: bytes, headers: tuple[tuple[str, str], ...]
) -> None:
    assert ParsedPage.of(_bundle(body, headers)).cleaned_text.text == "a \u2013 b"


def test_a_browser_capture_is_utf8_whatever_the_server_declared() -> None:
    # The browser body is the rendered DOM, serialized by the fetcher as UTF-8 (`acquire.browser`); the server's
    # declaration was for the bytes it sent, which the browser already decoded.
    body = '<meta charset="windows-1252"><p>a \u2013 b</p>'.encode()
    plain = _bundle(body, (("content-type", "text/html; charset=windows-1252"),))
    manifest = plain.manifest.model_copy(update={"method": "browser"})

    page = ParsedPage.of(CaptureBundle(manifest=manifest, body=plain.body, network=()))

    assert page.cleaned_text.text == "a \u2013 b"


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


def test_script_blocks_are_the_inline_scripts_with_media_type_text_and_xpath() -> None:
    assert ParsedPage(DOC).scripts == (
        ScriptBlock(
            type="application/ld+json",
            text='{"@type": "Product", "name": "A &amp; B"}',
            xpath="/html[1]/head[1]/script[1]",
        ),
        ScriptBlock(type="", text="if (a < b) { go(); }", xpath="/html[1]/body[1]/script[1]"),
        ScriptBlock(type="application/json", text="[1]", xpath="/html[1]/body[1]/div[1]/script[1]"),
    )


def test_the_lxml_tree_is_built_from_the_same_text() -> None:
    tree = ParsedPage(DOC).lxml_tree

    assert [el.text_content() for el in tree.xpath("/html[1]/body[1]/p[1]")] == ["Hello world"]


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<?xml version="1.0" encoding="ISO-8859-1"?><html><body><p>x</p></body></html>', "x"),
        ("", ""),
    ],
)
def test_the_lxml_tree_accepts_an_xml_declaration_and_an_empty_document(html: str, expected: str) -> None:
    assert ParsedPage(html).lxml_tree.text_content() == expected


def test_every_consumer_reads_one_parse_per_parser(parses: Parses) -> None:
    # INV-26: each capture body is parsed at most once per parser, however many consumers read the page.
    page = ParsedPage.of(_bundle(DOC.encode(), (("Content-Type", "text/html"),)))
    for _ in range(2):
        assert page.tree.css_first("p") is not None
        assert len(page.scripts) == 3
        assert page.cleaned_text.text.startswith("Hello world")
        assert page.visible_values.visible("Hello world")
        assert page.lxml_tree.xpath("count(//script)") == 4

    assert {name: counter.calls for name, counter in parses.items()} == {"selectolax": 1, "lxml": 1}


def _holds_head_script(parser_input: object) -> bool:
    text = parser_input.decode() if isinstance(parser_input, bytes) else parser_input
    return isinstance(text, str) and "application/ld+json" in text


def test_the_content_formats_read_one_parse_per_parser(parses: Parses) -> None:
    # INV-26 across SPEC-07 §4.5's formats: they read the page's trees, and none parses the body again.
    # trafilatura's readability fallback parses readability's own output, a new document with the main content
    # only, so a parse of the body is one whose input still holds the `<head>`'s JSON-LD block.
    page = ParsedPage.of(_bundle(DOC.encode(), (("Content-Type", "text/html"),)))
    final_url = "https://shop.example.test/p/1"

    assert page.lxml_tree.xpath("count(//p)") == 1  # another consumer of the lxml tree, as an XPath step is
    assert markdown(page, final_url) == "Hello **world**"
    assert "<script" not in cleaned_html(page)
    assert links(page, final_url) == ()
    assert metadata(page, final_url).structured_data_types == ("Product",)

    body_parses = {name: sum(map(_holds_head_script, counter.inputs)) for name, counter in parses.items()}
    assert body_parses == {"selectolax": 1, "lxml": 1}


def test_lxml_parses_only_when_a_consumer_asks(parses: Parses) -> None:
    page = ParsedPage(DOC)
    assert page.visible_values.visible("world")
    assert len(page.scripts) == 3

    assert {name: counter.calls for name, counter in parses.items()} == {"selectolax": 1, "lxml": 0}


def test_a_script_inside_a_prefixed_tag_gets_a_name_test_step() -> None:
    assert ParsedPage("<o:w><b></b><script>1</script></o:w>").scripts == (
        ScriptBlock(type="", text="1", xpath="/html[1]/body[1]/*[name()='o:w'][1]/script[1]"),
    )
