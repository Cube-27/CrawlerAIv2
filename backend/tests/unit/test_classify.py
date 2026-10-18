"""Block classification (acquisition spec, INV-24): HTTP status and structural body properties only."""

import pytest

from crawlerai.acquire.classify import classify, interstitial
from crawlerai.acquire.types import BlockClass

_HTML = (("content-type", "text/html; charset=utf-8"),)
_JSON = (("content-type", "application/json"),)


def _page(text_chars: int, links: int, extra: str = "") -> str:
    anchors = "".join(f'<a href="/p/{i}"></a>' for i in range(links))
    return f"<html><head><title>t</title></head><body><p>{'x' * text_chars}</p>{anchors}{extra}</body></html>"


_FULL = _page(400, 20)
_EMPTY_APP = '<html><head><script src="/app.js"></script></head><body><div id="root"></div></body></html>'


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, "not_found"),
        (410, "not_found"),
        (401, "blocked"),
        (403, "blocked"),
        (407, "blocked"),
        (451, "blocked"),
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


# --- D-1262: a refusal that stands in for the page until it navigates on ----------------------------------------------

_AT = "https://shop.example.test/item/1"
_SCRIPT = "<script>void 0</script>"
# A refusal with text and links enough to pass the shell rule, whose links all lead off the site or back to the page.
_OFF_SITE = (
    "<html><body><p>"
    + "Checking the connection. " * 20
    + "</p>"
    + "".join(f'<a href="https://help.example.org/{i}">Help {i}</a>' for i in range(6))
    + '<a href="/item/1">Retry</a><a href="#top">Top</a>'
    + "</body></html>"
)


@pytest.mark.parametrize(
    ("status", "headers", "body", "expected"),
    [
        pytest.param(403, _HTML, _EMPTY_APP, True, id="script-shell"),
        pytest.param(503, _HTML, _page(400, 0, _SCRIPT), True, id="script-linkless"),
        pytest.param(429, _HTML, _OFF_SITE.replace("</body>", _SCRIPT + "</body>"), True, id="no-site-link"),
        pytest.param(
            403, _HTML, _page(400, 20, '<meta http-equiv="Refresh" content="5">'), True, id="meta-refresh-with-links"
        ),
        pytest.param(403, (*_HTML, ("refresh", "3")), _page(10, 0), True, id="refresh-header"),
        pytest.param(403, _HTML, _page(10, 0), False, id="static-no-script"),
        pytest.param(403, _HTML, _OFF_SITE, False, id="static-off-site"),
        pytest.param(403, _HTML, _page(400, 20, _SCRIPT), False, id="site-page-with-script"),
        pytest.param(401, _HTML, _EMPTY_APP, False, id="asks-for-credentials"),
        pytest.param(451, _HTML, _EMPTY_APP, False, id="legal-refusal"),
        pytest.param(200, _HTML, _EMPTY_APP, False, id="not-a-refusal"),
        pytest.param(403, _JSON, _EMPTY_APP, False, id="not-html"),
    ],
)
def test_an_interstitial_is_a_refusal_that_can_navigate_and_is_no_page_of_the_site(
    status: int, headers: tuple[tuple[str, str], ...], body: str, expected: bool
) -> None:
    assert interstitial(status, headers, body, _AT) is expected
