"""Block classification (SPEC-02 §4.3, INV-24): HTTP status and structural body properties only."""

import pytest

from crawlerai.acquire.classify import classify, interstitial, lacks_site_structure
from crawlerai.acquire.types import BlockClass
from crawlerai.db.models import PageKind

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


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (_EMPTY_APP, "shell"),
        (b"", "shell"),
        (_page(199, 4), "shell"),
        (_page(200, 1), "ok"),
        # Enough text, but no hyperlink (`test_a_document_that_links_nowhere_is_blocked_whatever_else_it_holds`).
        (_page(200, 0), "blocked"),
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


def _terminal(message_chars: int, extra: str = "") -> bytes:
    """An error document's shape: a title, a heading and a message, and nothing that links, loads or runs anything."""
    message = " ".join("w" * 9 for _ in range(message_chars // 10))
    return f"<html><head><title>Error</title></head><body><h1>Error</h1><p>{message}</p>{extra}</body></html>".encode()


@pytest.mark.parametrize("message_chars", [250, 500])
def test_a_small_terminal_document_with_a_message_is_blocked(message_chars: int) -> None:
    # Enough text not to be a shell, but no hyperlink, script, style sheet or embedded content: nothing a site's
    # page would render or navigate from. A 200 that answers this is an error page served as success.
    assert classify(200, _HTML, _terminal(message_chars)) == "blocked"


def test_a_document_with_a_hyperlink_is_not_blocked() -> None:
    assert classify(200, _HTML, _terminal(250, '<a href="/">home</a>')) == "ok"


@pytest.mark.parametrize(
    "extra",
    [
        '<script src="/app.js"></script>',
        "<script>start()</script>",
        '<link rel="stylesheet" href="/s.css">',
        '<img src="/i.png" alt="">',
        '<iframe src="/f"></iframe>',
        '<form action="/q"><input name="q"></form>',
        pytest.param("<p>" + "w " * 1000 + "</p>", id="long-text"),
    ],
)
def test_a_document_that_links_nowhere_is_blocked_whatever_else_it_holds(extra: str) -> None:
    # A challenge or error page rendered by scripts, with images and a form, but no hyperlink (HTML Standard §4.6):
    # a site's pages link to one another, a page that links nowhere is not one of them.
    assert classify(200, _HTML, _terminal(250, extra)) == "blocked"


def test_a_small_terminal_document_without_enough_text_stays_a_shell() -> None:
    # The shell rule decides first: a browser retry may render what HTTP did not.
    assert classify(200, _HTML, _terminal(100)) == "shell"


_NAV = "<nav><ul>" + "".join(f'<li><a href="/c/{i}">Section {i}</a></li>' for i in range(8)) + "</ul></nav>"
_PROSE = "<p>" + "A shop that sells kettles and other things for the kitchen. " * 6 + "</p>"


def _listing(grid: str, *, head: str = "", main: bool = True) -> bytes:
    """A listing page's chrome (navigation, prose, a footer of links) around `grid`."""
    footer = "<footer>" + "".join(f'<a href="/help/{i}">Help {i}</a>' for i in range(6)) + "</footer>"
    content = f"<h1>Kettles</h1>{_PROSE}{grid}"
    body = f"<header>{_NAV}</header>{f'<main>{content}</main>' if main else content}{footer}"
    return f"<html><head><title>Kettles</title>{head}</head><body>{body}</body></html>".encode()


def _tiles(count: int, *, tag: str = "li", linked: bool = True) -> str:
    def tile(i: int) -> str:
        name = f'<a href="/p/{i}">Kettle {i}</a>' if linked else f"Kettle {i}"
        return f'<{tag} class="tile"><h3>{name}</h3><span>{i}9.90 EUR</span></{tag}>'

    return '<ul class="grid">' + "".join(tile(i) for i in range(count)) + "</ul>"


_SCRIPT_GRID = '<div id="results"></div><script src="/results.js"></script>'


def test_a_listing_without_repeated_linked_items_is_a_shell_for_the_listing_kind_only() -> None:
    # The grid loads by script: the HTTP page has chrome and text, and no item to read. A detail page, or a page of
    # no declared kind, is judged as before.
    page = _listing(_SCRIPT_GRID)
    kinds: list[PageKind | None] = ["listing", "detail", None]

    assert [classify(200, _HTML, page, page_kind=kind) for kind in kinds] == ["shell", "ok", "ok"]


@pytest.mark.parametrize(
    "page",
    [
        _listing(_tiles(3)),
        _listing(_tiles(24, tag="div")),
        # Without a main landmark, the body outside navigation, header, footer and aside is read.
        _listing(_tiles(3), main=False),
        # Tiles that are links themselves.
        _listing(
            "<div>" + "".join(f'<a class="card" href="/p/{i}"><h3>Kettle {i}</h3></a>' for i in range(4)) + "</div>"
        ),
        # Tiles of one template whose class lists differ by a token of each tile's own.
        _listing(
            "<div>"
            + "".join(f'<div class="card order-{i}"><a href="/p/{i}">Kettle {i}</a></div>' for i in range(4))
            + "</div>"
        ),
        # Rows published as structured data are read without the grid (SPEC-05 §4.7): a JSON-LD ItemList, found at any
        # depth and in a type list, or at least as many microdata items as a grid's.
        _listing(_SCRIPT_GRID, head='<script type="application/ld+json">{"@type": "ItemList"}</script>'),
        _listing(
            _SCRIPT_GRID,
            head='<script type="application/ld+json">{"@graph": [{"@type": ["CollectionPage"], "mainEntity": '
            '{"@type": ["ItemList"]}}]}</script>',
        ),
        # A media type is compared before its parameters, in any case (RFC 9110 §8.3.1).
        _listing(
            _SCRIPT_GRID, head='<script type="Application/LD+JSON; charset=utf-8">[{"@type": "ItemList"}]</script>'
        ),
        _listing(_SCRIPT_GRID + '<div itemscope itemtype="https://schema.org/Product"></div>' * 3),
    ],
)
def test_a_listing_with_repeated_linked_items_or_structured_rows_is_ok(page: bytes) -> None:
    assert classify(200, _HTML, page, page_kind="listing") == "ok"


@pytest.mark.parametrize(
    "page",
    [
        # Structured data about the site or the page, not a list of its items: the grid still loads by script.
        _listing(_SCRIPT_GRID, head='<script type="application/ld+json">{"@type": "WebSite"}</script>'),
        _listing(_SCRIPT_GRID, head='<script type="application/ld+json">{"@type": "ItemList"</script>'),
        _listing(_SCRIPT_GRID + '<div itemscope itemtype="https://schema.org/WebSite"></div>' * 2),
        # Nested items are properties of their holder, not items the page lists.
        _listing(
            _SCRIPT_GRID
            + '<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
            + '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">x</li>' * 3
            + "</ol>"
        ),
        # Script state may hold the rows or not; the browser renders the grid from it either way.
        _listing(_SCRIPT_GRID + '<script type="application/json">{"items": []}</script>'),
    ],
)
def test_a_listing_whose_structured_data_lists_no_items_is_a_shell(page: bytes) -> None:
    assert classify(200, _HTML, page, page_kind="listing") == "shell"


@pytest.mark.parametrize(
    "page",
    [
        _listing(_tiles(2)),
        _listing(_tiles(6, linked=False)),
        # Navigation and footer links repeat, but they are the site's chrome, not its items (HTML landmarks).
        _listing(""),
        _listing("", main=False),
    ],
)
def test_too_few_items_unlinked_items_or_only_chrome_links_are_no_listing(page: bytes) -> None:
    assert classify(200, _HTML, page, page_kind="listing") == "shell"


@pytest.mark.parametrize(
    ("body", "expected"),
    [(_EMPTY_APP, True), (_page(199, 4), True), (_page(400, 0), True), (_page(200, 1), False), (_FULL, False)],
)
def test_site_structure_is_judged_by_the_2xx_rules_whatever_the_status(body: bytes, expected: bool) -> None:
    # The browser reads it on a 403/429/503 document (D-1206), where `classify` answers by status alone.
    assert lacks_site_structure(body) is expected
    assert lacks_site_structure(body) is (classify(200, _HTML, body) != "ok")


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
        pytest.param(429, _HTML, _OFF_SITE.replace("</body>", _SCRIPT + "</body>").encode(), True, id="no-site-link"),
        pytest.param(
            403, _HTML, _page(400, 20, '<meta http-equiv="Refresh" content="5">'), True, id="meta-refresh-with-links"
        ),
        pytest.param(403, (*_HTML, ("refresh", "3")), _page(10, 0), True, id="refresh-header"),
        pytest.param(403, _HTML, _page(10, 0), False, id="static-no-script"),
        pytest.param(403, _HTML, _OFF_SITE.encode(), False, id="static-off-site"),
        pytest.param(403, _HTML, _page(400, 20, _SCRIPT), False, id="site-page-with-script"),
        pytest.param(401, _HTML, _EMPTY_APP, False, id="asks-for-credentials"),
        pytest.param(451, _HTML, _EMPTY_APP, False, id="legal-refusal"),
        pytest.param(200, _HTML, _EMPTY_APP, False, id="not-a-refusal"),
        pytest.param(403, _JSON, _EMPTY_APP, False, id="not-html"),
    ],
)
def test_an_interstitial_is_a_refusal_that_can_navigate_and_is_no_page_of_the_site(
    status: int, headers: tuple[tuple[str, str], ...], body: bytes, expected: bool
) -> None:
    assert interstitial(status, headers, body, _AT) is expected
