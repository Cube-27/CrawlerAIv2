"""`ParsedPage` (SPEC-05 §4.1, ARCHITECTURE §8 "Parse once"): one decode and at most one parse per parser per
capture (INV-26); the script blocks; the lazy lxml tree."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from lxml import html as lxml_html
from selectolax import lexbor

from crawlerai.content.page import ParsedPage, ScriptBlock
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

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
        (" \n", ""),
    ],
)
def test_the_lxml_tree_accepts_an_xml_declaration_and_an_empty_document(html: str, expected: str) -> None:
    assert ParsedPage(html).lxml_tree.text_content() == expected


class _Counter:
    def __init__(self) -> None:
        self.calls = 0

    def wrap(self, constructor: Callable[..., Any]) -> Callable[..., Any]:
        def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            return constructor(*args, **kwargs)

        return counted


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, _Counter]]:
    counters = {"selectolax": _Counter(), "lxml": _Counter()}
    monkeypatch.setattr(lexbor, "LexborHTMLParser", counters["selectolax"].wrap(lexbor.LexborHTMLParser))
    monkeypatch.setattr(lxml_html, "document_fromstring", counters["lxml"].wrap(lxml_html.document_fromstring))
    yield counters


def test_every_consumer_reads_one_parse_per_parser(parses: dict[str, _Counter]) -> None:
    # INV-26: each capture body is parsed at most once per parser, however many consumers read the page.
    page = ParsedPage.of(_bundle(DOC.encode(), (("Content-Type", "text/html"),)))
    for _ in range(2):
        assert page.tree.css_first("p") is not None
        assert len(page.scripts) == 3
        assert page.cleaned_text.text.startswith("Hello world")
        assert page.visible_values.visible("Hello world")
        assert page.lxml_tree.xpath("count(//script)") == 4

    assert {name: counter.calls for name, counter in parses.items()} == {"selectolax": 1, "lxml": 1}


def test_lxml_parses_only_when_a_consumer_asks(parses: dict[str, _Counter]) -> None:
    page = ParsedPage(DOC)
    assert page.visible_values.visible("world")
    assert len(page.scripts) == 3

    assert {name: counter.calls for name, counter in parses.items()} == {"selectolax": 1, "lxml": 0}


def test_a_script_inside_a_prefixed_tag_gets_a_name_test_step() -> None:
    assert ParsedPage("<o:w><b></b><script>1</script></o:w>").scripts == (
        ScriptBlock(type="", text="1", xpath="/html[1]/body[1]/*[name()='o:w'][1]/script[1]"),
    )
