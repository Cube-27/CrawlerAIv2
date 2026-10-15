"""Block classification (SPEC-02 §4.3, INV-24): HTTP status and structural body properties only."""

import pytest

from crawlerai.acquire.classify import classify
from crawlerai.acquire.types import BlockClass

_HTML = (("content-type", "text/html; charset=utf-8"),)
_JSON = (("content-type", "application/json"),)


def _page(text_chars: int, links: int, extra: str = "") -> bytes:
    anchors = "".join(f'<a href="/p/{i}"></a>' for i in range(links))
    return f"<html><head><title>t</title></head><body><p>{'x' * text_chars}</p>{anchors}{extra}</body></html>".encode()


_FULL = _page(400, 20)
_EMPTY_APP = b'<html><head><script src="/app.js"></script></head><body><div id="root"></div></body></html>'


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, "not_found"),
        (403, "blocked"),
        # 503 is a server error that asks the client to back off: blocked wins over error.
        (503, "blocked"),
        (400, "error"),
        (500, "error"),
        (200, "ok"),
        # The fetcher follows redirects; a 3xx reaching classify is not a 2xx page, so the shell rule does not apply.
        (301, "ok"),
    ],
)
def test_status_decides_before_the_body(status: int, expected: BlockClass) -> None:
    assert classify(status, _HTML, _FULL) == expected
    # An empty page under a non-2xx status is classified by its status alone.
    assert classify(status, _HTML, _EMPTY_APP) == (expected if status >= 300 else "shell")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (_EMPTY_APP, "shell"),
        (b"", "shell"),
        (_page(199, 4), "shell"),
        (_page(200, 0), "ok"),
        (_page(0, 5), "ok"),
        # Text inside script, style, noscript and template is not visible.
        (
            _page(
                10,
                0,
                "<script>" + "y" * 500 + "</script><style>" + "z" * 500 + "</style>"
                "<noscript>" + "y" * 500 + "</noscript><template><p>" + "z" * 500 + "</p></template>",
            ),
            "shell",
        ),
        # Links inside a template are not in the document.
        (_page(10, 0, "<template>" + '<a href="/x">x</a>' * 10 + "</template>"), "shell"),
        # An anchor without href is not a link.
        (_page(10, 0, "<a>x</a>" * 10), "shell"),
        # Whitespace is not visible text.
        (_page(10, 0, "<p>" + " \n\t" * 300 + "</p>"), "shell"),
        # The title is not part of the body.
        (b"<html><head><title>" + b"t" * 500 + b"</title></head><body></body></html>", "shell"),
    ],
)
def test_shell_rule_on_html(body: bytes, expected: BlockClass) -> None:
    assert classify(200, _HTML, body) == expected


def test_visible_text_counts_characters_not_bytes() -> None:
    # 150 two-byte characters: 300 bytes, 150 characters.
    body = "<html><body><p>{}</p></body></html>".format("é" * 150).encode()
    assert classify(200, _HTML, body) == "shell"


def test_shell_rule_applies_only_to_html() -> None:
    # A small JSON or plain-text body is a complete response, not an unrendered page.
    assert classify(200, _JSON, b'{"id": 1}') == "ok"
    assert classify(200, (("Content-Type", "text/plain"),), b"ok") == "ok"
    assert classify(200, (("Content-Type", "application/xhtml+xml"),), _EMPTY_APP) == "shell"
    # Without a declared type the body is treated as HTML.
    assert classify(200, (), _EMPTY_APP) == "shell"
