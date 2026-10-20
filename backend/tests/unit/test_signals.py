"""Detect-and-report signals (`content.signals`): each fixture raises exactly its signal, and a plain page none."""

import pytest

from crawlerai.content.page import ParsedPage
from crawlerai.content.signals import SIGNALS, Signal, page_signals
from crawlerai.storage.capture_bundle import NetworkBody

_PLAIN = (
    '<html><head><link rel="canonical" href="/p/1"><script src="/static/app.js"></script></head>'
    "<body><h1>Desk lamp</h1><p class=price>$19.99</p><span>In stock</span></body></html>"
)
_SHA = "0" * 64


def _page(html: str = _PLAIN, content_type: str | None = None) -> ParsedPage:
    entries = (
        ()
        if content_type is None
        else (NetworkBody(url="/rpc", status=200, content_type=content_type, sha256=_SHA, file="network/0001.json"),)
    )
    return ParsedPage(html, (b"",) * len(entries), entries)


def _body(markup: str) -> str:
    return _PLAIN.replace("<span>In stock</span>", markup)


_FIXTURES: dict[Signal, tuple[ParsedPage, dict[str, int] | None, tuple[str, ...]]] = {
    "websocket": (_page(), {"document": 1, "websocket": 1}, ()),
    "eventsource": (_page(), {"document": 1, "eventsource": 2}, ()),
    "wasm": (_page(), {"fetch": 1, "application/wasm": 1}, ()),
    "grpc_web": (_page(content_type="application/grpc-web+proto"), None, ()),
    "flutter": (_page(_body("<flutter-view><flt-glass-pane>Lamp</flt-glass-pane></flutter-view>")), None, ()),
    "blazor_wasm": (_page(_body('<script src="/_framework/blazor.webassembly.js"></script>')), None, ()),
    "live_view": (_page(_body('<div data-phx-main phx-click="buy">Buy</div>')), None, ()),
    "obfuscated_text": (_page(), None, ("\ue012\ue019.\ue013\ue013",)),
    "closed_shadow_root": (_page(_body('<price-tag data-sku="1"></price-tag>')), None, ()),
    "turbo_stream": (
        _page(_body('<script>window.__reactRouterContext.streamController.enqueue("[1]");</script>')),
        None,
        (),
    ),
    "gatsby_page_data": (
        _page(_body('<link rel="preload" as="fetch" href="/page-data/p/1/page-data.json">')),
        None,
        (),
    ),
    "amp_alternate": (_page(_body('<link rel="amphtml" href="/amp/p/1">')), None, ()),
}


def test_every_signal_has_a_fixture() -> None:
    assert set(_FIXTURES) == set(SIGNALS)


@pytest.mark.parametrize("signal", SIGNALS)
def test_fixture_raises_exactly_its_signal(signal: Signal) -> None:
    page, resources, money = _FIXTURES[signal]
    assert page_signals(page, resources, money) == (signal,)


def test_plain_page_raises_none() -> None:
    resources = {"document": 1, "script": 3, "fetch": 2, "image": 4}
    assert page_signals(_page(), resources, ("$19.99",)) == ()


def test_declarative_shadow_root_is_no_closed_root() -> None:
    # The pre-pass flattens the declarative root into its host; the host's own light DOM holds no text either way.
    html = _body('<price-tag><template shadowrootmode="open"><span></span></template></price-tag>')
    assert page_signals(_page(html), None, ()) == ()
